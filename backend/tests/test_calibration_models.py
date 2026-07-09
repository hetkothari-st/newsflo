import pytest

from app.models import Alert, AlertCompany, Article, CalibrationSample, Company


def _make_alert_company(session):
    company = Company(
        ticker="RELIANCE.NS", name="Reliance Industries",
        sector="oil_gas", index_tier="NIFTY50", market_cap=1.0,
    )
    article = Article(source="test", url="https://example.com/cal-model", title="Oil news", content="")
    session.add_all([company, article])
    session.commit()

    alert = Alert(article_id=article.id, category="oil_energy")
    session.add(alert)
    session.commit()

    ac = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=2.0, magnitude_high=4.0, rationale="margin", basis="direct_mention",
    )
    session.add(ac)
    session.commit()
    return ac


def test_alert_company_confidence_defaults_to_llm_estimate(db_session):
    ac = _make_alert_company(db_session)
    fetched = db_session.query(AlertCompany).filter_by(id=ac.id).one()
    assert fetched.confidence == "llm_estimate"


def test_create_calibration_sample(db_session):
    ac = _make_alert_company(db_session)
    sample = CalibrationSample(
        alert_company_id=ac.id, category="oil_energy", company_id=ac.company_id,
        direction="bullish", magnitude_actual=3.2, horizon_days=3,
    )
    db_session.add(sample)
    db_session.commit()

    fetched = db_session.query(CalibrationSample).one()
    assert fetched.magnitude_actual == 3.2
    assert fetched.horizon_days == 3
    assert fetched.sampled_at is not None


def test_calibration_sample_unique_on_alert_company_and_horizon(db_session):
    ac = _make_alert_company(db_session)
    db_session.add(CalibrationSample(
        alert_company_id=ac.id, category="oil_energy", company_id=ac.company_id,
        direction="bullish", magnitude_actual=1.0, horizon_days=1,
    ))
    db_session.commit()

    db_session.add(CalibrationSample(
        alert_company_id=ac.id, category="oil_energy", company_id=ac.company_id,
        direction="bearish", magnitude_actual=-2.0, horizon_days=1,
    ))
    with pytest.raises(Exception):
        db_session.commit()
