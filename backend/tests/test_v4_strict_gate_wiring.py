"""Publication-gate wiring (spec §5/§35, INV-005/006/019/020): in strict
mode every v3 company candidate is gate-evaluated at the persistence
boundary. Excluded candidates never become AlertCompany rows but always
leave a durable CompanyDecisionRecord; eligible rows carry their tier.
Flag off: byte-identical legacy persistence, no gate, no records."""
import pytest

from app.config import settings
from app.models import Alert, Article, Company, CompanyDecisionRecord, CompanyNodeExposure, utcnow
from app.pipeline import _v3_entries


@pytest.fixture()
def strict_mode(monkeypatch):
    monkeypatch.setattr(settings, "impact_engine_v4_strict", True)


@pytest.fixture()
def legacy_mode(monkeypatch):
    monkeypatch.setattr(settings, "impact_engine_v4_strict", False)


def _company_row(db, ticker="ONGC.NS", name="ONGC", sector="oil_gas",
                 verified_node=None, business_desc="Upstream oil and gas explorer"):
    # business_desc is load-bearing since Task 4: BUSINESS_MODEL_VALID
    # rejects a candidate whose company profile cannot support the claimed
    # mechanism unless the evidence is structured tier A/B.
    row = Company(name=name, ticker=ticker, sector=sector, index_tier="NIFTY50",
                  business_desc=business_desc)
    db.add(row)
    db.commit()
    if verified_node is not None:
        db.add(CompanyNodeExposure(
            company_id=row.id, node_key=verified_node, exposure_exists=1,
            strength=0.8, mechanism="verified exposure", verified_at=utcnow()))
        db.commit()
    return row


def _graph_company(**overrides):
    from app.analysis.impact_graph.schemas import GraphCompany
    payload = dict(
        ticker="ONGC.NS", name="ONGC", direction="bullish",
        impact_strength=0.7, confidence=0.8, materiality=0.7, causal_distance=1,
        time_horizon="Short-Term", parent_type="economic_node", parent_id="crude_price",
        mechanism="upstream crude realization: higher price lifts revenue per barrel",
        rationale="unhedged upstream producer with crude-linked realization",
        net_direction="bullish", economic_effect="positive", verified=True,
        # These tests exercise gates OTHER than COUNTERFACTUAL_VALID; a
        # verifier-delivered SUPPORTED keeps that gate a non-factor here
        # (Task 9 killed the pipeline's old hardcoded "SUPPORTED" constant,
        # but GraphCompany itself now defaults counterfactual="" -- the
        # "verifier never reached this company" state, which would reject
        # every one of these fixtures on a gate they are not testing).
        counterfactual="SUPPORTED",
    )
    payload.update(overrides)
    return GraphCompany(**payload)


def _graph_edge(**overrides):
    from app.analysis.impact_graph.schemas import GraphEdge
    payload = dict(
        parent_type="event", parent_id="crude_supply_shock",
        child_type="economic_node", child_id="crude_price",
        direction="bullish", economic_effect="positive",
        mechanism="supply disruption raises crude price", causal_distance=1,
        impact_strength=0.8, confidence=0.9, materiality=0.7,
        time_horizon="Short-Term",
    )
    payload.update(overrides)
    return GraphEdge(**payload)


def _result(companies, edges=None, quality="authoritative"):
    from app.analysis.impact_graph.schemas import ImpactGraphResult
    return ImpactGraphResult(
        category="commodity", event_type="crude_oil", facts="crude up 5%",
        event_label="crude supply shock", named_entities=[],
        companies=companies, edges=edges if edges is not None else [_graph_edge()],
        gaps=[], ranking=[], analysis_provider="gemini", analysis_quality=quality,
        metrics={},
    )


# --- entry annotation (strict) --------------------------------------------

def test_strict_entries_carry_gate_decision(db_session, strict_mode):
    _company_row(db_session, verified_node="crude_price")
    entries = _v3_entries(db_session, _result([_graph_company()]))

    assert len(entries) == 1
    # A bare CompanyNodeExposure row is Tier-D evidence (MODEL_VERIFIED_PRIOR,
    # corrective-v4 Task 5) -- eligible, but not primary-authorizing.
    assert entries[0]["display_tier"] == "secondary_deep_dive"
    assert entries[0]["gate_state"] == "DISPLAY_ELIGIBLE"


