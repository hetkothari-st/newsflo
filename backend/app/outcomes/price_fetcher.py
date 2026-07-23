import math
from datetime import datetime, timedelta

import pandas as pd
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


def fetch_cumulative_excess_return(
    ticker: str, benchmark_ticker: str, event_date: datetime,
    days_before: int = 1, days_after: int = 3,
) -> float | None:
    """Cumulative Abnormal Return (docs/NEWS_IMPACT_APP_SPEC.md §4.6): the
    sum of (ticker daily return - benchmark daily return) over trading
    days [event_date - days_before .. event_date + days_after] (default
    -1..+3, 5 trading days -- 6 closes needed since each daily return
    requires the prior day's close too). Returns a percentage (matching
    MarketMove.excess_move_pct's own convention: 1.5 means 1.5%, not
    0.015). Returns None -- "not ready yet, retry on the next scheduled
    run" -- if the market hasn't yet traded far enough past event_date
    to fill the whole window, or if data is unavailable/the fetch fails.
    Same "never raise, degrade to None" contract as
    fetch_price_change_pct in this same module.
    """
    try:
        start = event_date - timedelta(days=14)
        end = event_date + timedelta(days=14)

        ticker_closes = yf.Ticker(ticker).history(start=start.date(), end=end.date())["Close"]
        if len(ticker_closes) == 0:
            return None
        # yfinance returns a tz-aware DatetimeIndex for NSE tickers (localized
        # to Asia/Kolkata) -- comparing that directly against a tz-naive
        # Timestamp raises TypeError, which the bare except below would
        # silently swallow into "None", making this function unconditionally
        # return None against real data while every mocked (tz-naive) test
        # fixture kept passing. Normalize to tz-naive before any comparison.
        if ticker_closes.index.tz is not None:
            ticker_closes.index = ticker_closes.index.tz_localize(None)

        event_ts = pd.Timestamp(event_date.date())
        on_or_after = ticker_closes.index[ticker_closes.index >= event_ts]
        if len(on_or_after) == 0:
            return None
        day0_pos = ticker_closes.index.get_loc(on_or_after[0])

        first_pos = day0_pos - days_before - 1
        last_pos = day0_pos + days_after
        if first_pos < 0 or last_pos >= len(ticker_closes):
            return None

        window_dates = ticker_closes.index[first_pos:last_pos + 1]
        window_ticker_closes = ticker_closes.iloc[first_pos:last_pos + 1]

        benchmark_closes = yf.Ticker(benchmark_ticker).history(start=start.date(), end=end.date())["Close"]
        if benchmark_closes.index.tz is not None:
            benchmark_closes.index = benchmark_closes.index.tz_localize(None)
        benchmark_by_date = {
            ts.date(): float(v) for ts, v in benchmark_closes.items() if math.isfinite(float(v))
        }

        cumulative_excess = 0.0
        for i in range(1, len(window_dates)):
            prev_close = float(window_ticker_closes.iloc[i - 1])
            curr_close = float(window_ticker_closes.iloc[i])
            if prev_close == 0 or not math.isfinite(prev_close) or not math.isfinite(curr_close):
                return None
            ticker_return = curr_close / prev_close - 1

            prev_date = window_dates[i - 1].date()
            curr_date = window_dates[i].date()
            if prev_date not in benchmark_by_date or curr_date not in benchmark_by_date:
                return None
            benchmark_prev = benchmark_by_date[prev_date]
            benchmark_curr = benchmark_by_date[curr_date]
            if benchmark_prev == 0:
                return None
            benchmark_return = benchmark_curr / benchmark_prev - 1

            cumulative_excess += (ticker_return - benchmark_return) * 100

        return cumulative_excess
    except Exception:
        return None
