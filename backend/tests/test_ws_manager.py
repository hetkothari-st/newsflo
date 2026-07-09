import asyncio

from app.ws.manager import ConnectionManager


class FakeWebSocket:
    """Minimal stand-in for starlette.WebSocket — records accept/send calls."""

    def __init__(self, fail_on_send: bool = False):
        self.accepted = False
        self.sent: list = []
        self.fail_on_send = fail_on_send

    async def accept(self):
        self.accepted = True

    async def send_json(self, message):
        if self.fail_on_send:
            raise RuntimeError("connection gone")
        self.sent.append(message)


def test_connect_accepts_and_registers():
    manager = ConnectionManager()
    ws = FakeWebSocket()

    asyncio.run(manager.connect(ws))

    assert ws.accepted is True
    assert ws in manager.active_connections


def test_disconnect_removes_connection():
    manager = ConnectionManager()
    ws = FakeWebSocket()
    asyncio.run(manager.connect(ws))

    manager.disconnect(ws)

    assert ws not in manager.active_connections


def test_disconnect_is_safe_when_not_present():
    manager = ConnectionManager()
    ws = FakeWebSocket()

    # Never connected — must not raise.
    manager.disconnect(ws)

    assert ws not in manager.active_connections


def test_broadcast_sends_to_all_connections():
    manager = ConnectionManager()
    a, b = FakeWebSocket(), FakeWebSocket()
    asyncio.run(manager.connect(a))
    asyncio.run(manager.connect(b))

    asyncio.run(manager.broadcast({"hello": "world"}))

    assert a.sent == [{"hello": "world"}]
    assert b.sent == [{"hello": "world"}]


def test_broadcast_drops_failed_connection_and_continues():
    manager = ConnectionManager()
    good, bad = FakeWebSocket(), FakeWebSocket(fail_on_send=True)
    asyncio.run(manager.connect(good))
    asyncio.run(manager.connect(bad))

    asyncio.run(manager.broadcast({"x": 1}))

    assert good.sent == [{"x": 1}]        # the healthy one still received it
    assert bad not in manager.active_connections  # the dead one was dropped
    assert good in manager.active_connections


def test_broadcast_sync_is_noop_without_loop():
    manager = ConnectionManager()

    # No captured loop and no connections — must return silently, never raise.
    manager.broadcast_sync({"x": 1})


def test_broadcast_sync_is_noop_without_connections():
    manager = ConnectionManager()
    loop = asyncio.new_event_loop()
    manager.loop = loop

    # Loop set but no connections -> still a no-op, no crash.
    manager.broadcast_sync({"x": 1})

    loop.close()
