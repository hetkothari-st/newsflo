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


def _schema_version_status() -> bool | None:
    """Compare the DB's alembic_version to the code's own alembic head(s).

    Returns True (schema at head), False (schema is DEFINITELY behind --
    a real revision mismatch), or None if it could not be determined at all
    (no alembic_version table -- a bare dev DB predating Alembic -- or the
    check itself failed, e.g. DB unreachable). None is deliberately treated
    as "unknown", never as "behind": an undeterminable check must not by
    itself block anything, only a confirmed mismatch is grounds for that
    (see _maybe_start_scheduler below).

    Migrations are executed by backend/tools/migrate_on_boot.py, which the
    Dockerfile runs before uvicorn -- this function is the boot-time
    tripwire that notices when that did not happen (a dev running uvicorn
    by hand, a deploy whose CMD was overridden, or a stale container image
    whose code is older than the DB it is pointed at)."""
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
                return None
            current = {
                row[0] for row in conn.exec_driver_sql("SELECT version_num FROM alembic_version")
            }
        return current == heads
    except Exception:
        return None


def _warn_if_schema_not_at_head() -> None:
    """Warn (never block) when the DB is not at Alembic head. Deliberately
    a warning at this call site: local development has always run on a bare
    `init_db()` DB and must keep starting, and an undeterminable check must
    never itself be the reason the app cannot boot. The scheduler gets a
    stricter, blocking version of this same check -- see
    _maybe_start_scheduler."""
    log = logging.getLogger(__name__)
    status = _schema_version_status()
    if status is None:
        log.warning(
            "[schema] could not verify alembic revision (or database is not "
            "alembic-managed) -- run `python tools/migrate_on_boot.py`; "
            "columns added by migrations may be missing")
    elif status is False:
        log.warning(
            "[schema] database is not at alembic head -- run "
            "`python tools/migrate_on_boot.py`; columns added by newer "
            "migrations may be missing")


_warn_if_schema_not_at_head()


def _assert_api_cannot_write_company_impact() -> None:
    """V5 Task 0.3: the API process must not be able to write the canonical
    `company_impact` table. Only app.core.impact_writer holds that
    capability, and only inside a reducer session.

    Warns rather than blocks when the check itself cannot run (a DB without
    the V5 tables yet, or a backend where the guarantee comes from real role
    privileges instead) -- but RAISES if this process genuinely holds the
    reducer capability at boot, which would mean the single-writer guarantee
    is already gone."""
    from app.core.impact_writer import (
        ReducerPrivilegeError, assert_cannot_write_company_impact,
    )
    from app.db import SessionLocal

    log = logging.getLogger(__name__)
    session = SessionLocal()
    try:
        assert_cannot_write_company_impact(session)
    except ReducerPrivilegeError:
        raise
    except Exception as exc:                    # noqa: BLE001 -- see docstring
        log.warning("[v5] could not verify company_impact write privileges: %s", exc)
    finally:
        session.close()


_assert_api_cannot_write_company_impact()


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


def _maybe_start_scheduler() -> None:
    """Gate for starting the scheduler (blueprint §26: "incompatible app/
    schema versions should fail fast where practical" / "no legacy worker
    may mutate current gated output").

    Even with ENABLE_SCHEDULER on, a database that is CONFIRMED behind the
    running code's alembic head must never run the scheduled analysis/
    refinement loop: a stale binary is exactly the shape of the real
    incident this guards against (alert 20, OIL.NS -- a stale pre-V4
    worker's refinement sweep flipped `direction` and nulled `rationale` on
    an already-gated AlertCompany row, because that worker's code predated
    the gate_state/display_tier columns and their immunity checks in
    app.pipeline and app.analysis.refinement). The API keeps serving on a
    stale schema (read paths degrade gracefully on missing columns/rows
    already), only the writer loop is refused.

    Extracted to its own function (same pattern as
    _start_hub_client_if_configured) so it is directly unit-testable via
    monkeypatch + call, without reloading this whole module. The
    `if settings.enable_scheduler:` test below must stay a bare attribute
    access -- tests/test_no_real_anthropic_guard.py's AST-based guard test
    requires every start_scheduler() call to be a syntactic descendant of
    exactly that shape.
    """
    if settings.enable_scheduler:
        log = logging.getLogger(__name__)
        if _schema_version_status() is False:
            log.critical(
                "[schema] REFUSING to start scheduler: database schema is "
                "behind this process's alembic head (stale binary or a "
                "missed migration) -- a stale worker must never mutate "
                "gated V4 rows (blueprint §26). The API will keep serving; "
                "run `python tools/migrate_on_boot.py` and restart this "
                "process to re-enable the scheduler.")
        else:
            start_scheduler()


_maybe_start_scheduler()


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
