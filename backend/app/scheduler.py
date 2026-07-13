import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.analysis.claude_client import build_client
from app.config import settings
from app.db import SessionLocal
from app.ingestion.poller import fetch_new_articles
from app.ingestion.sources import RSS_FEEDS
from app.outcomes.tracker import check_pending_outcomes
from app.pipeline import process_new_articles
from app.translation.groq_translator import build_translation_client
from app.translation.job import translate_pending_alerts, translate_pending_categories

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


def _run_ingestion_and_analysis() -> None:
    """Poll RSS feeds, then run the pipeline over anything new. Claude call
    failures are already handled per-article by process_new_articles (retry
    once, then ANALYSIS_FAILED) — this only guards against the poll/pipeline
    call itself raising, so one bad run never crashes the scheduler thread."""
    session = SessionLocal()
    try:
        inserted = fetch_new_articles(session, RSS_FEEDS)
        client = build_client(settings.groq_api_keys, settings.anthropic_api_key or None)
        created = process_new_articles(session, client, throttle_seconds=2.5)
        logger.info("Poll cycle: %s new articles, %s alerts created", inserted, created)
    except Exception:
        logger.exception("Ingestion/analysis poll cycle failed")
    finally:
        session.close()


def _run_translation() -> None:
    """Translate a small batch of alerts/categories lacking full 7-language
    coverage. Runs on its own interval, its own Groq model quota bucket
    (FALLBACK_MODEL, see translation/groq_translator.py), and a deliberately
    small batch size + throttle -- isolated from _run_ingestion_and_analysis
    so translation traffic can never compete with or degrade the analysis
    pipeline's rate-limit headroom. Any failure is logged, never raised, same
    as every other scheduler job."""
    session = SessionLocal()
    try:
        client = build_translation_client(settings.groq_api_keys)
        translated_categories = translate_pending_categories(session, client)
        translated_alerts = translate_pending_alerts(session, client, limit=15, throttle_seconds=3.0)
        logger.info(
            "Translation cycle: %s categories, %s alerts translated",
            translated_categories, translated_alerts,
        )
    except Exception:
        logger.exception("Translation cycle failed")
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
    scheduler.add_job(
        _run_ingestion_and_analysis,
        trigger="interval",
        minutes=settings.poll_interval_minutes,
        id="rss_poll",
    )
    scheduler.add_job(
        _run_translation,
        trigger="interval",
        minutes=settings.translation_interval_minutes,
        id="translation_job",
    )
    scheduler.start()
    _scheduler = scheduler
