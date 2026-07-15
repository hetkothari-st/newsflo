import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# Without this, every logger.info/logger.exception call in the app (e.g. the
# scheduler's per-poll-cycle success/failure logging) is silently dropped --
# Python's root logger defaults to WARNING, so INFO-level messages never
# reach any handler. Confirmed the hard way in production: diagnosing the
# ingestion pipeline required inferring behavior from side effects (alert
# counts, HTTP request logs) because our own log lines were invisible.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from app.config import settings
from app.db import SessionLocal, init_db
from app.models import Company
from app.prices.kite_ws_client import run_hub_client
from app.prices.live_price import LIVE_PRICE_CACHE
from app.routers import alerts, articles, auth, categories, companies, holdings, translation, watchlist, ws
from app.scheduler import start_scheduler
from app.ws.manager import manager

app = FastAPI(title="NewsFlo")

app.include_router(articles.router)
app.include_router(alerts.router)
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


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
