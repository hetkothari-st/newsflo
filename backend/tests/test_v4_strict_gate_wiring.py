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
                 verified_node=None):
    row = Company(name=name, ticker=ticker, sector=sector, index_tier="NIFTY50")
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
    assert entries[0]["display_tier"] == "primary"
    assert entries[0]["gate_state"] == "DISPLAY_ELIGIBLE"


def test_strict_unverified_candidate_excluded(db_session, strict_mode):
    _company_row(db_session)
    entries = _v3_entries(db_session, _result([_graph_company(verified=False)]))

    assert entries[0]["display_tier"] == "excluded"
    assert entries[0]["gate_state"] == "REJECT_UNVERIFIED"


def test_strict_budget_exhausted_fails_closed(db_session, strict_mode):
    """INV-005/016: verification never ran -> nothing may display."""
    _company_row(db_session)
    entries = _v3_entries(db_session, _result(
        [_graph_company(verified=False)], quality="budget_exhausted"))

    assert entries[0]["display_tier"] == "excluded"
    assert entries[0]["gate_state"] == "REJECT_VALIDATOR_UNAVAILABLE"


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


def test_strict_verified_relationship_upgrades_evidence(db_session, strict_mode):
    """A fresh CompanyNodeExposure row is Tier-C evidence: d2 primary
    becomes possible (spec §13)."""
    row = _company_row(db_session)
    db_session.add(CompanyNodeExposure(
        company_id=row.id, node_key="crude_price", exposure_exists=1,
        strength=0.8, mechanism="verified crude exposure", verified_at=utcnow()))
    db_session.commit()

    d2 = _graph_company(causal_distance=2, materiality=0.7)
    edges = [_graph_edge(),
             _graph_edge(parent_type="economic_node", parent_id="crude_price",
                         child_type="sector", child_id="oil_gas", causal_distance=2)]
    entries = _v3_entries(db_session, _result([d2], edges=edges))

    assert entries[0]["evidence_class"] == "VERIFIED_RELATIONSHIP"
    assert entries[0]["display_tier"] == "primary"


def test_strict_model_inference_d2_is_secondary(db_session, strict_mode):
    d2 = _graph_company(causal_distance=2, materiality=0.7)
    _company_row(db_session)
    entries = _v3_entries(db_session, _result([d2]))

    assert entries[0]["evidence_class"] == "MODEL_INFERENCE"
    assert entries[0]["display_tier"] == "secondary"


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
    _company_row(db_session, ticker="WEAKCO.NS", name="WeakCo", sector="oil_gas")
    result = _result([
        _graph_company(),                                              # primary
        _graph_company(ticker="WEAKCO.NS", name="WeakCo", verified=False),  # excluded
    ])
    alert = _persist(db_session, result)

    from app.models import AlertCompany
    rows = db_session.query(AlertCompany).filter_by(alert_id=alert.id).all()
    assert [r.display_tier for r in rows] == ["primary"]

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
