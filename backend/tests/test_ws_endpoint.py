from fastapi.testclient import TestClient

from app.main import app
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
