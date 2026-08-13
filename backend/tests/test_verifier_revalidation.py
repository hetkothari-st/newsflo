"""Corrective-v4 Task 9: the verifier's counterfactual verdict is wired
into the publication gate for real, the transitional "SUPPORTED" constant
is gone, and the remaining fail-open holes in the verifier path (narrow-path
budget exhaustion, silence-as-acceptance) are closed. Every test here drives
the REAL engine (app.analysis.impact_graph.engine.analyze_article_v3) through
a FakeRouter -- no network anywhere -- then feeds the result through
app.pipeline._v3_entries so the gate wiring is exercised end to end, not just
unit-tested on a hand-built CandidateInput."""
import pytest

from app.config import settings
from app.models import Company, CompanyNodeExposure, utcnow
from app.pipeline import _v3_entries
from tests.test_impact_graph import FACTS, FakeRouter, _company_entry, _edge


@pytest.fixture()
def strict_mode(monkeypatch):
    monkeypatch.setattr(settings, "impact_engine_v4_strict", True)


def _company_with_profile(db, ticker, name, sector):
    """A row with a real business_desc -- enough on its own to satisfy
    BUSINESS_MODEL_VALID (app.pipeline._company_profile_supports_mechanism),
    so these tests can isolate the verifier-wiring behavior under test
    instead of tripping an unrelated gate first."""
    row = Company(name=name, ticker=ticker, sector=sector, index_tier="NIFTY50",
                  business_desc=f"{name} is a real operating business in {sector}")
    db.add(row)
    db.commit()
    return row


def _company_with_exposure(db, ticker, name, sector, node_key):
    """Tier D (MODEL_VERIFIED_PRIOR) evidence via a fresh CompanyNodeExposure
    row -- authorizes display (unlike Tier E/MODEL_INFERENCE, which the
    materiality composite caps to LOW) without needing a SupplyLink."""
    row = _company_with_profile(db, ticker, name, sector)
    db.add(CompanyNodeExposure(
        company_id=row.id, node_key=node_key, exposure_exists=1,
        strength=0.8, mechanism="verified exposure", verified_at=utcnow()))
    db.commit()
    return row


def _entry(ticker, name, **overrides):
    """_company_entry's default mechanism ("fuel cost exposure", 19 chars)
    is one character short of MECHANISM_VALID's 20-char floor -- fine for
    test_impact_graph.py's engine-only tests, which never reach the gate,
    but these tests do. Give every entry a mechanism/rationale long enough
    to clear that gate on its own so the assertions under test aren't
    accidentally exercising a different one."""
    payload = _company_entry(ticker, name)
    payload["mechanism"] = "company-specific fuel cost exposure tied directly to this shock"
    payload["rationale"] = "operating costs move with crude oil prices for this specific company"
    payload.update(overrides)
    return payload


# --- narrow-path budget exhaustion fails closed ----------------------------

def test_narrow_budget_exhaustion_fails_closed(db_session, strict_mode):
    """The narrow single-call path used to trust its in-call self-check
    (verified=True) whenever a hard budget overrun skipped the independent
    verify call -- unlike the broad path, it never recorded
    verification_unavailable or degraded router.quality. Strict mode always
    treats the narrow result as risky (settings.impact_engine_v4_strict),
    so budget exhaustion here must fail exactly as closed as a broad-path
    overrun or a verifier outage. Uses _company_with_exposure (not just
    _company_with_profile) so the candidate clears MATERIALITY_VALID/
    EVIDENCE_VALID on a pre-existing Tier D record -- the verifier never
    runs in this scenario, so there is no fresh cache write to earn that
    tier the normal way, and the point under test is the VERIFIED gate
    specifically, not an incidental materiality/evidence rejection."""
    _company_with_exposure(db_session, "NARROW.NS", "Narrow Co", "fmcg", "fmcg")
    router = FakeRouter({
        "extract_facts": dict(FACTS, event_type="earnings"),
        "narrow_graph": {
            "shocks": [{"shock_id": "demand_hit", "label": "Demand hit", "direction": "bearish",
                        "mechanism": "m", "confidence": 0.85, "materiality": 0.7,
                        "impact_strength": 0.6}],
            "edges": [_edge("demand_hit", "fmcg", child_type="sector", mat=0.6, conf=0.8)],
        },
        "narrow_companies": {"companies": [
            dict(_entry("NARROW.NS", "Narrow Co"), parent_id="fmcg", net_direction="bearish"),
        ]},
    })
    # No settings monkeypatch needed: the narrow tier's own output-token
    # ceiling (IMPACT_TRIAGE_TIERS["narrow"]["max_output_tokens"]) governs
    # once analyze_article_v3 sets budget.max_output_override -- pre-record
    # comfortably past it so `budget.exceeded` is True by the time the
    # engine reaches the verification decision.
    router.budget.record("narrow_graph", output_tokens=999_999)

    from app.analysis.impact_graph.engine import analyze_article_v3
    result = analyze_article_v3(router, "t", "c", session=db_session)

    assert "verify_companies" not in router.calls
    assert result.metrics.get("verification_unavailable") == 1
    assert result.analysis_quality == "budget_exhausted"
    assert result.companies[0].verified is False

    entries = _v3_entries(db_session, result)
    assert entries[0]["gate_state"] == "REJECT_VALIDATOR_UNAVAILABLE"


