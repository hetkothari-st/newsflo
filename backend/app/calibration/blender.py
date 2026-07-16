import statistics

from sqlalchemy.orm import Session

from app.models import AlertCompany, CalibrationSample

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


def get_calibration_health(session: Session, category: str, company_id: int) -> dict:
    """Summarize past-outcome accuracy for a (category, company) pair, for the
    Confidence Engine's historical-calibration component (app.reasoning.
    confidence.compute_confidence). Unlike get_calibrated_magnitude, this
    needs the ORIGINAL predicted direction to compute a hit rate --
    CalibrationSample only stores the actual outcome, so it joins back to
    the originating AlertCompany row.
    """
    rows = (
        session.query(CalibrationSample, AlertCompany)
        .join(AlertCompany, CalibrationSample.alert_company_id == AlertCompany.id)
        .filter(CalibrationSample.category == category)
        .filter(CalibrationSample.company_id == company_id)
        .all()
    )
    sample_count = len(rows)
    if sample_count == 0:
        return {"sample_count": 0, "hit_rate": None, "mean_error": None}

    hits = sum(1 for sample, ac in rows if sample.direction == ac.direction)
    hit_rate = hits / sample_count

    errors = [abs(sample.magnitude_actual - (ac.magnitude_low + ac.magnitude_high) / 2) for sample, ac in rows]
    mean_error = statistics.mean(errors)

    return {"sample_count": sample_count, "hit_rate": hit_rate, "mean_error": mean_error}
