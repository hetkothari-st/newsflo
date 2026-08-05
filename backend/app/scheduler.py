import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from app.analysis.claude_client import build_client
from app.analysis.refinement import run_pending_refinements
from app.companies.market_caps import alert_referenced_tickers, refresh_market_caps
from app.companies.universe import fetchers, snapshot
from app.config import settings
from app.db import SessionLocal
# IndianAPI is disabled (not deleted) -- replaced by thenewsapi.com, see
# docs/superpowers/specs/2026-07-20-thenewsapi-ingestion-source-design.md.
# Swap the fetch_new_indianapi_articles(...) call back in (and re-enable
# this import and the _run_indianapi_ingestion function below) to revert.
# from app.ingestion.indianapi import fetch_new_indianapi_articles
# thenewsapi is disabled (not deleted) -- replaced by finnhub.io, see
# docs/superpowers/specs/2026-07-21-finnhub-ingestion-source-design.md.
# Swap the fetch_new_thenewsapi_articles(...) call back in (and re-enable
# this import and the _run_thenewsapi_ingestion function below) to revert.
# from app.ingestion.thenewsapi import fetch_new_thenewsapi_articles
from app.ingestion.finnhub import fetch_new_finnhub_articles
# RSS ingestion (poller.py + sources.py) is intact and fully working, just
# not wired in below -- IndianAPI's /news endpoint is the active source now.
# Swap the fetch_new_articles(...) call back in (and re-enable this import)
# to revert.
# from app.ingestion.poller import fetch_new_articles
# from app.ingestion.sources import RSS_FEEDS
from app.outcomes.car import check_pending_car_outcomes
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


def _run_car_review() -> None:
    """Open a fresh session, run the CAR outcome check, and always close
    the session. Any error is logged, never raised, so one failing run
    does not crash the scheduler thread -- same contract as
    _run_horizon."""
    session = SessionLocal()
    try:
        created = check_pending_car_outcomes(session)
        logger.info("CAR review cycle: %s outcomes recorded", created)
    except Exception:
        logger.exception("CAR review run failed")
    finally:
        session.close()


# def _run_indianapi_ingestion() -> None:
#     """Poll IndianAPI's /news endpoint for fresh Indian market news. Runs on
#     its own, much longer interval (indianapi_poll_interval_minutes) rather
#     than the fast analysis cycle below -- this key is capped at 500
#     requests/month, nowhere near enough for a 2-minute cadence. Whatever
#     lands here (status=NEW) is picked up and analyzed by the next regular
#     _run_ingestion_and_analysis tick, not here. Any failure is logged, never
#     raised, same as every other scheduler job."""
#     session = SessionLocal()
#     try:
#         inserted = fetch_new_indianapi_articles(session, settings.indianapi_api_key)
#         logger.info("IndianAPI poll: %s new articles", inserted)
#     except Exception:
#         logger.exception("IndianAPI ingestion poll failed")
#     finally:
#         session.close()


# def _run_thenewsapi_ingestion() -> None:
#     """Poll thenewsapi.com's /v1/news/all endpoint for fresh business/
#     politics/general/tech news. Runs on its own, much longer interval
#     (thenewsapi_poll_interval_minutes) rather than the fast per-minute
#     analysis cycle -- this key is capped at 100 requests/day. Any failure
#     is logged, never raised, same as every other scheduler job."""
#     session = SessionLocal()
#     try:
#         inserted = fetch_new_thenewsapi_articles(session, settings.thenewsapi_api_key)
#         logger.info("thenewsapi poll: %s new articles", inserted)
#     except Exception:
#         logger.exception("thenewsapi ingestion poll failed")
#     finally:
#         session.close()


def _run_finnhub_ingestion() -> None:
    """Poll finnhub.io's /v1/news endpoint (general + merger categories)
    for fresh market news. Runs on its own interval
    (finnhub_poll_interval_minutes) rather than the fast per-minute
    analysis cycle. Any failure is logged, never raised, same as every
    other scheduler job."""
    session = SessionLocal()
    try:
        inserted = fetch_new_finnhub_articles(session, settings.finnhub_api_key)
        logger.info("finnhub poll: %s new articles", inserted)
    except Exception:
        logger.exception("finnhub ingestion poll failed")
    finally:
        session.close()


