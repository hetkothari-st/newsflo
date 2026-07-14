from sqlalchemy.orm import Session

from app.models import AlertCompany, CalibrationSample

WIN_RATE_SAMPLE_THRESHOLD = 5


def get_win_rate(session: Session, company_id: int) -> dict[str, dict] | None:
    """Per-horizon win rate for a company: the fraction of calibration
    samples where the LLM's predicted direction (``AlertCompany.direction``)
    matched what actually happened (``CalibrationSample.direction``).

    A horizon only appears once it has at least ``WIN_RATE_SAMPLE_THRESHOLD``
    samples (same "not enough data yet, degrade gracefully" convention as
    ``calibration.blender.CALIBRATION_SAMPLE_THRESHOLD``, kept as its own
    constant since this gates a different grouping key -- (company, horizon)
    rather than (category, company)). Returns ``None`` if no horizon
    qualifies.
    """
    rows = (
        session.query(CalibrationSample.horizon_days, CalibrationSample.direction, AlertCompany.direction)
        .join(AlertCompany, CalibrationSample.alert_company_id == AlertCompany.id)
        .filter(CalibrationSample.company_id == company_id)
        .all()
    )

    by_horizon: dict[int, list[bool]] = {}
    for horizon_days, actual_direction, predicted_direction in rows:
        by_horizon.setdefault(horizon_days, []).append(actual_direction == predicted_direction)

    result = {}
    for horizon_days, matches in by_horizon.items():
        if len(matches) < WIN_RATE_SAMPLE_THRESHOLD:
            continue
        result[str(horizon_days)] = {
            "win_rate": sum(matches) / len(matches),
            "sample_size": len(matches),
        }

    return result or None
