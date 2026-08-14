"""BYPASS PINS (corrective-v4 Task 20): one test per bypass the 2026-08-13
audit found, each named for the bypass it closes.

A bypass is a path by which unvalidated, price-derived, self-certified or
stale data could reach the reader WITHOUT walking the publication gate.
Each test here reconstructs that path and asserts it is closed. These are
regression pins, not coverage: if one starts failing, a specific,
previously-audited hole has reopened -- read the test's docstring for what
the hole was before "fixing" the test.

Naming is deliberate and load-bearing: `test_bypass_<name>` maps 1:1 to the
audit's bypass list, so `-k bypass` runs exactly the closed-hole suite.
"""
import inspect
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.analysis.impact_graph.publication_gate import (
    CandidateInput, GateContext, evaluate_candidate,
)
from app.config import settings
from app.models import (
    Alert, AlertCompany, AlertRippleLayer, Article, Company, CompanyDecisionRecord,
    CompanyNodeExposure, EvidenceRecord, MarketMove, SupplyLink, utcnow,
)

APP_DIR = Path(__file__).resolve().parents[1] / "app"


@pytest.fixture()
def strict_mode(monkeypatch):
    monkeypatch.setattr(settings, "impact_engine_v4_strict", True)


@pytest.fixture()
def legacy_mode(monkeypatch):
    monkeypatch.setattr(settings, "impact_engine_v4_strict", False)


_seq = [0]


def _next() -> int:
    _seq[0] += 1
    return _seq[0]


def _company_row(db, ticker="ONGC.NS", name="ONGC", sector="oil_gas",
                 business_desc="Upstream oil and gas explorer", verified_node=None,
                 provenance_type="MODEL_VERIFIED"):
    row = Company(name=name, ticker=ticker, sector=sector, index_tier="NIFTY50",
                  market="INDIA", tradeability="NORMAL", market_cap=1e12,
                  business_desc=business_desc)
    db.add(row)
    db.commit()
    if verified_node is not None:
        db.add(CompanyNodeExposure(
            company_id=row.id, node_key=verified_node, exposure_exists=1, strength=0.8,
            mechanism="verified exposure", provenance_type=provenance_type,
            verified_at=utcnow()))
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
        impact_strength=0.8, confidence=0.9, materiality=0.7, time_horizon="Short-Term",
    )
    payload.update(overrides)
    return GraphEdge(**payload)


def _result(companies, edges=None, quality="authoritative", named_entities=None):
    from app.analysis.impact_graph.schemas import ImpactGraphResult
    return ImpactGraphResult(
        category="commodity", event_type="crude_oil", facts="crude up 5%",
        event_label="crude supply shock", named_entities=named_entities or [],
        companies=companies,
        edges=edges if edges is not None else [_graph_edge()], gaps=[], ranking=[],
        analysis_provider="gemini", analysis_quality=quality, metrics={},
    )


def _article(db, title="crude spikes", status="CATEGORIZED"):
    article = Article(source="s", provider="finnhub", url=f"https://ex.com/bp-{_next()}",
                      title=title, content="c", status=status)
    db.add(article)
    db.commit()
    return article


def _persist(db, result, article=None, **kwargs):
    from app.pipeline import _persist_alert, _v3_edges, _v3_entries

    article = article if article is not None else _article(db)
    entries = _v3_entries(db, result)
    return _persist_alert(
        db, article, "commodity", entries, event_type="crude_oil", gaps=[],
        edges=_v3_edges(result), client=None, facts="crude up 5%",
        analysis_provider=result.analysis_provider,
        analysis_quality=result.analysis_quality, **kwargs)


def _seed_alert(db):
    article = _article(db, status="ALERTED")
    alert = Alert(article_id=article.id, category="commodity", event_type="crude_oil")
    db.add(alert)
    db.commit()
    return alert