def _run_ingestion_and_analysis() -> None:
    """Run the pipeline over any pending (status=NEW) articles, regardless
    of which ingestion job inserted them. Claude call failures are already
    handled per-article by process_new_articles (retry once, then
    ANALYSIS_FAILED) — this only guards against the pipeline call itself
    raising, so one bad run never crashes the scheduler thread."""
    session = SessionLocal()
    try:
        # inserted = fetch_new_articles(session, RSS_FEEDS)  # RSS -- see import comment above
        client = build_client(settings.groq_api_keys, settings.gemini_api_key or None)
        created = process_new_articles(session, client, throttle_seconds=2.5)
        logger.info("Analysis cycle: %s alerts created", created)
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


def _run_deferred_refinement() -> None:
    """Fill in the LLM refinement fields (event summary, per-company whys,
    ripple sections, timeline) for alerts persisted with refinement
    deferred -- a no-op unless settings.refinement_mode is "deferred".

    Kept on its own interval for the same reason as _run_translation:
    refinement is latency-tolerant work that nothing user-facing waits on,
    so it must never compete with the analysis pipeline for the provider's
    rate-limit headroom. Any failure is logged, never raised, same as every
    other scheduler job."""
    if settings.refinement_mode != "deferred":
        return
    session = SessionLocal()
    try:
        client = build_client(settings.groq_api_keys, settings.gemini_api_key or None)
        refined = run_pending_refinements(
            client, session, throttle_seconds=2.5,
        )
        if refined:
            logger.info("Deferred refinement cycle: %s alerts refined", refined)
    except Exception:
        logger.exception("Deferred refinement cycle failed")
    finally:
        session.close()


def _run_analysis_retry() -> None:
    """Give today's ANALYSIS_FAILED articles another chance, once per hour
    -- analysis failures are overwhelmingly transient provider rate-limit
    storms (confirmed in production: both Groq orgs' daily token budgets
    exhausted mid-day marked a whole batch failed), and a failed article
    otherwise stays failed forever. Hourly cadence keeps this bounded: at
    most one extra 2-attempt round per article per hour, never a hot loop
    against a dead quota. Only TODAY's articles -- older news re-analyzed
    now would surface into the current feed as stale alerts."""
    from app.ist_time import day_utc_window, today_ist
    from app.models import Article

    session = SessionLocal()
    try:
        start_utc, _ = day_utc_window(today_ist())
        reset = (
            session.query(Article)
            .filter(Article.status == "ANALYSIS_FAILED", Article.fetched_at >= start_utc)
            .update({"status": "CATEGORIZED"}, synchronize_session=False)
        )
        session.commit()
        if reset:
            logger.info("Analysis retry: %s of today's failed articles re-queued", reset)
    except Exception:
        logger.exception("Analysis retry sweep failed")
    finally:
        session.close()


def _run_market_cap_refresh() -> None:
    """Refresh Company.market_cap for every company referenced by a recent
    alert -- the input to the cap-tier ranking behind every LARGE/MID/
    SMALL/MICRO tag and the feed's cap filter (spec v2 §4.5). Failures
    logged, never raised, same as every other scheduler job."""
    session = SessionLocal()
    try:
        tickers = alert_referenced_tickers(session, days=7)
        updated = refresh_market_caps(session, tickers)
        logger.info("Market-cap refresh: %s/%s companies updated", updated, len(tickers))
    except Exception:
        logger.exception("Market-cap refresh failed")
    finally:
        session.close()


def _run_universe_master_refresh() -> None:
    """Daily: refetch both exchange masters and reload. Two requests.

    Detail fetching is deliberately NOT done here -- that is ~5,000
    requests and runs on its own monthly job (_run_universe_detail_refresh).
    Any failure is logged, never raised, same as every other scheduler job."""
    from datetime import date

    import ingest_universe

    session = SessionLocal()
    try:
        today = date.today()
        fetchers.fetch_nse_equity_list(snapshot.DEFAULT_ROOT, today)
        fetchers.fetch_bse_scrip_list(snapshot.DEFAULT_ROOT, today)
        result = ingest_universe.run_ingest(
            snapshot.DEFAULT_ROOT, today, session, fetch=False,
        )
        logger.info("Universe master refresh: %s", result)
    except Exception:
        logger.exception("Universe master refresh failed")
    finally:
        session.close()


