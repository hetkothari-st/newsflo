import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import init_db
from app.routers import alerts, articles, auth, holdings, ws
from app.scheduler import start_scheduler
from app.ws.manager import manager

app = FastAPI(title="NewsFlo")

app.include_router(articles.router)
app.include_router(alerts.router)
app.include_router(auth.router)
app.include_router(holdings.router)
app.include_router(ws.router)

init_db()

if settings.enable_scheduler:
    start_scheduler()


@app.on_event("startup")
async def _capture_event_loop() -> None:
    # Capture the running loop so the synchronous pipeline can schedule async
    # broadcasts onto it from a worker thread via run_coroutine_threadsafe.
    manager.loop = asyncio.get_running_loop()


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