def test_strict_no_business_profile_is_insufficient_evidence(db_session, strict_mode):
    """Task 4 / canonical policy table: a company the system can neither
    describe nor show an exposure record for cannot carry a mechanism claim
    unless the evidence is structured tier A/B."""
    _company_row(db_session, business_desc=None)   # no desc, no exposure row
    entries = _v3_entries(db_session, _result([_graph_company()]))

    assert entries[0]["display_tier"] == "excluded"
    assert entries[0]["gate_state"] == "REJECT_INSUFFICIENT_EVIDENCE"
    assert "BUSINESS_MODEL_VALID" not in entries[0]["gates_passed"]


def test_strict_unverified_candidate_excluded(db_session, strict_mode):
    _company_row(db_session, verified_node="crude_price")
    entries = _v3_entries(db_session, _result([_graph_company(verified=False)]))

    assert entries[0]["display_tier"] == "excluded"
    assert entries[0]["gate_state"] == "REJECT_UNVERIFIED"


@pytest.mark.parametrize("verified", [False, True])
def test_strict_budget_exhausted_fails_closed(db_session, strict_mode, verified):
    """INV-005/016: verification never ran -> nothing may display, INCLUDING
    a company carrying verified=True. Budget exhaustion skips verification
    entirely, so that flag is the engine's own in-call self-check, not an
    independent verdict -- the gate must not let it through (Task 4 review
    C1: this exact combination was fail-open end to end)."""
    _company_row(db_session, verified_node="crude_price")
    entries = _v3_entries(db_session, _result(
        [_graph_company(verified=verified)], quality="budget_exhausted"))

    assert entries[0]["display_tier"] == "excluded"
    assert entries[0]["gate_state"] == "REJECT_VALIDATOR_UNAVAILABLE"


def test_strict_verifier_outage_fails_closed_even_when_verified(db_session, strict_mode):
    """Same fail-open shape via the other path: the verifier router died,
    the result says so in metrics, and the company still carries
    verified=True from an earlier stage."""
    from app.analysis.impact_graph.schemas import ImpactGraphResult

    _company_row(db_session, verified_node="crude_price")
    result = ImpactGraphResult(
        category="commodity", event_type="crude_oil", facts="crude up 5%",
        event_label="crude supply shock", named_entities=[],
        companies=[_graph_company(verified=True)], edges=[_graph_edge()],
        gaps=[], ranking=[], analysis_provider="gemini",
        analysis_quality="authoritative", metrics={"verification_unavailable": 1},
    )
    entries = _v3_entries(db_session, result)

    assert entries[0]["gate_state"] == "REJECT_VALIDATOR_UNAVAILABLE"


def test_strict_exposure_row_alone_supports_business_model_gate(db_session, strict_mode):
    """Task 4 review I3: a fresh verified exposure row for the mechanism's
    own node IS a grounded statement about the business at that dimension --
    a company with no business_desc is not automatically unpublishable."""
    _company_row(db_session, verified_node="crude_price", business_desc=None)
    entries = _v3_entries(db_session, _result([_graph_company()]))

    assert entries[0]["gate_state"] == "DISPLAY_ELIGIBLE"
    assert "BUSINESS_MODEL_VALID" in entries[0]["gates_passed"]


def test_strict_duplicate_company_second_occurrence_rejected(db_session, strict_mode):
    """Task 4 review I2: two candidates resolving to ONE company row are one
    row to the reader. The second is REJECT_DUPLICATE with its decision
    preserved -- not silently swallowed by ticker-keyed collection."""
    _company_row(db_session, verified_node="crude_price")
    entries = _v3_entries(db_session, _result([
        _graph_company(materiality=0.8),
        _graph_company(materiality=0.5, rationale="second bite at the same company"),
    ]))

    assert len(entries) == 2
    assert entries[0]["gate_state"] == "DISPLAY_ELIGIBLE"
    assert entries[1]["gate_state"] == "REJECT_DUPLICATE"
    assert entries[1]["display_tier"] == "excluded"


