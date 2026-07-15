import asyncio
import json
import struct

from app.prices.kite_ws_client import handle_message, run_hub_client


def _ltp_message(instrument_token: int, ltp_rupees: float) -> bytes:
    packet = struct.pack(">Ii", instrument_token, round(ltp_rupees * 100))
    return struct.pack(">H", 1) + struct.pack(">H", len(packet)) + packet


def test_handle_message_updates_cache_for_binary_tick():
    cache: dict[int, dict] = {}

    handle_message(_ltp_message(738561, 2500.50), cache)

    assert cache[738561]["ltp"] == 2500.50


def test_handle_message_ignores_text_frames():
    cache: dict[int, dict] = {}

    handle_message(json.dumps({"type": "auth_success"}), cache)

    assert cache == {}


class _FakeWebSocket:
    def __init__(self, messages):
        self._messages = messages
        self.sent = []

    async def send(self, data):
        self.sent.append(data)

    def __aiter__(self):
        return self._iter_messages()

    async def _iter_messages(self):
        for message in self._messages:
            yield message


def _fake_connect(messages_per_connection):
    """Build a fake replacement for ``websockets.connect`` -- an async
    generator function yielding one FakeWebSocket per entry in
    ``messages_per_connection``, exactly matching how ``async for websocket
    in websockets.connect(url):`` iterates real reconnecting connections."""
    async def connect(url):
        for messages in messages_per_connection:
            yield _FakeWebSocket(messages)
    return connect


def test_run_hub_client_subscribes_and_updates_cache():
    cache: dict[int, dict] = {}
    fake_connect = _fake_connect([[_ltp_message(738561, 2500.50)]])

    asyncio.run(run_hub_client("wss://fake-hub", [738561], cache, connect=fake_connect))

    assert cache[738561]["ltp"] == 2500.50


def test_run_hub_client_sends_subscribe_message_on_connect():
    cache: dict[int, dict] = {}
    sent_messages = []

    async def connect(url):
        ws = _FakeWebSocket([])
        yield ws
        sent_messages.extend(ws.sent)

    asyncio.run(run_hub_client("wss://fake-hub", [738561, 5633], cache, connect=connect))

    assert json.loads(sent_messages[0]) == {"a": "subscribe", "v": [738561, 5633]}


def test_run_hub_client_survives_a_connection_that_raises():
    cache: dict[int, dict] = {}

    async def connect(url):
        class _BoomWebSocket:
            async def send(self, data):
                raise ConnectionResetError("boom")

            def __aiter__(self):
                async def _gen():
                    return
                    yield  # pragma: no cover - never reached
                return _gen()
        yield _BoomWebSocket()
        yield _FakeWebSocket([_ltp_message(5633, 150.25)])

    asyncio.run(run_hub_client("wss://fake-hub", [738561], cache, connect=connect))

    assert cache[5633]["ltp"] == 150.25
