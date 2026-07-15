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

from app.config import settings
from app.db import init_db
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

init_db()

if settings.enable_scheduler:
    start_scheduler()


@app.on_event("startup")
async def _capture_event_loop() -> None:
    # Capture the running loop so the synchronous pipeline can schedule async
    # broadcasts onto it from a worker thread via run_coroutine_threadsafe.
    manager.loop = asyncio.get_running_loop()


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
