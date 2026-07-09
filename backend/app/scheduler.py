import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.db import SessionLocal
from app.outcomes.tracker import check_pending_outcomes

logger = logging.getLogger(__name__)

# Module-level reference so the scheduler thread is not garbage-collected.
_scheduler: BackgroundScheduler | None = None

HORIZONS = (1, 3, 7)


def _run_horizon(horizon_days: int) -> None:
    """Open a fresh session, run the outcome tracker for one horizon, and always
    close the session. Any error is logged, never raised, so one failing run does
    not crash the scheduler thread."""
    session = SessionLocal()
    try:
        check_pending_outcomes(session, horizon_days)
    except Exception:
        logger.exception("Outcome tracker run failed for horizon_days=%s", horizon_days)
    finally:
        session.close()


def start_scheduler() -> None:
    global _scheduler
    scheduler = BackgroundScheduler()
    for horizon in HORIZONS:
        scheduler.add_job(
            _run_horizon,
            trigger="interval",
            minutes=60,
            args=[horizon],
            id=f"outcome_tracker_{horizon}d",
        )
    scheduler.start()
    _scheduler = scheduler
