from app.analysis.impact_graph.schemas import GraphCompany, ImpactGraphResult
from app.models import Company, MarketMove
from app.pipeline import process_new_articles
import app.pipeline as pipeline_module


def _company():
    return Company(
        ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas",
        index_tier="NIFTY50", market_cap=1.0,
    )


def _article(db_session):
    from app.models import Article
    article = Article(
        source="test", url="https://example.com/a",
        title="Oil prices surge on supply disruption", content="crude oil markets react",
    )
    db_session.add(article)
    db_session.commit()
    return article


def _fake_analysis():
    return ImpactGraphResult(
        category="oil_gas",
        companies=[GraphCompany(
            ticker="RELIANCE.NS", name="Reliance Industries", direction="bullish",
            impact_strength=0.6, confidence=0.7, materiality=0.6, causal_distance=1,
            time_horizon="Short-Term", mechanism="test mechanism", rationale="refiner margin up",
            key_points=["Crude eases"], reasons=["r1"],
        )],
    )


def test_persist_alert_writes_a_market_move_row_per_company(db_session, monkeypatch):
    company = _company()
    db_session.add(company)
    db_session.commit()
    article = _article(db_session)

    monkeypatch.setattr(pipeline_module, "analyze_article_v3", lambda router, title, content, session=None, article_id=None: _fake_analysis())

    created = process_new_articles(db_session, claude_client=object())

    assert created == 1
    alert = db_session.query(pipeline_module.Alert).one()
    moves = db_session.query(MarketMove).filter_by(alert_id=alert.id).all()
    assert len(moves) == 1
    assert moves[0].company_id == company.id
    # The autouse conftest stub returns no_data -- this test only checks the
    # WIRING (one row per company, alert_id set, no crash), not measurement
    # arithmetic (covered by test_measure.py).
    assert moves[0].measurement_status == "no_data"


def test_persist_alert_does_not_crash_when_measurement_raises_no_data(db_session, monkeypatch):
    # Belt-and-braces: even if measure_company_move's own no_data path is
    # exercised for real (not the conftest stub), _persist_alert must not
    # crash and must still create the Alert + AlertCompany rows.
    from app.models import MarketMove, utcnow

    def fake_measure_real_no_data(session, company, **kwargs):
        return MarketMove(
            company_id=company.id, benchmark_ticker="^CNXENERGY",
            measurement_status="no_data", measured_at=utcnow(),
        )

    monkeypatch.setattr(pipeline_module, "measure_company_move", fake_measure_real_no_data)

    company = _company()
    db_session.add(company)
    db_session.commit()
    article = _article(db_session)
    monkeypatch.setattr(pipeline_module, "analyze_article_v3", lambda router, title, content, session=None, article_id=None: _fake_analysis())

    created = process_new_articles(db_session, claude_client=object())

    assert created == 1
    alert = db_session.query(pipeline_module.Alert).one()
    assert db_session.query(pipeline_module.AlertCompany).filter_by(alert_id=alert.id).count() == 1
    moves = db_session.query(MarketMove).filter_by(alert_id=alert.id).all()
    assert len(moves) == 1
    assert moves[0].benchmark_ticker == "^CNXENERGY"
