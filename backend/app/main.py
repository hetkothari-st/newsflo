import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

# Without this, every logger.info/logger.exception call in the app (e.g. the
# scheduler's per-poll-cycle success/failure logging) is silently dropped --
# Python's root logger defaults to WARNING, so INFO-level messages never
# reach any handler. Confirmed the hard way in production: diagnosing the
# ingestion pipeline required inferring behavior from side effects (alert
# counts, HTTP request logs) because our own log lines were invisible.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# Must run right after basicConfig, before any request-logging call happens
# -- see app/log_redaction.py's own docstring for why this exists (a real
# API key was visible in plaintext in production logs otherwise).
from app.log_redaction import RedactSecretsFilter  # noqa: E402

for _handler in logging.getLogger().handlers:
    _handler.addFilter(RedactSecretsFilter())

from app.config import settings
from app.db import SessionLocal, init_db
from app.models import Company
from app.prices.kite_ws_client import run_hub_client
from app.prices.live_price import LIVE_PRICE_CACHE
from app.routers import (
    alerts, articles, auth, calendar, car_review, categories, companies, feed_v2, holdings,
    internal_audit, portfolio_connect, pulse_live, source_health, stock_deep_dive, translation,
    watchlist, ws,
)
from app.scheduler import start_scheduler
from app.ws.manager import manager

app = FastAPI(title="NewsFlo")

app.include_router(articles.router)
app.include_router(alerts.router)
# stock_deep_dive.router must be included before feed_v2.router: feed_v2 has a
# catch-all GET /{alert_id} under the same "/api/feed-v2" prefix, which would
# otherwise intercept stock_deep_dive's single-segment "/directory" route
# (Starlette matches routes in registration order, not by specificity).
app.include_router(stock_deep_dive.router)
app.include_router(car_review.router)
app.include_router(source_health.router)
app.include_router(pulse_live.router)
app.include_router(feed_v2.router)
app.include_router(calendar.router)
app.include_router(auth.router)
app.include_router(holdings.router)
app.include_router(portfolio_connect.router)
app.include_router(companies.router)
app.include_router(categories.router)
app.include_router(watchlist.router)
app.include_router(translation.router)
app.include_router(internal_audit.router)
app.include_router(ws.router)

# Holds a strong reference to the background hub-client task for the app's
# lifetime -- asyncio's event loop only keeps a *weak* reference to tasks, so
# an unreferenced task is eligible for garbage collection mid-flight.
_hub_task: asyncio.Task | None = None

init_db()


def _warn_if_schema_not_at_head() -> None:
    """Warn (never block) when the DB is not at Alembic head.

    Migrations are executed by backend/tools/migrate_on_boot.py, which the
    Dockerfile runs before uvicorn -- this is only the tripwire that says
    so out loud if it did not happen (a dev running uvicorn by hand, or a
    deploy whose CMD was overridden). It is deliberately a warning: local
    development has always run on a bare `init_db()` DB and must keep
    starting. Any failure to even determine the revision is itself only
    logged -- a schema-version check must never be the reason the app
    cannot boot."""
    log = logging.getLogger(__name__)
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from sqlalchemy import inspect as sa_inspect

        from app.db import engine

        backend_dir = Path(__file__).resolve().parents[1]
        script = ScriptDirectory.from_config(Config(str(backend_dir / "alembic.ini")))
        heads = set(script.get_heads())
        with engine.connect() as conn:
            if "alembic_version" not in sa_inspect(conn).get_table_names():
                log.warning(
                    "[schema] database is not alembic-managed (no alembic_version "
                    "table) -- run `python tools/migrate_on_boot.py`; columns added "
                    "by migrations 0002+ may be missing")
                return
            current = {
                row[0] for row in conn.exec_driver_sql("SELECT version_num FROM alembic_version")
            }
        if current != heads:
            log.warning(
                "[schema] database is at alembic revision %s, head is %s -- run "
                "`python tools/migrate_on_boot.py`; columns added by newer "
                "migrations may be missing",
                sorted(current) or ["<none>"], sorted(heads))
    except Exception:
        log.warning("[schema] could not verify alembic revision", exc_info=True)


_warn_if_schema_not_at_head()


def _seed_exposure_registry() -> None:
    """Materialize archetype-implied exposures once per knowledge-registry
    version (2026-08-12 fix: seed_company_exposures had no production
    caller, leaving company_exposures empty and the archetype eligibility
    gate a silent no-op). Never blocks startup on failure."""
    db = SessionLocal()
    try:
        from app.analysis.impact_graph.knowledge import ensure_exposure_seed
        written = ensure_exposure_seed(db)
        if written:
            logging.getLogger(__name__).info(
                "exposure registry seeded: %s company_exposures rows", written)
    except Exception:
        logging.getLogger(__name__).exception("exposure registry seed failed; continuing")
    finally:
        db.close()


_seed_exposure_registry()

if settings.enable_scheduler:
    start_scheduler()


def _start_hub_client_if_configured() -> None:
    """Kick off the persistent Zerodha hub client if a hub URL is
    configured. Extracted from the startup event so it can be unit-tested
    without spinning up the whole ASGI lifespan."""
    if not settings.zerodha_hub_url:
        return
    global _hub_task
    db = SessionLocal()
    try:
        instrument_tokens = [
            row[0] for row in
            db.query(Company.instrument_token).filter(Company.instrument_token.isnot(None)).all()
        ]
    finally:
        db.close()
    _hub_task = asyncio.create_task(run_hub_client(settings.zerodha_hub_url, instrument_tokens, LIVE_PRICE_CACHE))


@app.on_event("startup")
async def _capture_event_loop() -> None:
    # Capture the running loop so the synchronous pipeline can schedule async
    # broadcasts onto it from a worker thread via run_coroutine_threadsafe.
    manager.loop = asyncio.get_running_loop()
    _start_hub_client_if_configured()


class SPAStaticFiles(StaticFiles):
    """StaticFiles(html=True) only auto-serves index.html for a directory
    request -- a client-side route with no matching file on disk (e.g.
    /alerts/262/charts, /company/22) 404s instead of loading the SPA shell.
    Confirmed in production: any deep link, bookmark, or browser refresh on
    a non-root route returned a raw 404. Fall back to index.html for any
    404 whose path has no file extension (a real missing asset like
    /nonexistent.js still 404s normally).

    index.html (and every SPA-fallback response) is served with
    Cache-Control: no-cache. Without it, browsers heuristically cache the
    shell HTML, which pins users to a stale hashed JS bundle across
    deploys -- confirmed in production: new deploys were invisible until a
    hard refresh. no-cache still allows ETag revalidation (304s), so the
    cost is one conditional request per load. Hashed /assets/* files stay
    heuristically cacheable -- their names change on every content change."""

    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and "." not in path.rsplit("/", 1)[-1]:
                response = await super().get_response("index.html", scope)
            else:
                raise
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/", SPAStaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
