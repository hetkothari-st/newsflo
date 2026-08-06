import logging
import time
from datetime import date, datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from app.analysis.claude_client import build_client
from app.analysis.refinement import run_pending_refinements
from app.companies.market_caps import alert_referenced_tickers, refresh_market_caps
from app.companies.supply_links import snapshot as supply_snapshot
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


# BSE throttles this app's egress hard: measured 2026-08-05, roughly half
# of back-to-back detail requests time out, but a retried scrip succeeds
# essentially always (25/25 with up to 3 attempts). So the pass is not
# blocked, it is slow -- and the way to consume a slow source unattended is
# a small budget every day rather than one long run every month.
_DETAIL_BUDGET_SECONDS = 45 * 60
_DETAIL_THROTTLE_SECONDS = 1.5
_DETAIL_MAX_RETRIES = 4


def _run_universe_detail_refresh() -> None:
    """Daily, time-boxed: chips away at the ~4,700-request official-
    classification pass until it is complete, then idles until the snapshot
    ages out.

    Resumable in two senses. Within a directory, fetch_bse_details skips
    codes already on disk. Across days, detail_target_day keeps writing into
    the SAME dated directory instead of following the daily master refresh
    into a fresh empty one -- without that, a daily job would restart the
    whole pass every morning and never finish it.

    Any failure is logged, never raised, same as every other scheduler job.
    """
    from app.companies.universe import normalize

    try:
        day = snapshot.detail_target_day(snapshot.DEFAULT_ROOT, date.today())
        if day is None:
            logger.warning("Universe detail refresh skipped: no snapshot on disk")
            return

        bse_path = snapshot.master_path(snapshot.DEFAULT_ROOT, day, "bse_scrips.json")
        rows = normalize.parse_bse_rows(bse_path.read_text(encoding="utf-8"))
        codes = [(r.get("SCRIP_CD") or "").strip() for r in rows]
        result = fetchers.fetch_bse_details(
            snapshot.DEFAULT_ROOT, day, [c for c in codes if c],
            throttle_seconds=_DETAIL_THROTTLE_SECONDS,
            max_retries=_DETAIL_MAX_RETRIES,
            time_budget_seconds=_DETAIL_BUDGET_SECONDS,
        )
        # Never silent: the count of scrips whose detail fetch failed must
        # always be visible, not just buried in a list.
        logger.info(
            "Universe detail refresh (%s): fetched=%s skipped=%s failed=%s "
            "remaining=%s exhausted=%s aborted=%s",
            day.isoformat(), result["fetched"], result["skipped"],
            len(result["failed"]), result.get("remaining"),
            result.get("exhausted", False), result.get("aborted", False),
        )
        if result.get("aborted"):
            # Distinct from "ran out of time": every retry of 50 scrips in a
            # row failed, which is a source problem, not a pacing one.
            logger.error(
                "Universe detail refresh ABORTED: BSE refused %s consecutive "
                "scrips. Classification data is unchanged, not cleared; the "
                "next daily firing resumes from disk.",
                len(result["failed"]),
            )
    except Exception:
        logger.exception("Universe detail refresh failed")


def _run_event_volatility_refresh() -> None:
    """Nightly: rebuild event_volatility_ranges from measured market_moves
    (subsystem D). DB-only -- no network. Coverage widens by itself as the
    app measures more events; nothing manual, ever. Logged, never raises,
    same discipline as every other job."""
    from app.market.event_volatility import rebuild

    session = SessionLocal()
    try:
        result = rebuild(session, date.today())
        logger.info(
            "Event volatility refresh: facts=%s deleted=%s inserted=%s",
            result["facts"], result["deleted"], result["inserted"],
        )
    except Exception:
        logger.exception("Event volatility refresh failed")
    finally:
        session.close()


def _run_rating_filings_poll() -> None:
    """Daily: pages BSE's Credit Rating announcements for yesterday->today
    and fetches every rationale PDF they name. No time budget -- a single
    day's rating filings are dozens of rows, not thousands, so both the
    announcements page and the document fetch comfortably finish inside one
    tick. Extraction of the fetched PDFs is NOT done here -- that is the
    separately-budgeted _run_supply_links_refresh, so a slow LLM pass never
    delays tomorrow's poll. Any failure is logged, never raised, same as
    every other scheduler job."""
    from app.companies.supply_links import fetchers as supply_fetchers

    try:
        today = date.today()
        yesterday = today - timedelta(days=1)
        rows = supply_fetchers.fetch_announcements(
            supply_snapshot.DEFAULT_ROOT, today, yesterday, today,
        )
        targets = supply_fetchers.parse_announcements(rows)
        result = supply_fetchers.fetch_documents(supply_snapshot.DEFAULT_ROOT, targets)
        logger.info(
            "Rating filings poll: %s announcement rows, %s rating docs, "
            "fetched=%s skipped=%s failed=%s",
            len(rows), len(targets), result["fetched"], result["skipped"],
            len(result["failed"]),
        )
    except Exception:
        logger.exception("Rating filings poll failed")