def _add_alert_company(db, alert, ticker, name, sector="oil_gas", *, direction="bullish",
                       economic_effect="positive", display_tier="primary",
                       gate_state="DISPLAY_ELIGIBLE", causal_parent_id="crude_price",
                       materiality=0.7, excess=None, mechanism="crude-linked input costs"):
    company = Company(name=name, ticker=ticker, sector=sector, index_tier="NIFTY50")
    db.add(company)
    db.commit()
    alert_company = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction=direction,
        magnitude_low=1.0, magnitude_high=3.0, rationale="thesis", basis="direct_mention",
        economic_effect=economic_effect, display_tier=display_tier, gate_state=gate_state,
        causal_parent_type="economic_node", causal_parent_id=causal_parent_id,
        materiality=materiality, causal_distance=1, mechanism=mechanism,
    )
    db.add(alert_company)
    db.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^NSEI",
        measurement_status="ok" if excess is not None else "no_data",
        excess_move_pct=excess, raw_move_pct=excess, sector_move_pct=0.0,
        measured_at=utcnow(), category="commodity", bar_complete=1))
    db.commit()
    return company, alert_company


# ===========================================================================
# BYPASS: title-dedup reuse copied an ungated/stale analysis onto a new alert
# ===========================================================================

def test_bypass_dedup_reuse(db_session, monkeypatch, strict_mode):
    """BYPASS (Task 12): the title-dedup shortcut copied a prior alert's
    AlertCompany rows verbatim. A LEGACY prior's field-less rows became a
    new alert's rows with gate_state NULL -- gate output the gate never
    produced -- and a prior decided under an OLD gate contract replayed
    forever. Three legs, one per refusal condition, plus the accepted case:

    1. prior alert is ungated            -> no reuse (fresh analysis)
    2. prior alert's audit trail is from a stale analysis_version
                                         -> no reuse
    3. prior alert is gated, current-version, authoritative
                                         -> reuse, and the audit trail is
                                            COPIED (never re-synthesized:
                                            the gate walked once)
    """
    import app.pipeline as pipeline_module
    from app.pipeline import _find_reusable_alert

    # --- leg 1: ungated prior --------------------------------------------
    legacy_article = _article(db_session, title="Crude oil surges on Gulf tension",
                              status="ANALYZED")
    legacy_alert = Alert(article_id=legacy_article.id, category="commodity",
                         analysis_quality="authoritative")
    db_session.add(legacy_alert)
    db_session.commit()
    legacy_company = _company_row(db_session, ticker="LEGACY.NS", name="Legacy Co")
    db_session.add(AlertCompany(
        alert_id=legacy_alert.id, company_id=legacy_company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
        display_tier=None, gate_state=None))
    db_session.commit()

    duplicate = _article(db_session, title="Crude oil surges on Gulf tension")
    assert _find_reusable_alert(db_session, duplicate) is None, "ungated prior must not be reused"

    # --- legs 2 and 3: a REAL gated prior ---------------------------------
    _company_row(db_session, verified_node="crude_price")
    prior_article = _article(db_session, title="Crude oil spikes on supply shock")
    prior_alert = _persist(db_session, _result([_graph_company()]), article=prior_article)
    prior_article.status = "ANALYZED"
    db_session.commit()

    assert db_session.query(AlertCompany).filter_by(alert_id=prior_alert.id).count() == 1
    prior_records = db_session.query(CompanyDecisionRecord).filter_by(
        alert_id=prior_alert.id).all()
    assert prior_records and all(r.gates_passed_json for r in prior_records)

    # leg 2: the gate contract has since moved on.
    for record in prior_records:
        record.analysis_version = "ancient-1/ancient-1"
    db_session.commit()
    stale_duplicate = _article(db_session, title="Crude oil spikes on supply shock")
    assert _find_reusable_alert(db_session, stale_duplicate) is None, (
        "a decision made under a superseded gate contract must not be replayed")
    db_session.delete(stale_duplicate)
    db_session.commit()

    # leg 3: current version -> reuse, with the audit trail copied.
    # The version string is the FULL 4-part contract (final-review finding
    # I4: prompt/schema/gate-policy/knowledge-registry), not prompt+schema
    # -- a POLICY_VERSION or KNOWLEDGE_REGISTRY_VERSION bump changes what
    # the gate decides and must invalidate the reuse shortcut too.
    from app.pipeline import analysis_version

    current_version = analysis_version()
    assert len(current_version.split("/")) == 4
    for record in prior_records:
        record.analysis_version = current_version
    db_session.commit()

    fresh_duplicate = _article(db_session, title="Crude oil spikes on supply shock")
    assert _find_reusable_alert(db_session, fresh_duplicate) is not None

    # process_new_articles sweeps EVERY categorized article; park the other
    # fixtures so this run is exactly the reuse path under test.
    for other in db_session.query(Article).filter(
            Article.status == "CATEGORIZED", Article.id != fresh_duplicate.id).all():
        other.status = "REJECTED"
    db_session.commit()

    calls = {"n": 0}

    def _never(*args, **kwargs):
        calls["n"] += 1
        raise AssertionError("reuse must not spend an analysis call")

    monkeypatch.setattr(pipeline_module, "analyze_article_v3", _never)
    created = pipeline_module.process_new_articles(db_session, claude_client=None)

    assert created >= 1
    assert calls["n"] == 0
    reused_alert = db_session.query(Alert).filter_by(article_id=fresh_duplicate.id).one()
    reused_rows = db_session.query(AlertCompany).filter_by(alert_id=reused_alert.id).all()
    # The copied row carries the ORIGINAL gate decision -- never NULL, which
    # would make it indistinguishable from a legacy ungated row.
    assert [r.gate_state for r in reused_rows] == ["DISPLAY_ELIGIBLE"]
    assert all(r.display_tier is not None for r in reused_rows)

    copied = db_session.query(CompanyDecisionRecord).filter_by(alert_id=reused_alert.id).all()
    assert len(copied) == len(prior_records)
    # PRESERVED, not restamped: the record describes the gate run that
    # actually produced it, against the prior article.
    assert {r.analysis_version for r in copied} == {current_version}
    assert {r.final_state for r in copied} == {r.final_state for r in prior_records}