def test_counterfactual_wired_from_graph_company_not_hardcoded(db_session, strict_mode):
    """Task 9 replacement for the killed transitional-constant pin: the
    gate's counterfactual input is the real per-company verdict carried on
    GraphCompany, not a literal in _gate_candidates. An empty verdict (the
    engine default -- verifier never reached this company at all) fails
    closed even though every other gate would pass this candidate."""
    _company_row(db_session, verified_node="crude_price")
    entries = _v3_entries(db_session, _result([_graph_company(counterfactual="")]))

    assert entries[0]["gate_state"] == "REJECT_VALIDATOR_UNAVAILABLE"
    assert entries[0]["display_tier"] == "excluded"

def test_strict_dangling_causal_path_not_event_specific(db_session, strict_mode):
    """A company whose parent chain does not root in this event's own
    graph is a generic story (spec §14) -- fail closed."""
    _company_row(db_session)
    orphan = _graph_company(parent_id="macro_uncertainty")
    entries = _v3_entries(db_session, _result([orphan]))

    assert entries[0]["gate_state"] == "REJECT_NOT_EVENT_SPECIFIC"


def test_strict_price_movement_rationale_never_primary(db_session, strict_mode):
    """INV-003: rationale grounded in the observed stock move is market
    observation, not fundamental evidence."""
    _company_row(db_session)
    mover = _graph_company(
        rationale="the stock fell 3% after the announcement",
        mechanism="shares dropped sharply on the news of the crude spike")
    entries = _v3_entries(db_session, _result([mover]))

    assert entries[0]["display_tier"] != "primary"


def test_strict_supply_link_upgrades_evidence_to_primary(db_session, strict_mode):
    """A SupplyLink-backed relationship is real Tier-C evidence (corrective-
    v4 Task 5: a bare CompanyNodeExposure cache row no longer is -- see
    test_strict_entries_carry_gate_decision): d2 primary becomes possible
    (spec §13)."""
    from datetime import date

    from app.models import SupplyLink

    parent = _company_row(db_session, ticker="MARUTI.NS", name="Maruti Suzuki", sector="auto")
    supplier = _company_row(db_session, ticker="MOTHERSON.NS", name="Samvardhana Motherson",
                            sector="auto_components")
    db_session.add(SupplyLink(
        company_id=parent.id, counterparty_company_id=supplier.id,
        counterparty_name="Samvardhana Motherson", relation="SUPPLIER",
        evidence="Samvardhana Motherson supplies wiring harnesses for our vehicle programmes",
        source_url="https://crisil.example/rationale", source_agency="CRISIL",
        as_of=date.today()))
    db_session.commit()

    d2 = _graph_company(
        ticker="MOTHERSON.NS", name="Samvardhana Motherson", causal_distance=2, materiality=0.7,
        parent_type="company", parent_id="MARUTI.NS",
        mechanism="volume cut at Maruti reduces component offtake",
        rationale="tier-1 supplier to the affected OEM",
    )
    edges = [_graph_edge(child_type="company", child_id="MARUTI.NS")]
    entries = _v3_entries(db_session, _result([d2], edges=edges))

    assert entries[0]["evidence_class"] == "VERIFIED_RELATIONSHIP"
    assert entries[0]["display_tier"] == "primary"


def test_strict_model_inference_d2_is_insufficient_evidence(db_session, strict_mode):
    """Policy change (corrective-v4 Task 4): tier E used to buy a quiet
    secondary slot. Model inference alone now authorizes nothing at all.

    Task 8 note: the composite materiality grade
    (app.analysis.impact_graph.materiality) caps tier E to LOW *before* the
    gate walk even starts, and MATERIALITY_VALID runs before EVIDENCE_VALID
    in GATE_SEQUENCE -- so this candidate now rejects one gate earlier, on
    REJECT_LOW_MATERIALITY rather than REJECT_INSUFFICIENT_EVIDENCE. Same
    root cause (tier E can never authorize display), same excluded outcome;
    only the specific machine-readable reason moved upstream."""
    d2 = _graph_company(causal_distance=2, materiality=0.7)
    _company_row(db_session)
    entries = _v3_entries(db_session, _result([d2]))

    assert entries[0]["evidence_class"] == "MODEL_INFERENCE"
    assert entries[0]["display_tier"] == "excluded"
    assert entries[0]["gate_state"] == "REJECT_LOW_MATERIALITY"


