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
    alerts, articles, auth, calendar, categories, companies, feed_v2, holdings, stock_deep_dive, translation,
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
app.include_router(feed_v2.router)
app.include_router(calendar.router)
app.include_router(auth.router)
app.include_router(holdings.router)
app.include_router(companies.router)
app.include_router(categories.router)
app.include_router(watchlist.router)
app.include_router(translation.router)
app.include_router(ws.router)

# Holds a strong reference to the background hub-client task for the app's
# lifetime -- asyncio's event loop only keeps a *weak* reference to tasks, so
# an unreferenced task is eligible for garbage collection mid-flight.
_hub_task: asyncio.Task | None = None

init_db()

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
    /nonexistent.js still 404s normally)."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and "." not in path.rsplit("/", 1)[-1]:
                return await super().get_response("index.html", scope)
            raise


app.mount("/", SPAStaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