# ===========================================================================
# BYPASS: the narrow path's in-call self-check standing in for verification
# ===========================================================================

def test_bypass_narrow_budget(db_session, strict_mode):
    """BYPASS (Task 9): the narrow single-call path marks its own companies
    `verified=True` as an IN-CALL self-check. When the budget ran out
    before independent verification, that self-assessment was the only
    "verification" left -- and it authorized display. Two halves:

    (a) engine: an exhausted budget skips the verifier and says so, marking
        the run budget_exhausted rather than shipping it as normal output;
    (b) gate: a company still carrying verified=True in such a run is
        REJECT_VALIDATOR_UNAVAILABLE -- the flag is an upstream default,
        not a verdict, and availability is checked first."""
    from app.analysis.impact_graph.engine import analyze_article_v3
    from app.pipeline import _v3_entries
    from tests.test_impact_graph import FACTS, FakeRouter, _edge

    _company_row(db_session, ticker="NARROW.NS", name="Narrow Co", sector="fmcg",
                 business_desc="Single-category packaged foods manufacturer",
                 verified_node="fmcg")
    router = FakeRouter({
        "extract_facts": dict(FACTS, event_type="earnings", category="fmcg"),
        "narrow_graph": {
            "shocks": [{"shock_id": "demand_hit", "label": "Demand hit", "direction": "bearish",
                        "mechanism": "input cost shock", "confidence": 0.85,
                        "materiality": 0.8, "impact_strength": 0.8}],
            "edges": [_edge("demand_hit", "fmcg", child_type="sector", mat=0.8, conf=0.85)],
        },
        "narrow_companies": {"companies": [{
            "ticker": "NARROW.NS", "name": "Narrow Co", "direction": "bearish",
            "impact_strength": 0.7, "confidence": 0.8, "materiality": 0.8,
            "time_horizon": "Short-Term", "parent_id": "fmcg",
            "mechanism": "input cost inflation compresses this company's gross margin",
            "rationale": "single-category manufacturer with no hedging",
            "net_direction": "bearish"}]},
        "verify_companies": {"accept": ["NARROW.NS"], "reject": [],
                             "counterfactual": {"NARROW.NS": "SUPPORTED"}},
    })
    # Blow the per-article token ceiling before the run reaches verification.
    router.budget.input_tokens = 10 ** 9

    result = analyze_article_v3(router, "t", "c", session=db_session)

    assert "verify_companies" not in router.calls, "no budget left, yet the verifier ran?"
    assert result.analysis_quality == "budget_exhausted"
    assert all(c.verified is False for c in result.companies)

    # (b) the fail-open shape itself: verified=True surviving into a
    # budget_exhausted result must still reject.
    self_certified = _result(
        [_graph_company(ticker="NARROW.NS", name="Narrow Co", parent_id="fmcg",
                        verified=True)],
        edges=[_graph_edge(child_id="fmcg")],   # roots in the event: not THAT gate's problem
        quality="budget_exhausted")
    entries = _v3_entries(db_session, self_certified)

    assert entries[0]["gate_state"] == "REJECT_VALIDATOR_UNAVAILABLE"
    assert entries[0]["display_tier"] == "excluded"
    assert entries[0]["gate_inputs"]["independently_verified"] is True
    assert entries[0]["gate_inputs"]["verification_available"] is False


