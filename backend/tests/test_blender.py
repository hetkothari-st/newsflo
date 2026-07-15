import pytest

from app.calibration.blender import CALIBRATION_SAMPLE_THRESHOLD, get_calibrated_magnitude, get_calibration_health
from app.models import Alert, AlertCompany, Article, CalibrationSample, Company


def _add_sample(session, category, company_id, magnitude_actual, alert_company_id, horizon_days):
    session.add(CalibrationSample(
        alert_company_id=alert_company_id, category=category, company_id=company_id,
        direction="bullish" if magnitude_actual >= 0 else "bearish",
        magnitude_actual=magnitude_actual, horizon_days=horizon_days,
    ))


def test_threshold_is_five():
    assert CALIBRATION_SAMPLE_THRESHOLD == 5


def test_returns_none_below_threshold(db_session):
    for i, value in enumerate([1.0, 2.0, 3.0, 4.0]):  # 4 samples, below threshold
        _add_sample(db_session, "oil_energy", 1, value, alert_company_id=i + 1, horizon_days=1)
    db_session.commit()

    assert get_calibrated_magnitude(db_session, category="oil_energy", company_id=1) is None


def test_returns_mean_plus_minus_pstdev_at_threshold(db_session):
    # 5 samples of [1, 2, 3, 4, 5] -> mean = 3.0, pstdev = sqrt(2) ~= 1.41421356
    for i, value in enumerate([1.0, 2.0, 3.0, 4.0, 5.0]):
        _add_sample(db_session, "oil_energy", 1, value, alert_company_id=i + 1, horizon_days=1)
    db_session.commit()

    result = get_calibrated_magnitude(db_session, category="oil_energy", company_id=1)

    assert result is not None
    low, high = result
    assert low == pytest.approx(3.0 - 2 ** 0.5)
    assert high == pytest.approx(3.0 + 2 ** 0.5)


def test_excludes_other_category_and_company(db_session):
    # 5 matching samples of [10, 10, 10, 10, 10] -> mean = 10.0, pstdev = 0 -> (10.0, 10.0)
    for i, value in enumerate([10.0, 10.0, 10.0, 10.0, 10.0]):
        _add_sample(db_session, "oil_energy", 1, value, alert_company_id=i + 1, horizon_days=1)
    # noise that must NOT be included in the (oil_energy, company 1) calculation
    _add_sample(db_session, "banking", 1, -50.0, alert_company_id=100, horizon_days=1)
    _add_sample(db_session, "oil_energy", 2, -50.0, alert_company_id=101, horizon_days=1)
    db_session.commit()

    result = get_calibrated_magnitude(db_session, category="oil_energy", company_id=1)

    assert result == pytest.approx((10.0, 10.0))


def test_calibration_health_returns_zero_stats_with_no_samples(db_session):
    result = get_calibration_health(db_session, category="oil_energy", company_id=1)
    assert result == {"sample_count": 0, "hit_rate": None, "mean_error": None}


def test_calibration_health_computes_hit_rate_and_mean_error(db_session):
    company = Company(ticker="X.NS", name="X", sector="oil_gas", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()
    article = Article(source="test", url="https://example.com/health", title="t")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()

    # Two predictions, both originally "bullish": one correct (actual also
    # bullish), one wrong (actual bearish) -- hit_rate must be 0.5.
    ac1 = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=2.0, magnitude_high=4.0, rationale="x", basis="direct_mention",
    )
    ac2 = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=2.0, magnitude_high=4.0, rationale="x", basis="direct_mention",
    )
    db_session.add_all([ac1, ac2])
    db_session.commit()

    db_session.add(CalibrationSample(
        alert_company_id=ac1.id, category="oil_energy", company_id=company.id,
        direction="bullish", magnitude_actual=5.0, horizon_days=1,
    ))
    db_session.add(CalibrationSample(
        alert_company_id=ac2.id, category="oil_energy", company_id=company.id,
        direction="bearish", magnitude_actual=-1.0, horizon_days=1,
    ))
    db_session.commit()

    result = get_calibration_health(db_session, category="oil_energy", company_id=company.id)

    assert result["sample_count"] == 2
    assert result["hit_rate"] == pytest.approx(0.5)
    # predicted_mid = (2.0+4.0)/2 = 3.0 for both rows.
    # errors: |5.0-3.0|=2.0, |-1.0-3.0|=4.0 -> mean = 3.0
    assert result["mean_error"] == pytest.approx(3.0)


def test_calibration_health_excludes_other_category_and_company(db_session):
    company = Company(ticker="Y.NS", name="Y", sector="oil_gas", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()
    article = Article(source="test", url="https://example.com/health2", title="t")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()

    matching = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=1.0, rationale="x", basis="direct_mention",
    )
    db_session.add(matching)
    db_session.commit()
    db_session.add(CalibrationSample(
        alert_company_id=matching.id, category="oil_energy", company_id=company.id,
        direction="bullish", magnitude_actual=1.0, horizon_days=1,
    ))
    # Noise: different category, same company -- must not be counted.
    db_session.add(CalibrationSample(
        alert_company_id=matching.id, category="banking", company_id=company.id,
        direction="bearish", magnitude_actual=-99.0, horizon_days=2,
    ))
    db_session.commit()

    result = get_calibration_health(db_session, category="oil_energy", company_id=company.id)

    assert result["sample_count"] == 1
