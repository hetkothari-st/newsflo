from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routers import alerts, articles

app = FastAPI(title="NewsFlo")

app.include_router(articles.router)
app.include_router(alerts.router)

app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
