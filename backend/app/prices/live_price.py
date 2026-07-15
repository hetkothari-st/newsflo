from datetime import datetime, timezone

# Shared, process-wide cache written by kite_ws_client.run_hub_client and
# read by the /live-price endpoint -- a plain module-level dict (like
# app/ws/manager.py's `manager` singleton) rather than a class instance,
# since there is exactly one cache for the whole process.
LIVE_PRICE_CACHE: dict[int, dict] = {}


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def get_previous_close(points: list[dict]) -> float | None:
    """The most recent close strictly before today, from a list of
    ``{"date": "YYYY-MM-DD", "close": float}`` points (as returned by
    ``fetch_price_series``). Falls back to the single most recent point if
    every point is dated today or later (e.g. a short lookback window
    fetched right at/after today's first print). ``None`` for an empty list.
    """
    if not points:
        return None
    today = _today()
    before_today = [p for p in points if p["date"] < today]
    if before_today:
        return before_today[-1]["close"]
    return points[-1]["close"]


def compute_change_pct(ltp: float, previous_close: float | None) -> float | None:
    """Percent change of ``ltp`` versus ``previous_close``. ``None`` if
    there's no previous close to compare against, or it's zero (division
    would be undefined/meaningless)."""
    if not previous_close:
        return None
    return (ltp - previous_close) / previous_close * 100
