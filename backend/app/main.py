from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.db import init_db
from app.routers import alerts, articles

app = FastAPI(title="NewsFlo")

app.include_router(articles.router)
app.include_router(alerts.router)

init_db()

app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