# --- verifier silence is not acceptance ------------------------------------

def test_verifier_silence_is_not_acceptance(db_session, strict_mode):
    """A ticker the verifier's response mentions in NEITHER accept[] NOR
    reject[] must NOT display. The old comment here read "a company with
    neither verdict is KEPT (omission is not rejection)" -- true of
    state.companies membership, but that must never be read as acceptance:
    the company's `verified` flag stays False (reset before the call, never
    set True for it), so REJECT_UNVERIFIED is the correct verdict at
    _check_verified. In practice a company this silent-on-everything also
    never appears in the verifier's counterfactual map, so its
    counterfactual stays "" too and COUNTERFACTUAL_VALID -- earlier in
    GATE_SEQUENCE -- rejects first with REJECT_VALIDATOR_UNAVAILABLE; either
    way the outcome is the same fail-closed non-display, which is the
    property this test actually pins. Uses _company_with_exposure (not just
    _company_with_profile): this candidate is never accepted, so no fresh
    cache write earns it a display-authorizing evidence tier the normal
    way -- a pre-existing Tier D record isolates the gate rejection under
    test from an incidental materiality/evidence one."""
    _company_with_exposure(db_session, "SILENT.NS", "Silent Co", "oil_gas", "oil_gas")
    router = FakeRouter({
        "extract_facts": FACTS,
        "initial_shocks": {"shocks": [], "direct_nodes": [
            _edge("event", "oil_gas", child_type="sector", parent_type="event", mat=0.7, conf=0.8),
        ]},
        "map_companies": {"companies": [_entry("SILENT.NS", "Silent Co")]},
        "ripple_discovery": [{"children": []}],
        # Neither accepts nor rejects SILENT.NS -- pure silence.
        "verify_companies": {"accept": [], "reject": []},
    })
    from app.analysis.impact_graph.engine import analyze_article_v3
    result = analyze_article_v3(router, "t", "c", session=db_session)

    assert [c.ticker for c in result.companies] == ["SILENT.NS"]
    assert result.companies[0].verified is False        # never quietly accepted
    assert result.companies[0].counterfactual == ""      # never quietly UNCERTAIN either
    assert not result.metrics.get("verification_unavailable")  # the verifier DID run

    entries = _v3_entries(db_session, result)
    # COUNTERFACTUAL_VALID precedes VERIFIED in GATE_SEQUENCE, so a company
    # this silent rejects there first -- but the underlying property this
    # test pins is that NEITHER gate was fooled into accepting silence.
    assert entries[0]["gate_state"] in ("REJECT_VALIDATOR_UNAVAILABLE", "REJECT_UNVERIFIED")
    assert entries[0]["display_tier"] == "excluded"


# --- corrections are revalidated by the gate, not rubber-stamped ----------