# ===========================================================================
# BYPASS: the exposure cache certifying itself
# ===========================================================================

def test_bypass_self_certifying_cache(db_session, strict_mode):
    """BYPASS (Task 6): one LLM acceptance wrote a CompanyNodeExposure row
    that then (a) read back as VERIFIED_RELATIONSHIP evidence and (b)
    auto-accepted the same candidate on every later event without ever
    facing verification again. Prior acceptance certified itself forever.

    A MODEL_VERIFIED row is a PRIOR: Tier D at best, and the verifier runs
    regardless -- its rejection stands even when the cache says yes."""
    from app.analysis.impact_graph.engine import analyze_article_v3
    from app.analysis.impact_graph.evidence import classify_evidence
    from app.pipeline import _v3_entries

    row = _company_row(db_session, verified_node="crude_price",
                       provenance_type="MODEL_VERIFIED")

    evidence_class, evidence_tier, payloads = classify_evidence(
        db_session, _graph_company(), set())
    assert (evidence_class, evidence_tier) == ("MODEL_VERIFIED_PRIOR", "D")
    assert payloads == [], "a self-written cache row cites no artifact -- it IS none"

    # ...and Tier D can never authorize a primary claim, however high the
    # model's own materiality float.
    entries = _v3_entries(db_session, _result([_graph_company(materiality=0.95)]))
    assert entries[0]["display_tier"] == "secondary_ripple"

    # A candidate this event's verifier did NOT accept stays rejected --
    # the cached row cannot stand in for the missing verdict.
    unverified = _v3_entries(db_session, _result([_graph_company(verified=False)]))
    assert unverified[0]["gate_state"] == "REJECT_UNVERIFIED"

    # Engine level: the verifier is CALLED even with a positive cache row,
    # and its rejection is honored.
    from tests.test_impact_graph import FakeRouter, _company_entry
    from tests.test_impact_graph_optimization import _direct_sector_setup

    cached = _company_row(db_session, ticker="CACHED.NS", name="Cached Co", sector="oil_gas")
    db_session.add(CompanyNodeExposure(
        company_id=cached.id, node_key="oil_gas", exposure_exists=1, strength=0.7,
        mechanism="crude input exposure", provenance_type="MODEL_VERIFIED",
        verified_at=utcnow()))
    db_session.commit()

    router = FakeRouter(_direct_sector_setup({
        "map_companies": {"companies": [_company_entry("CACHED.NS", "Cached Co")]},
        "verify_companies": {"accept": [], "reject": [
            {"ticker": "CACHED.NS", "reason": "not material for this specific event"}]},
    }))
    result = analyze_article_v3(router, "t", "c", session=db_session)

    assert "verify_companies" in router.calls
    assert result.companies == []
    assert row.id  # (fixture kept alive for the reader: two distinct companies)


# ===========================================================================
# BYPASS: price data leaking into confidence / persistence
# ===========================================================================