def test_strict_primary_cap_demotes_overflow_to_deep_dive(db_session, strict_mode, monkeypatch):
    """finalize_alert_decisions runs at the alert boundary: the overflow is
    demoted, never dropped (INV-015). Needs genuinely primary-eligible
    candidates (corrective-v4 Task 5: a bare CompanyNodeExposure row is only
    Tier D, not primary-authorizing) -- SupplyLink-backed Tier-C evidence at
    d2 gives both candidates a real shot at primary so the cap has something
    to demote."""
    from datetime import date

    from app.models import SupplyLink

    monkeypatch.setattr(settings, "impact_max_primary_companies", 1)
    parent = _company_row(db_session, ticker="PARENT.NS", name="Parent Co", sector="auto")
    for i in range(2):
        supplier = _company_row(db_session, ticker=f"CO{i}.NS", name=f"Co{i}",
                                sector="auto_components")
        db_session.add(SupplyLink(
            company_id=parent.id, counterparty_company_id=supplier.id,
            counterparty_name=f"Co{i}", relation="SUPPLIER",
            evidence=f"Co{i} supplies components used in Parent Co's vehicle programmes",
            source_url=f"https://crisil.example/rationale-{i}", source_agency="CRISIL",
            as_of=date.today()))
    db_session.commit()

    companies = [
        _graph_company(ticker="CO0.NS", name="Co0", materiality=0.9, causal_distance=2,
                       parent_type="company", parent_id="PARENT.NS"),
        _graph_company(ticker="CO1.NS", name="Co1", materiality=0.7, causal_distance=2,
                       parent_type="company", parent_id="PARENT.NS"),
    ]
    edges = [_graph_edge(child_type="company", child_id="PARENT.NS")]
    entries = _v3_entries(db_session, _result(companies, edges=edges))

    tiers = {e["display_tier"] for e in entries}
    assert tiers == {"primary", "secondary_deep_dive"}
    overflow = [e for e in entries if e["display_tier"] == "secondary_deep_dive"]
    assert overflow[0]["decision_notes"] == "primary_cap_overflow"
    assert len(entries) == 2


def test_legacy_entries_have_no_gate_fields(db_session, legacy_mode):
    _company_row(db_session)
    entries = _v3_entries(db_session, _result([_graph_company()]))

    assert "display_tier" not in entries[0]
    assert "gate_state" not in entries[0]


# --- persistence (strict): excluded rows never become AlertCompany --------

def _persist(db, entries_result, monkeypatch=None):
    from app.pipeline import _persist_alert, _v3_edges
    article = Article(source="s", provider="finnhub", url="https://ex.com/a",
                      title="crude spikes", content="c", status="CATEGORIZED")
    db.add(article)
    db.commit()
    entries = _v3_entries(db, entries_result)
    return _persist_alert(
        db, article, "commodity", entries, event_type="crude_oil",
        gaps=[], edges=_v3_edges(entries_result), client=None,
        facts="crude up 5%", analysis_provider="gemini",
        analysis_quality=entries_result.analysis_quality,
    )


