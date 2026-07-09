"""Dev-only demo: run the NewsFlo backend and push one live alert on demand.

Not part of the test suite and not imported by the app. It starts uvicorn in a
background thread so the WebSocket server and the pipeline share ONE process
(therefore one ConnectionManager instance and one captured event loop). When you
press Enter it seeds an article and runs the pipeline, which broadcasts the new
alert to every browser connected to /ws/alerts — no page refresh required.

Usage (from the backend/ directory, so `app` is importable):
    .venv/Scripts/python demo_push.py
Then open the frontend (npm run dev -> http://localhost:5173) in a browser.
"""
import threading
import time

import uvicorn

import app.pipeline as pipeline_module
from app.analysis.schemas import AnalysisOutput, CompanyMention
from app.db import SessionLocal, init_db
from app.models import Article, Company


def _seed_company() -> None:
    session = SessionLocal()
    try:
        if session.query(Company).filter_by(ticker="RELIANCE.NS").one_or_none() is None:
            session.add(Company(
                ticker="RELIANCE.NS", name="Reliance Industries",
                sector="oil_gas", index_tier="NIFTY50", market_cap=1_800_000.0,
            ))
            session.commit()
    finally:
        session.close()


def _fake_analysis(client, title, content):
    return AnalysisOutput(
        category="oil_energy",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0,
            rationale="Top refiner benefits from a crude price spike.",
        )],
    )


def _push_one_alert() -> None:
    # Same monkeypatch pattern as the pipeline tests — no real Claude call.
    pipeline_module.analyze_article = _fake_analysis
    session = SessionLocal()
    try:
        session.add(Article(
            source="demo", url=f"https://example.com/demo-{int(time.time())}",
            title="US strikes Iran oil export sites", content="Crude oil markets react sharply.",
        ))
        session.commit()
        created = pipeline_module.process_new_articles(session, claude_client=object())
        print(f"Pushed {created} alert(s) to connected clients.")
    finally:
        session.close()


def main() -> None:
    init_db()
    _seed_company()
    config = uvicorn.Config("app.main:app", host="127.0.0.1", port=8000, log_level="info")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    time.sleep(2)  # let the server start and its startup event capture the loop
    print("Backend running on http://127.0.0.1:8000")
    print("Open http://localhost:5173, then press Enter here to push a live alert (Ctrl+C to quit).")
    try:
        while True:
            input()
            _push_one_alert()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