def test_bypass_price_confidence_floor(db_session, monkeypatch, strict_mode):
    """BYPASS (Task 3): the observed price move reached the fundamental
    confidence score (via a reasoning/price contradiction flag and
    calibration hit-rate), and CONFIDENCE_FLOOR then deleted gated rows on
    the strength of it -- a second, price-tainted persistence authority
    sitting on top of the publication gate.

    Now: the confidence engine takes no price input at all, and the floor
    does not apply to a gated entry (the gate is its sole authority). The
    floor still guards LEGACY, ungated entries -- asserted as the control,
    so "the floor is gone" can never pass as "the floor is bypassed"."""
    from app.reasoning import confidence as confidence_module
    from app.reasoning.confidence import ConfidenceResult
    import app.pipeline as pipeline_module
    from app.pipeline import CONFIDENCE_FLOOR

    signature = inspect.signature(confidence_module.compute_confidence)
    assert set(signature.parameters) == {
        "claim_count", "evidence_ref_count", "rule_matched",
        "source_credibility", "article_age_hours"}
    source = inspect.getsource(confidence_module)
    for banned in ("return_1m", "excess_move", "calibration_hit_rate", "price"):
        assert banned not in source, banned

    _company_row(db_session, verified_node="crude_price")
    monkeypatch.setattr(pipeline_module, "compute_confidence",
                        lambda **kwargs: ConfidenceResult(score=0, band="LOW"))

    alert = _persist(db_session, _result([_graph_company()]))
    rows = db_session.query(AlertCompany).filter_by(alert_id=alert.id).all()

    assert len(rows) == 1, "the gate ruled this row in; the floor must not veto it"
    assert rows[0].gate_state == "DISPLAY_ELIGIBLE"
    assert rows[0].confidence_score < CONFIDENCE_FLOOR

    # Control: a LEGACY (ungated) entry has no gate decision behind it, so
    # the floor is still its only persistence check.
    from app.pipeline import _persist_alert

    legacy_company = _company_row(db_session, ticker="LEGACY.NS", name="Legacy Co")
    legacy_alert = _persist_alert(db_session, _article(db_session), "commodity", [{
        "company_id": legacy_company.id, "direction": "bullish", "magnitude_low": 1.0,
        "magnitude_high": 2.0, "rationale": "r", "key_points": [], "basis": "direct_mention",
        "time_horizon": "Short-Term", "impact_level": "direct"}])
    assert db_session.query(AlertCompany).filter_by(alert_id=legacy_alert.id).count() == 0


def test_bypass_price_calibration(db_session):
    """BYPASS (Task 3): realized-outcome CalibrationSample stats overrode
    the persisted magnitude range, so how a company's stock happened to
    move after PAST, unrelated articles silently rewrote THIS article's
    stated range. Magnitude is now deterministic in impact_strength, and
    the blender is not called from the persistence path at all."""
    from app.models import CalibrationSample
    from app.pipeline import _persist_alert

    company = _company_row(db_session, ticker="CALIB.NS", name="Calib Co")
    # Five constant samples: comfortably past the old blend threshold, and
    # constant so any accidental blending is unmistakable (10.0, 10.0).
    for i in range(5):
        db_session.add(CalibrationSample(
            alert_company_id=i + 1, category="commodity", company_id=company.id,
            direction="bullish", magnitude_actual=10.0, horizon_days=1))
    db_session.commit()

    impact_strength = 0.6
    magnitude_high = round(0.5 + 4.5 * impact_strength, 1)
    magnitude_low = round(max(0.1, magnitude_high / 3), 1)
    alert = _persist_alert(db_session, _article(db_session), "commodity", [{
        "company_id": company.id, "direction": "bullish",
        "magnitude_low": magnitude_low, "magnitude_high": magnitude_high,
        "rationale": "r", "key_points": [], "basis": "direct_mention",
        "time_horizon": "Short-Term", "impact_level": "direct",
        "impact_strength": impact_strength,
        "reasons": ["one"], "evidence_refs": ["RULE_CRUDE_OIL_UP"]}])

    row = db_session.query(AlertCompany).filter_by(alert_id=alert.id).one()
    assert (row.magnitude_low, row.magnitude_high) == (magnitude_low, magnitude_high)
    assert row.magnitude_high != 10.0

    # Structural: the persistence path cannot reach the blender at all.
    pipeline_source = (APP_DIR / "pipeline.py").read_text(encoding="utf-8")
    assert "get_calibrated_magnitude(" not in pipeline_source


# ===========================================================================
# BYPASS: the legacy section generator resurrecting for gated data
# ===========================================================================

def test_bypass_legacy_section_resurrection(db_session, legacy_mode):
    """BYPASS (Task 12): section rendering dispatched on
    settings.impact_engine_v4_strict, so turning the flag OFF resurrected
    the legacy LLM-authored section path for alerts whose rows were
    already gate-validated -- ungated storytelling over gated data.

    Reachability is now STRUCTURAL (it reads the row's own gate fields), so
    a persisted AlertRippleLayer stays unreachable with the flag off."""
    from app.market.ripple_layers import compute_ripple_layers

    assert settings.impact_engine_v4_strict is False  # the flag is genuinely off

    alert = _seed_alert(db_session)
    _add_alert_company(db_session, alert, "ONGC.NS", "ONGC", excess=1.0)
    db_session.add(AlertRippleLayer(
        alert_id=alert.id, position=0, title="Winners — upstream", relationship="DIRECT",
        note="n", tickers_json=json.dumps(["ONGC.NS"])))
    db_session.commit()

    layers = compute_ripple_layers(db_session, alert, set())

    assert "Winners — upstream" not in [layer["title"] for layer in layers]
    assert any(layer["relationship"].startswith("MECH:") for layer in layers)


