from datetime import datetime, timedelta, timezone

from app.models import Alert, AlertCompany, Article, CalibrationSample, Company
from app.outcomes.tracker import check_pending_outcomes


def _seed_alert_company(session, ticker, url, days_old):
    company = Company(ticker=ticker, name=f"Co {ticker}", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    article = Article(source="test", url=url, title="Oil news", content="")
    session.add_all([company, article])
    session.commit()

    alert = Alert(
        article_id=article.id, category="oil_energy",
        created_at=datetime.now(timezone.utc) - timedelta(days=days_old),
    )
    session.add(alert)
    session.commit()

    ac = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="x", basis="direct_mention",
    )
    session.add(ac)
    session.commit()
    return ac


def test_check_pending_outcomes_creates_sample(db_session):
    _seed_alert_company(db_session, "RELIANCE.NS", "https://example.com/1", days_old=2)

    created = check_pending_outcomes(db_session, horizon_days=1, fetch_fn=lambda t, s, h: 5.0)

    assert created == 1
    sample = db_session.query(CalibrationSample).one()
    assert sample.direction == "bullish"
    assert sample.magnitude_actual == 5.0
    assert sample.horizon_days == 1
    assert sample.category == "oil_energy"


def test_check_pending_outcomes_is_idempotent(db_session):
    _seed_alert_company(db_session, "RELIANCE.NS", "https://example.com/1", days_old=2)

    first = check_pending_outcomes(db_session, horizon_days=1, fetch_fn=lambda t, s, h: 5.0)
    second = check_pending_outcomes(db_session, horizon_days=1, fetch_fn=lambda t, s, h: 5.0)

    assert first == 1
    assert second == 0
    assert db_session.query(CalibrationSample).count() == 1


def test_check_pending_outcomes_skips_alerts_younger_than_horizon(db_session):
    _seed_alert_company(db_session, "RELIANCE.NS", "https://example.com/1", days_old=2)

    created = check_pending_outcomes(db_session, horizon_days=7, fetch_fn=lambda t, s, h: 5.0)

    assert created == 0
    assert db_session.query(CalibrationSample).count() == 0


def test_check_pending_outcomes_skips_none_but_continues_batch(db_session):
    _seed_alert_company(db_session, "GOOD.NS", "https://example.com/good", days_old=2)
    _seed_alert_company(db_session, "BAD.NS", "https://example.com/bad", days_old=2)

    def fetch_fn(ticker, start_date, horizon_days):
        if ticker == "BAD.NS":
            return None
        return 3.0

    created = check_pending_outcomes(db_session, horizon_days=1, fetch_fn=fetch_fn)

    assert created == 1
    samples = db_session.query(CalibrationSample).all()
    assert len(samples) == 1
    assert samples[0].magnitude_actual == 3.0  # the GOOD ticker was sampled; BAD (None) was skipped