def _run_universe_detail_refresh() -> None:
    """Monthly: the ~5,000-request official-classification pass against the
    latest master snapshot on disk. Resumable -- fetch_bse_details skips
    codes already fetched for that day, so an interrupted run continues
    from disk on the next firing. Any failure is logged, never raised, same
    as every other scheduler job."""
    from app.companies.universe import normalize

    try:
        day = snapshot.latest_snapshot_day(snapshot.DEFAULT_ROOT)
        if day is None:
            logger.warning("Universe detail refresh skipped: no snapshot on disk")
            return

        bse_path = snapshot.master_path(snapshot.DEFAULT_ROOT, day, "bse_scrips.json")
        rows = normalize.parse_bse_rows(bse_path.read_text(encoding="utf-8"))
        codes = [(r.get("SCRIP_CD") or "").strip() for r in rows]
        result = fetchers.fetch_bse_details(
            snapshot.DEFAULT_ROOT, day, [c for c in codes if c],
        )
        # Never silent: the count of scrips whose detail fetch failed must
        # always be visible, not just buried in a list.
        logger.info(
            "Universe detail refresh: fetched=%s skipped=%s failed=%s aborted=%s",
            result["fetched"], result["skipped"], len(result["failed"]),
            result.get("aborted", False),
        )
        if result.get("aborted"):
            # A blocked source, not a bad month. Distinct log level because
            # the outcome is indistinguishable from success in the counts
            # above when almost nothing was due to be fetched.
            logger.error(
                "Universe detail refresh ABORTED: BSE refused %s consecutive "
                "scrips. Classification data is unchanged, not cleared. Run "
                "the detail pass from a network BSE answers and ship the "
                "snapshot to the volume.",
                len(result["failed"]),
            )
    except Exception:
        logger.exception("Universe detail refresh failed")


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
        _run_car_review,
        trigger="interval",
        minutes=60,
        id="car_review",
    )
    # IndianAPI job disabled -- see the import comment above. Restore this
    # block (and re-enable _run_indianapi_ingestion) to revert.
    # scheduler.add_job(
    #     _run_indianapi_ingestion,
    #     trigger="interval",
    #     minutes=settings.indianapi_poll_interval_minutes,
    #     id="indianapi_poll",
    # )
    # thenewsapi job disabled -- see the import comment above. Restore
    # this block (and re-enable _run_thenewsapi_ingestion) to revert.
    # scheduler.add_job(
    #     _run_thenewsapi_ingestion,
    #     trigger="interval",
    #     minutes=settings.thenewsapi_poll_interval_minutes,
    #     id="thenewsapi_poll",
    # )
    scheduler.add_job(
        _run_finnhub_ingestion,
        trigger="interval",
        minutes=settings.finnhub_poll_interval_minutes,
        id="finnhub_poll",
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
    scheduler.add_job(
        _run_deferred_refinement,
        trigger="interval",
        minutes=settings.refinement_interval_minutes,
        id="deferred_refinement",
    )
    scheduler.add_job(
        _run_analysis_retry,
        trigger="interval",
        hours=1,
        id="analysis_retry",
    )
    scheduler.add_job(
        _run_market_cap_refresh,
        trigger="interval",
        hours=12,
        # Also once shortly after boot -- a fresh deploy against a DB with
        # mostly-null caps (the state that made every cap tag render "—"
        # and the L/M/S/µ filter match nothing) fixes itself without
        # waiting half a day.
        next_run_time=datetime.now(timezone.utc) + timedelta(minutes=2),
        id="market_cap_refresh",
    )
    scheduler.add_job(
        _run_universe_master_refresh,
        trigger="interval",
        hours=24,
        id="universe_master_refresh",
    )
    scheduler.add_job(
        _run_universe_detail_refresh,
        trigger="interval",
        days=30,
        # Never at boot: this is ~5,000 throttled requests taking 30-40
        # minutes, and a restart loop would hammer BSE.
        next_run_time=datetime.now(timezone.utc) + timedelta(days=1),
        id="universe_detail_refresh",
    )
    scheduler.start()
    _scheduler = scheduler
