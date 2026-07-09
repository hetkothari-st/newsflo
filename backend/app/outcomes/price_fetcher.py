from datetime import datetime, timedelta

import yfinance as yf


def fetch_price_change_pct(ticker: str, start_date: datetime, horizon_days: int) -> float | None:
    """Return the % price change for ``ticker`` over ``horizon_days`` starting at
    ``start_date``, or ``None`` if data is unavailable or the fetch fails.

    A ``None`` result means "skip, retry on the next scheduled run" — a single
    ticker failure never blocks the rest of a batch (see spec error handling).
    """
    try:
        history = yf.Ticker(ticker).history(
            start=start_date.date(),
            end=(start_date + timedelta(days=horizon_days + 1)).date(),
        )
        close = history["Close"]
        if len(close) < 2:
            return None
        first = close.iloc[0]
        last = close.iloc[-1]
        return float((last - first) / first * 100)
    except Exception:
        return None
