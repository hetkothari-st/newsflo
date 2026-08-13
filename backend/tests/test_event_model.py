"""Task 10 (corrective plan 2026-08-13): structured event_cause + expected
market sensitivity as two DISTINCT new concepts, neither invented when the
model omits them and neither derived from a measured price move."""
import inspect

from app.analysis.impact_graph.engine import analyze_article_v3
from app.analysis.impact_graph.schemas import EventFacts, GraphCompany
from app.models import Article
from app.pipeline import _persist_alert, _v3_entries

from tests.test_impact_graph import FACTS, FakeRouter, _company, _company_entry, _edge


def _persist(db, result, category="commodity"):
    article = Article(source="s", provider="finnhub", url="https://ex.com/a",
                      title="crude spikes", content="c", status="CATEGORIZED")
    db.add(article)
    db.commit()
    entries = _v3_entries(db, result)
    return _persist_alert(
        db, article, category, entries, event_type=result.event_type,
        gaps=[], edges=[], client=None, facts=result.facts,
        analysis_provider=result.analysis_provider, analysis_quality=result.analysis_quality,
        event_cause=result.event_cause,
    )


# --- EventFacts.event_cause parsing / default -----------------------------

def test_event_cause_parsed_when_valid():
    facts = EventFacts(**dict(FACTS, event_cause="policy_action"))
    assert facts.event_cause == "policy_action"


def test_event_cause_defaults_to_unknown_when_omitted():
    facts = EventFacts(**FACTS)  # FACTS carries no event_cause key
    assert facts.event_cause == "unknown"


def test_event_cause_out_of_enum_normalizes_to_unknown():
    """The model must never invent a cause -- an out-of-enum value is
    exactly as honest as an omission."""
    facts = EventFacts(**dict(FACTS, event_cause="totally_made_up_reason"))
    assert facts.event_cause == "unknown"


# --- GraphCompany.expected_market_sensitivity ------------------------------

def test_sensitivity_parsed_when_valid():
    company = GraphCompany(ticker="A.NS", expected_market_sensitivity="HIGH")
    assert company.expected_market_sensitivity == "HIGH"


def test_sensitivity_defaults_to_unknown_when_omitted():
    company = GraphCompany(ticker="A.NS")
    assert company.expected_market_sensitivity == "UNKNOWN"


def test_sensitivity_out_of_enum_normalizes_to_unknown():
    company = GraphCompany(ticker="A.NS", expected_market_sensitivity="SUPER_HIGH")
    assert company.expected_market_sensitivity == "UNKNOWN"


# --- end-to-end: cause + sensitivity flow through the engine ---------------

def test_event_cause_flows_through_engine_result(db_session):
    router = FakeRouter({
        "extract_facts": dict(FACTS, event_cause="geopolitical_event"),
        "initial_shocks": {"shocks": [], "direct_nodes": [
            _edge("event", "oil_gas", child_type="sector", parent_type="event", mat=0.7, conf=0.8),
        ]},
        "ripple_discovery": [{"children": []}],
    })
    result = analyze_article_v3(router, "t", "c", session=db_session)
    assert result.event_cause == "geopolitical_event"


def test_event_cause_absent_from_facts_ships_unknown(db_session):
    router = FakeRouter({
        "extract_facts": FACTS,  # no event_cause key at all
        "initial_shocks": {"shocks": [], "direct_nodes": []},
        "ripple_discovery": [{"children": []}],
    })
    result = analyze_article_v3(router, "t", "c", session=db_session)
    assert result.event_cause == "unknown"


def test_sensitivity_flows_through_engine_and_survives_mapping(db_session):
    _company(db_session, "SENS.NS", "Sensitive Co", "oil_gas")
    entry = _company_entry("SENS.NS", "Sensitive Co")
    entry["expected_market_sensitivity"] = "HIGH"
    router = FakeRouter({
        "extract_facts": FACTS,
        "initial_shocks": {"shocks": [], "direct_nodes": [
            _edge("event", "oil_gas", child_type="sector", parent_type="event", mat=0.7, conf=0.8),
        ]},
        "map_companies": {"companies": [entry]},
        "ripple_discovery": [{"children": []}],
    })
    result = analyze_article_v3(router, "t", "c", session=db_session)
    assert result.companies[0].expected_market_sensitivity == "HIGH"


# --- persistence ------------------------------------------------------------