def test_strict_persist_skips_excluded_and_records_decisions(db_session, strict_mode):
    _company_row(db_session, verified_node="crude_price")
    _company_row(db_session, ticker="WEAKCO.NS", name="WeakCo", sector="oil_gas",
                 verified_node="crude_price")
    result = _result([
        _graph_company(),                                              # primary
        _graph_company(ticker="WEAKCO.NS", name="WeakCo", verified=False),  # excluded
    ])
    alert = _persist(db_session, result)

    from app.models import AlertCompany
    rows = db_session.query(AlertCompany).filter_by(alert_id=alert.id).all()
    # Bare CompanyNodeExposure evidence is Tier D (corrective-v4 Task 5),
    # not primary-authorizing -- secondary_deep_dive is the honest tier
    # here. The point under test is exclusion + decision-record bookkeeping.
    assert [r.display_tier for r in rows] == ["secondary_deep_dive"]

    records = db_session.query(CompanyDecisionRecord).filter_by(alert_id=alert.id).all()
    assert len(records) == 2
    by_ticker = {r.ticker: r for r in records}
    assert by_ticker["ONGC.NS"].final_state == "DISPLAY_ELIGIBLE"
    assert by_ticker["WEAKCO.NS"].final_state == "REJECT_UNVERIFIED"
    assert by_ticker["WEAKCO.NS"].rejection_reason == "REJECT_UNVERIFIED"


# --- engine fail-closed behavior (strict) ---------------------------------

def test_strict_narrow_path_always_verifies_independently(db_session, strict_mode):
    """Strict mode never trusts the narrow path's in-call self-check
    (INV-005): independent verification runs even for low-risk results."""
    from tests.test_impact_graph import FACTS, FakeRouter, _company, _company_entry, _edge

    _company(db_session, "NARROW.NS", "Narrow Co", "fmcg")
    router = FakeRouter({
        "extract_facts": dict(FACTS, event_type="earnings"),
        "narrow_graph": {
            "shocks": [{"shock_id": "demand_hit", "label": "Demand hit", "direction": "bearish",
                        "mechanism": "m", "confidence": 0.85, "materiality": 0.7,
                        "impact_strength": 0.6}],
            "edges": [_edge("demand_hit", "fmcg", child_type="sector", mat=0.6, conf=0.8)],
        },
        "narrow_companies": {"companies": [
            dict(_company_entry("NARROW.NS", "Narrow Co", impact=0.5, conf=0.8),
                 parent_id="fmcg", net_direction="bearish"),  # NOT risky
        ]},
        "verify_companies": {"accept": ["NARROW.NS"], "reject": []},
    })
    from app.analysis.impact_graph.engine import analyze_article_v3
    result = analyze_article_v3(router, "t", "c", session=db_session)

    assert "verify_companies" in router.calls
    assert result.companies[0].verified is True


def test_verification_router_failure_marks_metric(db_session, strict_mode):
    """When the verifier cannot run at all, the result must say so --
    the gate turns that into REJECT_VALIDATOR_UNAVAILABLE (INV-005/016)."""
    from app.analysis.impact_graph.router import StageRouterError
    from tests.test_impact_graph import FACTS, FakeRouter, _company, _company_entry, _edge

    _company(db_session, "NARROW.NS", "Narrow Co", "fmcg")
    router = FakeRouter({
        "extract_facts": dict(FACTS, event_type="earnings"),
        "narrow_graph": {
            "shocks": [{"shock_id": "demand_hit", "label": "Demand hit", "direction": "bearish",
                        "mechanism": "m", "confidence": 0.85, "materiality": 0.7,
                        "impact_strength": 0.6}],
            "edges": [_edge("demand_hit", "fmcg", child_type="sector", mat=0.6, conf=0.8)],
        },
        "narrow_companies": {"companies": [
            dict(_company_entry("NARROW.NS", "Narrow Co", impact=0.5, conf=0.8),
                 parent_id="fmcg", net_direction="bearish"),
        ]},
        "verify_companies": StageRouterError("verifier down"),
    })
    from app.analysis.impact_graph.engine import analyze_article_v3
    result = analyze_article_v3(router, "t", "c", session=db_session)

    assert result.metrics.get("verification_unavailable") == 1
    assert result.companies[0].verified is False


def test_legacy_persist_writes_no_decision_records(db_session, legacy_mode):
    _company_row(db_session)
    alert = _persist(db_session, _result([_graph_company()]))

    from app.models import AlertCompany
    rows = db_session.query(AlertCompany).filter_by(alert_id=alert.id).all()
    assert len(rows) == 1
    assert rows[0].display_tier is None
    assert db_session.query(CompanyDecisionRecord).count() == 0