# ===========================================================================
# BYPASS: the headline picking whichever company moved most
# ===========================================================================

def test_bypass_headline_ignores_tier(db_session, strict_mode):
    """BYPASS (Task 16): the feed's headline/peak calculation ranked by
    measured move alone, so a SECONDARY_DEEP_DIVE company with a big price
    move headlined an alert -- a company the gate deliberately refused to
    make a primary claim about, presented as the story."""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.routers.articles import get_db

    alert = _seed_alert(db_session)
    _add_alert_company(db_session, alert, "ONGC.NS", "ONGC", display_tier="primary",
                       economic_effect="positive", excess=1.0)
    _add_alert_company(db_session, alert, "BLUEDART.NS", "Blue Dart", "railways_transport",
                       display_tier="secondary_deep_dive", economic_effect="negative",
                       direction="bearish", materiality=0.3, excess=-9.0)

    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app)
        row = client.get("/api/feed-v2").json()[0]
        assert row["peak_ticker"] == "ONGC.NS"      # not the -9.0% secondary
        assert row["excess_move_pct"] == 1.0

        detail = client.get(f"/api/feed-v2/{alert.id}").json()
        assert detail["peak_ticker"] == "ONGC.NS"
        card_tickers = [r["ticker"] for layer in detail["layers"] for r in layer["rows"]]
        assert card_tickers == ["ONGC.NS"]

        deep_dive = client.get(f"/api/feed-v2/{alert.id}/deep-dive").json()
        secondary = [r["ticker"] for layer in deep_dive["secondary"] for r in layer["rows"]]
        assert secondary == ["BLUEDART.NS"]         # visible, but only here
    finally:
        app.dependency_overrides.clear()


# ===========================================================================
# BYPASS: an LLM (or any non-gate module) writing display_tier
# ===========================================================================

def test_bypass_llm_writes_display_tier(db_session, strict_mode):
    """BYPASS: display_tier is the gate's verdict. If any other module (or
    an LLM response schema) could produce one, the gate stops being the
    single authority over what the reader sees as a primary claim.

    Three pins, all structural:
    1. no prompt or response schema mentions display_tier / primary tiers,
       so a model cannot even propose one;
    2. no module outside publication_gate.py assigns a DISPLAYABLE tier
       literal ("primary" / "secondary_ripple" / "macro_context", plus the
       legacy "secondary_deep_dive" spelling) to display_tier --
       everything else COPIES a decision (the one allowed literal is
       "excluded" on an explicit rejection record, which is a refusal to
       display, not a claim);
    3. behaviorally, the tier on a persisted row equals the tier the gate
       decided for that same candidate."""
    from app.analysis.impact_graph import prompts, schemas

    for module in (prompts, schemas):
        source = inspect.getsource(module)
        assert "display_tier" not in source, module.__name__
        assert "secondary_deep_dive" not in source, module.__name__

    offenders = []
    for path in APP_DIR.rglob("*.py"):
        if path.name == "publication_gate.py":
            continue
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#") or "display_tier" not in stripped:
                continue
            if any(f'display_tier{sep}"{tier}"' in stripped.replace(" ", "")
                   for sep in ("=", "==")
                   for tier in ("primary", "secondary_ripple", "macro_context",
                                "secondary_deep_dive")):
                # `== "primary"` is a READ (routers filtering the feed);
                # only an assignment claims authorship.
                if "==" in stripped.replace(" ", "").split("display_tier")[1][:2]:
                    continue
                offenders.append(f"{path.relative_to(APP_DIR)}:{line_number}: {stripped}")
    assert offenders == [], offenders

    from app.analysis.impact_graph.evidence import classify_evidence
    from app.pipeline import _v3_entries

    parent = _company_row(db_session, ticker="MARUTI.NS", name="Maruti Suzuki", sector="auto")
    supplier = _company_row(db_session, ticker="MOTHERSON.NS", name="Samvardhana Motherson",
                            sector="auto_components",
                            business_desc="Wiring harness and auto components supplier")
    db_session.add(SupplyLink(
        company_id=parent.id, counterparty_company_id=supplier.id,
        counterparty_name="Samvardhana Motherson", relation="SUPPLIER",
        evidence="Samvardhana Motherson supplies wiring harnesses for our vehicle programmes",
        source_url="https://crisil.example/rationale", source_agency="CRISIL",
        as_of=date.today()))
    db_session.commit()

    d2 = _graph_company(
        ticker="MOTHERSON.NS", name="Samvardhana Motherson", causal_distance=2,
        materiality=0.8, parent_type="company", parent_id="MARUTI.NS",
        mechanism="volume cut at Maruti reduces component offtake",
        rationale="tier-1 supplier to the affected OEM")
    result = _result([d2], edges=[_graph_edge(child_type="company", child_id="MARUTI.NS")])
    entries = _v3_entries(db_session, result)
    alert = _persist(db_session, result)

    evidence_class, evidence_tier, _payloads = classify_evidence(db_session, d2, set())
    gate_decision = evaluate_candidate(CandidateInput(
        **json.loads(json.dumps(entries[0]["gate_inputs"]))), GateContext())
    row = db_session.query(AlertCompany).filter_by(alert_id=alert.id).one()

    assert evidence_tier == "C" and evidence_class == "VERIFIED_RELATIONSHIP"
    assert row.display_tier == gate_decision.display_tier == "primary"


