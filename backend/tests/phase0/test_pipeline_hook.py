"""TASK 0.1/0.2 wiring -- the one additive hook in app/pipeline.py.

Controller adaptation (binding): the existing `alert_companies` serving path
stays byte-untouched. `company_impact` is a PARALLEL canonical record
written ONLY by the reducer persistence module, from a post-analysis hook
that must be FAILURE-ISOLATED: its exception can never break the existing
persist path.
"""
import pytest
from sqlalchemy import text

from app.config import settings
from app.models import Alert, AlertCompany, Article, Company, CompanyNodeExposure, utcnow
from app.pipeline import _persist_alert, _v3_entries


@pytest.fixture()
def strict_mode(monkeypatch):
    monkeypatch.setattr(settings, "impact_engine_v4_strict", True)


def _company(db, ticker="ONGC.NS"):
    row = Company(name="ONGC", ticker=ticker, sector="oil_gas",
                  index_tier="NIFTY50", business_desc="Upstream oil and gas explorer")
    db.add(row)
    db.commit()
    db.add(CompanyNodeExposure(
        company_id=row.id, node_key="crude_price", exposure_exists=1,
        strength=0.8, mechanism="verified exposure", verified_at=utcnow()))
    db.commit()
    return row


def _result():
    from app.analysis.impact_graph.schemas import GraphCompany, GraphEdge, ImpactGraphResult

    company = GraphCompany(
        ticker="ONGC.NS", name="ONGC", direction="bullish", impact_strength=0.7,
        confidence=0.8, materiality=0.7, causal_distance=1,
        time_horizon="Short-Term", parent_type="economic_node",
        parent_id="crude_price",
        mechanism="upstream crude realization: higher price lifts revenue per barrel",
        rationale="unhedged upstream producer with crude-linked realization",
        net_direction="bullish", economic_effect="positive", verified=True,
        counterfactual="SUPPORTED")
    edge = GraphEdge(
        parent_type="event", parent_id="crude_supply_shock",
        child_type="economic_node", child_id="crude_price", direction="bullish",
        economic_effect="positive", mechanism="supply disruption raises crude price",
        causal_distance=1, impact_strength=0.8, confidence=0.9, materiality=0.7,
        time_horizon="Short-Term")
    return ImpactGraphResult(
        category="commodity", event_type="crude_oil", facts="crude up",
        event_label="crude supply shock", named_entities=[], companies=[company],
        edges=[edge], gaps=[], ranking=[], analysis_provider="claude",
        analysis_quality="authoritative", metrics={}, ambiguous_entities=[])


def _persist(db):
    article = Article(source="s", provider="finnhub", url="https://ex.com/hook",
                      title="crude spikes", content="c", status="CATEGORIZED")
    db.add(article)
    db.commit()
    result = _result()
    return _persist_alert(
        db, article, "commodity", _v3_entries(db, result), event_type="crude_oil",
        gaps=[], edges=[], client=None, facts="crude up",
        analysis_provider="claude", analysis_quality="authoritative")


def test_the_hook_writes_a_canonical_company_impact_row(db_session, strict_mode):
    _company(db_session)
    alert = _persist(db_session)

    rows = db_session.execute(text(
        "SELECT event_id, company_id, publication_tier, directness, "
        "graph_distance, discovery_source, reducer_version "
        "FROM company_impact")).all()
    assert len(rows) == 1, "the post-analysis hook wrote no canonical record"
    assert rows[0][0] == f"article:{alert.article_id}"
    assert rows[0][2] in ("PRIMARY", "SECONDARY_RIPPLE", "REJECTED")


def test_the_hook_also_appends_the_signals_it_reduced(db_session, strict_mode):
    _company(db_session)
    _persist(db_session)
    kinds = {row[0] for row in db_session.execute(text(
        "SELECT kind FROM signal")).all()}
    assert {"ENTITY_RESOLUTION", "CHANNEL", "DISCOVERY"} <= kinds


def test_a_failing_hook_never_breaks_the_existing_persist_path(
        db_session, strict_mode, monkeypatch, caplog):
    """The isolation requirement, proven by breaking it on purpose."""
    import app.core.impact_writer as writer

    def _boom(*args, **kwargs):
        raise RuntimeError("canonical write exploded")

    monkeypatch.setattr(writer, "record_company_impacts", _boom)

    _company(db_session)
    alert = _persist(db_session)

    assert isinstance(alert, Alert)
    assert db_session.query(AlertCompany).filter_by(alert_id=alert.id).count() == 1
    assert db_session.execute(text("SELECT count(*) FROM company_impact")).scalar() == 0


def test_the_legacy_serving_row_is_unchanged_by_the_hook(db_session, strict_mode):
    """Phase 0 outcome must be 'wrong-but-consistent': the user-facing row
    is identical whether or not the canonical path ran."""
    import app.core.impact_writer as writer

    _company(db_session)
    alert = _persist(db_session)
    with_hook = {
        c.name: getattr(db_session.query(AlertCompany)
                        .filter_by(alert_id=alert.id).one(), c.name)
        for c in AlertCompany.__table__.columns if c.name not in ("id", "alert_id")
    }

    db_session.query(AlertCompany).delete()
    db_session.query(Alert).delete()
    db_session.execute(text("DELETE FROM company_decision_records"))
    db_session.execute(text("DELETE FROM evidence_records"))
    db_session.execute(text("DELETE FROM market_moves"))
    db_session.execute(text("DELETE FROM articles"))
    db_session.commit()

    original = writer.record_company_impacts
    try:
        writer.record_company_impacts = lambda *a, **k: None
        alert2 = _persist(db_session)
    finally:
        writer.record_company_impacts = original

    without_hook = {
        c.name: getattr(db_session.query(AlertCompany)
                        .filter_by(alert_id=alert2.id).one(), c.name)
        for c in AlertCompany.__table__.columns if c.name not in ("id", "alert_id")
    }
    assert with_hook == without_hook


def test_the_supported_version_row_is_seeded_by_create_all(db_session):
    """create_all-built DBs (the whole suite, every fresh dev DB) must carry
    the same version registry the migration writes, or the canonical write
    silently fails everywhere it is tested."""
    from app.core.reducer import REDUCER_VERSION

    rows = db_session.execute(text(
        "SELECT reducer_version FROM supported_version")).all()
    assert (REDUCER_VERSION,) in rows