def _parse_news_date(value) -> date | None:
    """meta.json's news_date is BSE's raw NEWS_DT string (an ISO-ish
    datetime, e.g. "2026-08-04T17:47:01.793"). Best-effort parse to a date
    for loader.apply_extraction's recency gate -- a missing or unparsable
    value must never crash the extraction drain, just fall back to
    "today" (the caller's responsibility) so the document is still
    processed."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


# BSE's LLM-as-reader call (extract.extract_profile) is the slow step here,
# not network fetch -- 30 minutes is generous headroom for a daily backlog
# without letting a stuck/huge backlog block the scheduler thread
# indefinitely. Whatever is left when the budget runs out resumes on
# tomorrow's firing, same resumability contract as
# _run_universe_detail_refresh.
_SUPPLY_BUDGET_SECONDS = 30 * 60


def _run_supply_links_refresh() -> None:
    """Daily, time-boxed: drains snapshot.pending_docs (rationale PDFs
    fetched by _run_rating_filings_poll or backfill_supply_links.py)
    through PDF-text extraction, the LLM-as-reader call, and loader writes.

    Three ways a doc leaves the queue for good (mark_extracted): its scrip
    code resolves to no Listing/Company (unmatched_scrip), its PDF has no
    extractable text (unextractable), or extraction+load succeeded
    (extracted). One way it stays pending for a retry on a later run: the
    LLM call returned nothing (llm_failed) -- a transient provider failure
    should not permanently drop a document that a later run might extract
    successfully.

    Any failure is logged, never raised, same as every other scheduler job.
    """
    import json

    from app.companies.supply_links import extract, loader
    from app.models import Company, Listing

    counts = {"extracted": 0, "unmatched_scrip": 0, "unextractable": 0, "llm_failed": 0}
    deadline = time.monotonic() + _SUPPLY_BUDGET_SECONDS

    session = SessionLocal()
    try:
        client = build_client(settings.groq_api_keys, settings.gemini_api_key or None)

        for pdf_path in supply_snapshot.pending_docs(supply_snapshot.DEFAULT_ROOT):
            if time.monotonic() >= deadline:
                break

            try:
                meta = json.loads(
                    supply_snapshot.meta_sidecar_path(pdf_path).read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                meta = {}
            try:
                source_url = supply_snapshot.url_sidecar_path(pdf_path).read_text(
                    encoding="utf-8"
                ).strip()
            except OSError:
                source_url = ""

            scrip_code = meta.get("scrip_code")
            listing = (
                session.query(Listing).filter(Listing.scrip_code == scrip_code).first()
                if scrip_code else None
            )
            company = (
                session.query(Company).filter(Company.id == listing.company_id).first()
                if listing is not None else None
            )
            if company is None:
                supply_snapshot.mark_extracted(pdf_path)
                counts["unmatched_scrip"] += 1
                continue

            text = extract.pdf_text(pdf_path)
            if text is None:
                supply_snapshot.mark_extracted(pdf_path)
                counts["unextractable"] += 1
                continue

            profile = extract.extract_profile(client, company.name, text)
            if profile is None:
                counts["llm_failed"] += 1
                continue  # left pending -- retried on the next run

            as_of = _parse_news_date(meta.get("news_date")) or date.today()
            loader.apply_extraction(
                session, company, profile,
                source_url=source_url, source_agency=meta.get("agency") or "",
                as_of=as_of,
            )
            supply_snapshot.mark_extracted(pdf_path)
            counts["extracted"] += 1

        logger.info(
            "Supply links refresh: extracted=%s unmatched_scrip=%s "
            "unextractable=%s llm_failed=%s",
            counts["extracted"], counts["unmatched_scrip"],
            counts["unextractable"], counts["llm_failed"],
        )
    except Exception:
        logger.exception("Supply links refresh failed")
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
        # Daily, not monthly. BSE throttles us to roughly half throughput,
        # so the pass no longer fits one sitting -- it takes a 45-minute
        # budget each day and resumes into the same directory until done,
        # then does nothing until that snapshot is 30 days old.
        hours=24,
        # Never at boot: a restart loop would hammer BSE.
        next_run_time=datetime.now(timezone.utc) + timedelta(hours=6),
        id="universe_detail_refresh",
    )
    scheduler.add_job(
        _run_event_volatility_refresh,
        trigger="interval",
        hours=24,
        # DB-only and cheap, but still not at boot -- a crash loop should
        # not be re-aggregating tables.
        next_run_time=datetime.now(timezone.utc) + timedelta(minutes=30),
        id="event_volatility_refresh",
    )
    scheduler.add_job(
        _run_rating_filings_poll,
        trigger="interval",
        hours=24,
        # Never at boot -- give the app a chance to settle first.
        next_run_time=datetime.now(timezone.utc) + timedelta(minutes=45),
        id="rating_filings_poll",
    )
    scheduler.add_job(
        _run_supply_links_refresh,
        trigger="interval",
        hours=24,
        # Fires after the poll above has had a chance to land today's docs.
        next_run_time=datetime.now(timezone.utc) + timedelta(hours=1),
        id="supply_links_refresh",
    )
    scheduler.start()
    _scheduler = scheduler