def test_correction_is_revalidated_by_gate(db_session, strict_mode):
    """A verifier correction that raises materiality (0.3 -> 0.7) must reach
    the gate as the corrected float, not the original one -- and the rest of
    the composite/evidence system (Task 4/8) must still evaluate the
    CORRECTED candidate on its own merits rather than rubber-stamping it.

    Note on evidence tier: an ACCEPTED company always earns at least Tier D
    (MODEL_VERIFIED_PRIOR) by the time _v3_entries runs, because
    _verify_companies' own _write_exposure_cache writes a fresh
    CompanyNodeExposure row for every verified company before returning --
    the verifier's acceptance IS the independent check that earns Tier D
    (see evidence.py's classify_evidence docstring). So a genuinely Tier-E
    (MODEL_INFERENCE) accepted candidate cannot occur via the real pipeline;
    that combination is exercised directly at the gate-unit level in
    test_v4_strict_gate_wiring.py instead. What DOES persist here is Task
    4's evidence-tier cap on primary authorization (canonical policy table:
    "tier D is a deep dive") -- the correction earns a HIGH materiality
    grade and DISPLAY_ELIGIBLE, but Tier D still holds it to
    secondary_deep_dive, exactly as it would have BEFORE the correction."""
    row = Company(name="Corr Co", ticker="CORR.NS", sector="oil_gas", index_tier="NIFTY50")
    db_session.add(row)
    db_session.commit()
    router = FakeRouter({
        "extract_facts": FACTS,
        "initial_shocks": {"shocks": [], "direct_nodes": [
            _edge("event", "oil_gas", child_type="sector", parent_type="event", mat=0.7, conf=0.8),
        ]},
        "map_companies": {"companies": [_entry("CORR.NS", "Corr Co", materiality=0.3)]},
        "ripple_discovery": [{"children": []}],
        "verify_companies": {
            "accept": ["CORR.NS"], "reject": [],
            "corrections": [{"ticker": "CORR.NS", "materiality": 0.7}],
            "counterfactual": {"CORR.NS": "SUPPORTED"},
        },
    })
    from app.analysis.impact_graph.engine import analyze_article_v3
    result = analyze_article_v3(router, "t", "c", session=db_session)

    assert result.companies[0].materiality == 0.7  # correction carried through

    entries = _v3_entries(db_session, result)
    assert entries[0]["materiality"] == 0.7          # gate saw the CORRECTED float
    assert entries[0]["materiality_grade"] == "HIGH"  # 0.7 >= the HIGH cutoff, no cap in play here
    assert entries[0]["gate_state"] == "DISPLAY_ELIGIBLE"
    assert entries[0]["display_tier"] == "secondary_deep_dive"  # Tier D cap still applies


# --- counterfactual verdict flows from the verifier to the gate -----------

def test_counterfactual_flows_from_verdict_to_gate(db_session, strict_mode):
    """The verifier's real per-ticker counterfactual verdict -- not a
    pipeline constant -- decides COUNTERFACTUAL_VALID. NOT_SUPPORTED
    rejects as a generic, non-event-specific story; an ACCEPTED company the
    verifier's map omits falls back to UNCERTAIN (spec §25/§31: displayable
    as a deep dive, never primary, never excluded outright)."""
    _company_with_exposure(db_session, "NOTSUP.NS", "NotSup Co", "oil_gas", "oil_gas")
    _company_with_exposure(db_session, "OMIT.NS", "Omitted Co", "oil_gas", "oil_gas")
    router = FakeRouter({
        "extract_facts": FACTS,
        "initial_shocks": {"shocks": [], "direct_nodes": [
            _edge("event", "oil_gas", child_type="sector", parent_type="event", mat=0.7, conf=0.8),
        ]},
        "map_companies": {"companies": [
            _entry("NOTSUP.NS", "NotSup Co"),
            _entry("OMIT.NS", "Omitted Co"),
        ]},
        "ripple_discovery": [{"children": []}],
        "verify_companies": {
            "accept": ["NOTSUP.NS", "OMIT.NS"], "reject": [],
            # OMIT.NS is deliberately absent from this map.
            "counterfactual": {"NOTSUP.NS": "NOT_SUPPORTED"},
        },
    })
    from app.analysis.impact_graph.engine import analyze_article_v3
    result = analyze_article_v3(router, "t", "c", session=db_session)

    by_ticker = {c.ticker: c for c in result.companies}
    assert by_ticker["NOTSUP.NS"].counterfactual == "NOT_SUPPORTED"
    assert by_ticker["OMIT.NS"].counterfactual == "UNCERTAIN"

    entries = _v3_entries(db_session, result)
    id_to_ticker = {
        db_session.query(Company).filter_by(ticker=c.ticker).one().id: c.ticker
        for c in result.companies
    }
    by_gate = {id_to_ticker[e["company_id"]]: e for e in entries}

    assert by_gate["NOTSUP.NS"]["gate_state"] == "REJECT_NOT_EVENT_SPECIFIC"
    assert by_gate["OMIT.NS"]["gate_state"] == "DISPLAY_ELIGIBLE"
    assert by_gate["OMIT.NS"]["display_tier"] != "primary"
