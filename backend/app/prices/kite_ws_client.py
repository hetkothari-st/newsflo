import json
import logging

import websockets

from app.models import utcnow
from app.prices.kite_ticks import decode_ticks, update_cache

logger = logging.getLogger(__name__)


def handle_message(message: str | bytes, cache: dict[int, dict]) -> None:
    """Route one incoming hub message: binary frames are Kite ticks (decoded
    and folded into ``cache``); text frames are the hub's own status
    messages (``auth_error``/``auth_success``) -- logged, not cached, since
    they carry no price data."""
    if not isinstance(message, bytes):
        logger.info("[kite-hub] status message: %s", message)
        return
    ticks = decode_ticks(message)
    update_cache(cache, ticks, utcnow())


async def run_hub_client(
    hub_url: str,
    instrument_tokens: list[int],
    cache: dict[int, dict],
    connect=websockets.connect,
) -> None:
    """Persistent client for the Zerodha tick-relay hub. Subscribes to every
    given instrument_token on each (re)connection and folds every incoming
    tick into ``cache``.

    ``connect`` defaults to the real ``websockets.connect``, whose reconnect
    behavior (``async for websocket in websockets.connect(url): ...``)
    already retries with backoff on disconnect -- this function relies on
    that built-in reconnect loop rather than implementing its own. Tests
    substitute a fake async-generator ``connect`` that yields a fixed
    sequence of fake connections instead of retrying forever.

    Any error on one connection (send failure, decode error, the hub
    closing) is caught and logged so the outer reconnect loop keeps going --
    a hub outage degrades the live-price feature, it never crashes the
    caller.
    """
    async for websocket in connect(hub_url):
        try:
            await websocket.send(json.dumps({"a": "subscribe", "v": instrument_tokens}))
            async for message in websocket:
                handle_message(message, cache)
        except Exception:
            logger.exception("[kite-hub] connection error, will reconnect")
            continue
