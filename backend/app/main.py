from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import init_db
from app.routers import alerts, articles
from app.scheduler import start_scheduler

app = FastAPI(title="NewsFlo")

app.include_router(articles.router)
app.include_router(alerts.router)

init_db()

if settings.enable_scheduler:
    start_scheduler()

app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
