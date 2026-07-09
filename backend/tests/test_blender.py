import pytest

from app.calibration.blender import CALIBRATION_SAMPLE_THRESHOLD, get_calibrated_magnitude
from app.models import CalibrationSample


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
