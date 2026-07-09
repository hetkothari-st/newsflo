import statistics

from sqlalchemy.orm import Session

from app.models import CalibrationSample

CALIBRATION_SAMPLE_THRESHOLD = 5


def get_calibrated_magnitude(session: Session, category: str, company_id: int) -> tuple[float, float] | None:
    """Blend historical outcomes for a (category, company) pair into a magnitude
    range. Returns ``(low, high)`` = ``(mean - pstdev, mean + pstdev)`` over the
    actual moves once at least ``CALIBRATION_SAMPLE_THRESHOLD`` samples exist,
    else ``None`` (caller keeps the LLM's own estimate).
    """
    samples = (
        session.query(CalibrationSample)
        .filter(CalibrationSample.category == category)
        .filter(CalibrationSample.company_id == company_id)
        .all()
    )
    if len(samples) < CALIBRATION_SAMPLE_THRESHOLD:
        return None

    values = [s.magnitude_actual for s in samples]
    mean = statistics.mean(values)
    pstdev = statistics.pstdev(values)  # population stdev — full sample set, not a sample of a larger population
    if pstdev == 0:
        return (mean, mean)
    return (mean - pstdev, mean + pstdev)
