from fastapi.testclient import TestClient

import app.pipeline as pipeline_module
from app.analysis.schemas import AnalysisOutput, CompanyMention
from app.main import app
from app.models import Article, Company
from app.pipeline import process_new_articles
from app.routers.articles import get_db
from app.ws.manager import manager


def test_websocket_connect_registers_then_unregisters_on_close():
    client = TestClient(app)

    with client.websocket_connect("/ws/alerts"):
        assert len(manager.active_connections) == 1

    # Leaving the context closes the socket -> handler catches
    # WebSocketDisconnect -> the connection is unregistered.
    assert len(manager.active_connections) == 0


def test_startup_event_captures_running_loop():
    # Entering the TestClient context runs the ASGI lifespan, firing the
    # startup event, which captures the portal's running loop for threadsafe
    # broadcasts.
    with TestClient(app):
        assert manager.loop is not None


def test_pipeline_broadcasts_new_alert_to_connected_client(db_session, monkeypatch):
    app.dependency_overrides[get_db] = lambda: db_session

    db_session.add(Company(
        ticker="RELIANCE.NS", name="Reliance Industries",
        sector="oil_gas", index_tier="NIFTY50", market_cap=1_800_000.0,
    ))
    db_session.commit()
    db_session.add(Article(
        source="test", url="https://example.com/ws-live",
        title="US strikes Iran oil export sites", content="crude oil markets react",
    ))
    db_session.commit()

    fake_output = AnalysisOutput(
        category="oil_energy",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)

    # Entering the TestClient context runs startup (captures manager.loop);
    # the nested websocket_connect registers a live client.
    with TestClient(app) as client:
        with client.websocket_connect("/ws/alerts") as websocket:
            created = process_new_articles(db_session, claude_client=object())
            assert created == 1
            payload = websocket.receive_json()

    assert payload["article"]["title"] == "US strikes Iran oil export sites"
    assert payload["category"] == "oil_energy"
    assert payload["companies"][0]["ticker"] == "RELIANCE.NS"
    assert payload["companies"][0]["direction"] == "bullish"
    assert payload["companies"][0]["confidence"] == "llm_estimate"
    # The pipeline has no per-viewer context at broadcast time, so the payload
    # intentionally omits in_my_holdings (the frontend defaults it to false).
    assert "in_my_holdings" not in payload["companies"][0]

    app.dependency_overrides.clear()
