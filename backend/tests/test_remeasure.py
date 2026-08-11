"""remeasure_no_data_moves: a transient price-fetch failure at persist
time must not orphan an alert forever -- the feed only ever shows alerts
with a measured (status "ok") move, so an unmeasured alert is invisible
until someone re-measures it (production 2026-08-11: every alert on the
ingestion-v2 service sat at no_data and the feed rendered empty)."""
import json
from datetime import timedelta

from app.models import Alert, AlertCompany, Article, Company, MarketMove, utcnow
from app.pipeline import remeasure_no_data_moves


def _seed(db, *, direction="bullish", created_at=None):
    article = Article(source="pulse_zerodha", provider="pulse_zerodha",
                      url="https://ex.com/a", title="t", content="c", status="ALERTED")
    company = Company(name="Reliance Industries", ticker="RELIANCE.NS", sector="oil_gas",
                      index_tier="NIFTY50")
    db.add_all([article, company])
    db.commit()
    alert = Alert(article_id=article.id, category="policy")
    if created_at is not None:
        alert.created_at = created_at
    db.add(alert)
    db.commit()
    alert_company = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction=direction,
        magnitude_low=1.0, magnitude_high=3.0, rationale="prediction text",
        key_points_json=json.dumps(["point"]), basis="direct_mention",
    )
    move = MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^NSEI",
        measurement_status="no_data", measured_at=utcnow(), category="policy",
    )
    db.add_all([alert_company, move])
    db.commit()
    return alert, company, alert_company, move


def _ok_move(company, excess=-2.5):
    return MarketMove(
        company_id=company.id, benchmark_ticker="^CNXENERGY", raw_move_pct=excess + 0.5,
        sector_move_pct=0.5, excess_move_pct=excess, volume=1000.0, avg_volume_20d=500.0,
        volume_multiple=2.0, vol_normalized=1.1, materiality=0.01, avg_traded_value=9e8,
        measured_at=utcnow(), measurement_status="ok",
    )


def test_remeasure_updates_no_data_rows_in_place_and_reconciles_direction(db_session, monkeypatch):
    alert, company, alert_company, move = _seed(db_session, direction="bullish")
    import app.pipeline as pipeline_module
    monkeypatch.setattr(pipeline_module, "measure_company_move",
                        lambda session, c: _ok_move(c, excess=-2.5))

    fixed = remeasure_no_data_moves(db_session)

    assert fixed == 1
    db_session.refresh(move)
    assert move.measurement_status == "ok"
    assert move.excess_move_pct == -2.5
    assert move.benchmark_ticker == "^CNXENERGY"
    assert move.category == "policy"  # stamped category never re-shuffles
    # Same reconcile rule as first-time measurement: the measured reality
    # overrides the LLM's pre-measurement guess, and the now-contradicted
    # prose is dropped rather than shown under a flipped badge.
    db_session.refresh(alert_company)
    assert alert_company.direction == "bearish"
    assert alert_company.rationale is None
    assert json.loads(alert_company.key_points_json) == []


def test_remeasure_leaves_row_untouched_when_data_is_still_missing(db_session, monkeypatch):
    _, company, alert_company, move = _seed(db_session)
    import app.pipeline as pipeline_module
    monkeypatch.setattr(
        pipeline_module, "measure_company_move",
        lambda session, c: MarketMove(company_id=c.id, benchmark_ticker="^NSEI",
                                      measurement_status="no_data", measured_at=utcnow()),
    )

    assert remeasure_no_data_moves(db_session) == 0
    db_session.refresh(move)
    assert move.measurement_status == "no_data"
    db_session.refresh(alert_company)
    assert alert_company.direction == "bullish"
    assert alert_company.rationale == "prediction text"


def test_remeasure_skips_old_alerts(db_session, monkeypatch):
    _seed(db_session, created_at=utcnow() - timedelta(days=10))
    import app.pipeline as pipeline_module
    monkeypatch.setattr(pipeline_module, "measure_company_move",
                        lambda session, c: _ok_move(c))

    # An old no_data alert is history, not a pending repair -- re-measuring
    # it now would write TODAY's bar as if it were the event-day reaction.
    assert remeasure_no_data_moves(db_session) == 0