# ===========================================================================
# BYPASS: a paraphrased market observation reading as fundamental evidence
# ===========================================================================

@pytest.mark.parametrize("rationale", [
    "the scrip slid 3% after the announcement",
    "the scrip fell sharply on the news",
    "the scrip rose on heavy volumes",
    "its price fell hard through the session",
    "its price rose through the afternoon",
    "the counter sold off through the afternoon",
    "the stock slid on the update",
    "shares slid after the print",
    "the stock is down since the announcement",
    "the stock is up since the announcement",
    "the name tanked after the downgrade",
    "the counter plunged after the release",
    "the counter rallied after the release",
    "the stock surged after the release",
    "the counter cracked after the release",
    "shares tumbled on the news",
])
def test_bypass_market_observation_paraphrase(db_session, strict_mode, rationale):
    """BYPASS (INV-003): the market-observation detector matched a fixed
    phrase list ("stock fell", "shares rose", ...), so the SAME argument in
    Indian-market vernacular -- "the scrip slid 3%" -- sailed past it and
    was classified as ordinary fundamental evidence. A price move is a
    price move however it is phrased.

    Precision-first, deliberately: this list over-flags. A genuine
    fundamental mechanism has no reason to say "the counter rallied" -- if
    a real one ever does, it is downgraded to a deep dive, which is the
    cheap direction of the error. Phrase matching is lowercase substring,
    so "rallied"/"tanked" also catch their compound forms."""
    from app.analysis.impact_graph.evidence import classify_evidence
    from app.pipeline import _v3_entries

    _company_row(db_session)
    company = _graph_company(rationale=rationale)

    evidence_class, evidence_tier, payloads = classify_evidence(db_session, company, set())
    assert (evidence_class, evidence_tier) == ("ARTICLE_MARKET_OBSERVATION", "MARKET_OBS")
    assert payloads == []

    entries = _v3_entries(db_session, _result([company]))
    assert entries[0]["gate_state"] == "REJECT_INSUFFICIENT_EVIDENCE"
    assert entries[0]["display_tier"] == "excluded"


def test_bypass_market_observation_paraphrase_keeps_real_mechanisms(db_session, strict_mode):
    """The other side of the phrase list: it must not swallow genuine
    fundamental language. A rationale about costs, margins or demand is
    still ordinary evidence -- this is what stops the pin above from being
    "reject everything"."""
    from app.analysis.impact_graph.evidence import classify_evidence

    _company_row(db_session, verified_node="crude_price")
    for rationale in (
        "crude-linked input costs squeeze this company's margins",
        "regulated marketing margins compress when crude rises",
        "unhedged upstream producer with crude-linked realization",
        "the company's fuel bill rises with aviation turbine fuel prices",
    ):
        evidence_class, _tier, _payloads = classify_evidence(
            db_session, _graph_company(rationale=rationale), set())
        assert evidence_class != "ARTICLE_MARKET_OBSERVATION", rationale


