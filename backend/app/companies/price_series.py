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
