import math

import yfinance as yf


def fetch_price_series(ticker: str, period: str) -> list[dict] | None:
    """Return daily closing prices for ``ticker`` over ``period`` (a yfinance
    period string, e.g. "1mo"/"3mo"/"6mo"/"1y") as
    ``[{"date": "YYYY-MM-DD", "close": float}, ...]``, oldest first, or
    ``None`` if data is unavailable or the fetch fails.

    Same "never raise, degrade to None" contract as
    ``app.outcomes.price_fetcher.fetch_price_change_pct`` -- a live
    third-party call on the request path should never 500 the page it feeds.
    """
    try:
        history = yf.Ticker(ticker).history(period=period, interval="1d")
        close = history["Close"]
        if len(close) == 0:
            return None
        # Drop individual days yfinance reports as NaN (a gap/glitch, not a
        # real price) rather than propagating them -- both because the JSON
        # encoder can't serialize NaN (see price_fetcher.py's fix for the
        # matching bug) and because callers use the *last* point as "current
        # price" (financial_context.fetch_financial_snapshot), which must
        # never be a NaN masquerading as a real value.
        points = [
            {"date": index.strftime("%Y-%m-%d"), "close": float(value)}
            for index, value in close.items()
            if math.isfinite(float(value))
        ]
        return points or None
    except Exception:
        return None


def fetch_daily_bars(ticker: str, period: str) -> list[dict] | None:
    """Return daily close+volume bars for ``ticker`` over ``period`` as
    ``[{"date": "YYYY-MM-DD", "close": float, "volume": float}, ...]``,
    oldest first, or ``None`` if data is unavailable or the fetch fails.

    Volume-carrying sibling of ``fetch_price_series`` -- built for
    app.market.measure's excess-move/volume-multiple calculations (see
    docs/NEWS_IMPACT_APP_SPEC.md §3, §5). Same "never raise, degrade to
    None" contract. Only a non-finite CLOSE drops a day (matching
    fetch_price_series); a non-finite/absent volume on an otherwise-good
    day is recorded as 0.0 rather than dropping the close price the
    excess-move math needs.
    """
    try:
        history = yf.Ticker(ticker).history(period=period, interval="1d")
        close = history["Close"]
        if len(close) == 0:
            return None
        volume = history["Volume"] if "Volume" in history else None
        points = []
        for index, close_value in close.items():
            if not math.isfinite(float(close_value)):
                continue
            vol_value = 0.0
            if volume is not None:
                raw_vol = volume.get(index)
                if raw_vol is not None and math.isfinite(float(raw_vol)):
                    vol_value = float(raw_vol)
            points.append({
                "date": index.strftime("%Y-%m-%d"),
                "close": float(close_value),
                "volume": vol_value,
            })
        return points or None
    except Exception:
        return None