# ===========================================================================
# BYPASS: the subject fallback fabricating a directional, measured-sounding call
# ===========================================================================

def test_bypass_subject_fallback_fabrication(db_session, monkeypatch):
    """BYPASS (engine subject fallback): when the mapping call named
    nobody, the engine persisted the article's subject company with a
    HARDCODED "bearish" direction and a rationale claiming the direction
    "reflects the measured market reaction" -- a fabricated directional
    call, dressed as measurement, from a stage that measured nothing. It
    also skipped .clamp(), so its scores never faced the schema's own
    normalization.

    The fallback stays (an invisible zero-company alert on a single-stock
    story is its own failure), but it now says only what it knows: this
    company is the named subject, no verified mechanism was established.
    Uncertain, unverified, clamped -- and therefore never primary.

    The construction is probed with the strict flag OFF so this run's
    risk-based escalation never fires: what is asserted below is what the
    FALLBACK ITSELF wrote, not a later verifier's verdict laid on top."""
    from app.analysis.impact_graph.budget import ArticleBudget
    from app.analysis.impact_graph.engine import _GraphState, _narrow_single_call
    from app.analysis.impact_graph.schemas import EventFacts
    from app.pipeline import _v3_entries
    from tests.test_impact_graph import FakeRouter

    monkeypatch.setattr(settings, "impact_engine_v4_strict", False)
    _company_row(db_session, ticker="LONER.NS", name="Loner Co", sector="fmcg",
                 business_desc="Single-brand packaged foods company")
    facts = EventFacts(event="Loner Co downgraded", event_status="confirmed",
                       facts="rating cut", category="fmcg", event_type="earnings",
                       named_entities=["Loner Co"])
    router = FakeRouter({
        "narrow_graph": {
            "shocks": [{"shock_id": "rating_cut", "label": "Rating cut", "direction": "bearish",
                        "mechanism": "a rating downgrade raises the cost of funding",
                        "confidence": 0.8, "materiality": 0.6, "impact_strength": 0.5}],
            "edges": [],
        },
        "narrow_companies": {"companies": []},   # the mapping call named nobody
    })
    state = _GraphState()
    _narrow_single_call(router, db_session, facts, state, ArticleBudget(), None)

    assert "verify_companies" not in router.calls, (
        "fixture guard: this leg must observe the fallback's own output")

    assert "LONER.NS" in state.companies, "a single-stock story must not ship zero companies"
    company = state.companies["LONER.NS"]

    assert company.discovery_source == "subject_fallback"
    assert company.verified is False
    # No fabricated direction: uncertain is the honest verdict, and the
    # legacy market-facing view follows it rather than a hardcoded bearish.
    assert company.net_direction == "uncertain"
    assert company.economic_effect == "uncertain"
    assert company.direction == "neutral"
    # No false claim of a measured basis.
    assert "measured" not in company.rationale.lower()
    assert "market reaction" not in company.rationale.lower()
    assert company.rationale == (
        "Named subject of this article; no verified causal mechanism established.")
    # clamp() ran: every score is inside [0, 1] and the effect is reconciled.
    assert 0.0 <= company.impact_strength <= 1.0
    assert 0.0 <= company.confidence <= 1.0
    assert 0.0 <= (company.materiality or 0.0) <= 1.0

    # ...and it cannot become a primary claim at the gate. The verifier
    # never reached it (counterfactual ""), which fails closed.
    monkeypatch.setattr(settings, "impact_engine_v4_strict", True)
    entries = _v3_entries(db_session, _result(
        [company], edges=state.edges, named_entities=["Loner Co"]))

    # ARTICLE_SUBJECT is the strongest evidence this candidate can possibly
    # have (the article named it) -- so this is the BEST case for the
    # fallback, and even it cannot display: the verifier never reached the
    # company, and an unanswered counterfactual fails closed.
    assert entries[0]["evidence_class"] == "ARTICLE_SUBJECT"
    assert entries[0]["display_tier"] != "primary"
    assert entries[0]["display_tier"] == "excluded"
    assert entries[0]["gate_state"] == "REJECT_VALIDATOR_UNAVAILABLE"