def test_event_cause_persisted_on_alert(db_session):
    _company(db_session, "CAUSE.NS", "Cause Co", "oil_gas")
    entry = _company_entry("CAUSE.NS", "Cause Co")
    router = FakeRouter({
        "extract_facts": dict(FACTS, event_cause="regulatory_change"),
        "initial_shocks": {"shocks": [], "direct_nodes": [
            _edge("event", "oil_gas", child_type="sector", parent_type="event", mat=0.7, conf=0.8),
        ]},
        "map_companies": {"companies": [entry]},
        "ripple_discovery": [{"children": []}],
    })
    result = analyze_article_v3(router, "t", "c", session=db_session)
    alert = _persist(db_session, result)
    assert alert.event_cause == "regulatory_change"


def test_event_cause_unknown_default_persisted(db_session):
    router = FakeRouter({
        "extract_facts": FACTS,  # no event_cause
        "initial_shocks": {"shocks": [], "direct_nodes": []},
        "ripple_discovery": [{"children": []}],
    })
    result = analyze_article_v3(router, "t", "c", session=db_session)
    alert = _persist(db_session, result)
    assert alert.event_cause == "unknown"


def test_sensitivity_persisted_on_alert_company(db_session):
    _company(db_session, "PSENS.NS", "Persist Sens Co", "oil_gas")
    entry = _company_entry("PSENS.NS", "Persist Sens Co")
    entry["expected_market_sensitivity"] = "MEDIUM"
    router = FakeRouter({
        "extract_facts": FACTS,
        "initial_shocks": {"shocks": [], "direct_nodes": [
            _edge("event", "oil_gas", child_type="sector", parent_type="event", mat=0.7, conf=0.8),
        ]},
        "map_companies": {"companies": [entry]},
        "ripple_discovery": [{"children": []}],
    })
    result = analyze_article_v3(router, "t", "c", session=db_session)
    alert = _persist(db_session, result)
    assert len(alert.companies) == 1
    assert alert.companies[0].expected_market_sensitivity == "MEDIUM"


def test_sensitivity_omitted_persists_unknown(db_session):
    _company(db_session, "USENS.NS", "Unknown Sens Co", "oil_gas")
    entry = _company_entry("USENS.NS", "Unknown Sens Co")  # no sensitivity key
    router = FakeRouter({
        "extract_facts": FACTS,
        "initial_shocks": {"shocks": [], "direct_nodes": [
            _edge("event", "oil_gas", child_type="sector", parent_type="event", mat=0.7, conf=0.8),
        ]},
        "map_companies": {"companies": [entry]},
        "ripple_discovery": [{"children": []}],
    })
    result = analyze_article_v3(router, "t", "c", session=db_session)
    alert = _persist(db_session, result)
    assert alert.companies[0].expected_market_sensitivity == "UNKNOWN"


# --- sensitivity must never be derived from price (grep-style pin) --------

def test_serializer_sets_sensitivity_only_from_graph_company_field():
    """_v3_entries is the ONLY place that turns a GraphCompany into the
    persisted entry dict. Pin its source so the expected_market_sensitivity
    line reads straight from company.expected_market_sensitivity and never
    from a price/return/measurement field -- the market layer's own
    measured reaction (price_at_analysis/return_1m/return_3m/excess_move)
    must stay completely independent of this."""
    source = inspect.getsource(_v3_entries)
    line = next(
        text for text in source.splitlines()
        if '"expected_market_sensitivity"' in text and ':' in text
    )
    assert "company.expected_market_sensitivity" in line
    for forbidden in ("price", "return_1m", "return_3m", "excess_move", "snapshot"):
        assert forbidden not in line


# --- migration (0004) ------------------------------------------------------

def test_migration_0004_adds_event_model_columns(tmp_path):
    import os
    import sqlite3
    import subprocess
    import sys
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    db = tmp_path / "event_model.db"
    url = f"sqlite:///{db}"
    env = dict(os.environ, DATABASE_URL=url)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

    conn = sqlite3.connect(db)
    try:
        alert_columns = {row[1] for row in conn.execute("PRAGMA table_info(alerts)")}
        alert_company_columns = {row[1] for row in conn.execute("PRAGMA table_info(alert_companies)")}
    finally:
        conn.close()
    assert "event_cause" in alert_columns
    assert "expected_market_sensitivity" in alert_company_columns
