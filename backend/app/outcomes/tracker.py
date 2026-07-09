from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import Alert, AlertCompany, CalibrationSample
from app.outcomes.price_fetcher import fetch_price_change_pct


def check_pending_outcomes(session: Session, horizon_days: int, fetch_fn=fetch_price_change_pct) -> int:
    """For every AlertCompany whose Alert is at least ``horizon_days`` old and has
    no CalibrationSample yet for this horizon, fetch the actual price move and
    record a sample. A ``None`` fetch result is skipped (retried next run) and
    never blocks the rest of the batch. Returns the number of samples created.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=horizon_days)

    already_sampled_ids = (
        session.query(CalibrationSample.alert_company_id)
        .filter(CalibrationSample.horizon_days == horizon_days)
    )

    pending = (
        session.query(AlertCompany)
        .join(AlertCompany.alert)
        .filter(Alert.created_at <= cutoff)
        .filter(~AlertCompany.id.in_(already_sampled_ids))
        .all()
    )

    created = 0
    for ac in pending:
        result = fetch_fn(ac.company.ticker, ac.alert.created_at, horizon_days)
        if result is None:
            continue
        session.add(CalibrationSample(
            alert_company_id=ac.id,
            category=ac.alert.category,
            company_id=ac.company_id,
            direction="bullish" if result >= 0 else "bearish",
            magnitude_actual=result,
            horizon_days=horizon_days,
        ))
        session.commit()
        created += 1

    return created
