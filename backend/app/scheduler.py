import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.analysis.claude_client import build_client
from app.config import settings
from app.db import SessionLocal
from app.ingestion.benzinga import fetch_new_benzinga_articles
# RSS ingestion (poller.py + sources.py) is intact and fully working, just
# not wired in below -- Benzinga's News API is the active source now. Swap
# the fetch_new_articles(...) call back in (and re-enable this import) to
# revert.
# from app.ingestion.poller import fetch_new_articles
# from app.ingestion.sources import RSS_FEEDS
from app.outcomes.tracker import check_pending_outcomes
from app.pipeline import process_new_articles
from app.translation.groq_translator import (
    RECOMMENDED_THROTTLE_SECONDS,
    TRANSLATION_PROVIDER,
    build_translation_client,
    build_translation_clients,
)
from app.translation.job import translate_pending_alerts, translate_pending_categories

# NLLB has no per-minute token cap to respect (local model, no API cost), so
# each scheduler cycle can push through a much bigger batch than the
# throttled Groq/Anthropic path could -- the whole point of self-hosting is
# no longer having to trickle the historical backlog through slowly.
_TRANSLATION_BATCH_LIMIT = 200 if TRANSLATION_PROVIDER == "nllb" else 15

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
    """Poll the news source, then run the pipeline over anything new. Claude
    call failures are already handled per-article by process_new_articles
    (retry once, then ANALYSIS_FAILED) — this only guards against the poll/
    pipeline call itself raising, so one bad run never crashes the scheduler
    thread."""
    session = SessionLocal()
    try:
        inserted = fetch_new_benzinga_articles(session, settings.benzinga_api_key)
        # inserted = fetch_new_articles(session, RSS_FEEDS)  # RSS -- see import comment above
        client = build_client(settings.groq_api_keys, settings.anthropic_api_key or None)
        created = process_new_articles(session, client, throttle_seconds=2.5)
        logger.info("Poll cycle: %s new articles, %s alerts created", inserted, created)
    except Exception:
        logger.exception("Ingestion/analysis poll cycle failed")
    finally:
        session.close()


def _run_translation() -> None:
    """Translate a small batch of alerts/categories lacking full language
    coverage. Runs on its own interval, isolated from
    _run_ingestion_and_analysis so translation traffic can never compete
    with or degrade the analysis pipeline's rate-limit headroom. Any
    failure is logged, never raised, same as every other scheduler job."""
    session = SessionLocal()
    try:
        client = build_translation_client(settings.groq_api_keys, settings.anthropic_api_key or None)
        translated_categories = translate_pending_categories(
            session, client, throttle_seconds=RECOMMENDED_THROTTLE_SECONDS
        )
        clients = build_translation_clients(
            settings.translation_groq_api_keys, settings.anthropic_api_key or None
        )
        translated_alerts = translate_pending_alerts(
            session, clients, limit=_TRANSLATION_BATCH_LIMIT, throttle_seconds=RECOMMENDED_THROTTLE_SECONDS
        )
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
