import math
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
        first = float(close.iloc[0])
        last = float(close.iloc[-1])
        # yfinance occasionally returns a zero or NaN close for an illiquid/
        # foreign ticker on a given day -- dividing by that produced a NaN
        # that silently made it all the way into the API response (Starlette
        # can't JSON-encode NaN, 500ing the whole alerts feed on the first
        # affected row). Treat it the same as "no data" rather than letting
        # a bad upstream value propagate.
        if first == 0 or not math.isfinite(first) or not math.isfinite(last):
            return None
        pct = (last - first) / first * 100
        return pct if math.isfinite(pct) else None
    except Exception:
        return None
