"""CAR (Cumulative Abnormal Return) review, spec §4.6: back-validates a
flagged reaction by summing (ticker - benchmark) daily returns over
trading days -1..+3 once the market has actually traded that far. "Not
live -- it completes days later" (spec) -- this module's job is entirely
scheduled/batch, never called on a live request path.
"""
from datetime import timedelta

from sqlalchemy.orm import Session

from app import config
from app.models import Alert, AlertCompany, CarOutcome, MarketMove, utcnow
from app.outcomes.price_fetcher import fetch_cumulative_excess_return

# Generous buffer: a -1..+3 trading-day window is well within a week even
# across a long weekend/holiday cluster. An alert younger than this cannot
# possibly have a fully-traded window yet, so it's cheaper to skip it at
# the query level than to call the fetch function and get a None back.
_MIN_ALERT_AGE_DAYS = 7


def compute_car_outcome_label(day0_excess_move_pct: float, car_pct: float) -> str:
    """"Held" vs "reversed" (spec §4.6): a same-sign comparison between the
    original flagged reaction and the actual outcome, with a dead zone
    around zero (config.CAR_FLAT_THRESHOLD_PCT) classified as neither."""
    if abs(car_pct) < config.CAR_FLAT_THRESHOLD_PCT:
        return "FLAT"
    same_sign = (day0_excess_move_pct >= 0) == (car_pct >= 0)
    return "HELD" if same_sign else "REVERSED"


def check_pending_car_outcomes(
    session: Session, fetch_fn=fetch_cumulative_excess_return,
) -> int:
    """For every AlertCompany with a real measured MarketMove
    (measurement_status='ok') whose Alert is at least _MIN_ALERT_AGE_DAYS
    old and has no CarOutcome yet, compute CAR and record it. A None
    fetch result (market hasn't traded that far yet, or data unavailable)
    is skipped -- retried next run, never blocks the rest of the batch
    (same contract as app.outcomes.tracker.check_pending_outcomes).
    Returns the number of rows created.
    """
    cutoff = utcnow() - timedelta(days=_MIN_ALERT_AGE_DAYS)
    already_sampled_ids = session.query(CarOutcome.alert_company_id)

    pending = (
        session.query(AlertCompany, MarketMove)
        .join(Alert, AlertCompany.alert_id == Alert.id)
        .join(
            MarketMove,
            (MarketMove.alert_id == AlertCompany.alert_id) & (MarketMove.company_id == AlertCompany.company_id),
        )
        .filter(Alert.created_at <= cutoff)
        .filter(MarketMove.measurement_status == "ok")
        .filter(~AlertCompany.id.in_(already_sampled_ids))
        .all()
    )

    created = 0
    for alert_company, move in pending:
        car_pct = fetch_fn(alert_company.company.ticker, move.benchmark_ticker, alert_company.alert.created_at)
        if car_pct is None:
            continue
        session.add(CarOutcome(
            alert_company_id=alert_company.id,
            company_id=alert_company.company_id,
            category=alert_company.alert.category,
            day0_excess_move_pct=move.excess_move_pct,
            car_pct=car_pct,
        ))
        session.commit()
        created += 1
    return created
