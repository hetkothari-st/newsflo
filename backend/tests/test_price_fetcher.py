from datetime import datetime, timezone

import pandas as pd
import pytest

from app.outcomes import price_fetcher


class FakeTicker:
    def __init__(self, df):
        self._df = df

    def history(self, start, end):
        return self._df


def test_fetch_price_change_pct_computes_positive_move(monkeypatch):
    df = pd.DataFrame({"Close": [100.0, 105.0]})
    monkeypatch.setattr(price_fetcher.yf, "Ticker", lambda ticker: FakeTicker(df))

    result = price_fetcher.fetch_price_change_pct(
        "RELIANCE.NS", datetime(2026, 1, 1, tzinfo=timezone.utc), 1,
    )

    assert result == pytest.approx(5.0)


def test_fetch_price_change_pct_returns_none_for_empty(monkeypatch):
    df = pd.DataFrame({"Close": []})
    monkeypatch.setattr(price_fetcher.yf, "Ticker", lambda ticker: FakeTicker(df))

    result = price_fetcher.fetch_price_change_pct(
        "RELIANCE.NS", datetime(2026, 1, 1, tzinfo=timezone.utc), 3,
    )

    assert result is None


def test_fetch_price_change_pct_returns_none_for_zero_first_close(monkeypatch):
    # A zero (bad/missing data) first close previously produced NaN via
    # division by zero, which made it all the way into the JSON API
    # response and 500'd the whole alerts feed (Starlette can't encode
    # NaN). Must degrade to None like any other "no data" case instead.
    df = pd.DataFrame({"Close": [0.0, 105.0]})
    monkeypatch.setattr(price_fetcher.yf, "Ticker", lambda ticker: FakeTicker(df))

    result = price_fetcher.fetch_price_change_pct(
        "RELIANCE.NS", datetime(2026, 1, 1, tzinfo=timezone.utc), 1,
    )

    assert result is None


def test_fetch_price_change_pct_returns_none_for_nan_close(monkeypatch):
    df = pd.DataFrame({"Close": [float("nan"), 105.0]})
    monkeypatch.setattr(price_fetcher.yf, "Ticker", lambda ticker: FakeTicker(df))

    result = price_fetcher.fetch_price_change_pct(
        "RELIANCE.NS", datetime(2026, 1, 1, tzinfo=timezone.utc), 1,
    )

    assert result is None


def test_fetch_price_change_pct_returns_none_on_exception(monkeypatch):
    def boom(ticker):
        raise RuntimeError("network down")

    monkeypatch.setattr(price_fetcher.yf, "Ticker", boom)

    result = price_fetcher.fetch_price_change_pct(
        "RELIANCE.NS", datetime(2026, 1, 1, tzinfo=timezone.utc), 7,
    )

    assert result is None


def _history_df(dates, closes):
    return pd.DataFrame({"Close": closes}, index=pd.DatetimeIndex(dates))


def test_fetch_cumulative_excess_return_sums_daily_excess_over_window(monkeypatch):
    # 6 trading days needed for a -1..+3 window (5 daily returns): day-2
    # through day+3. Event date = day 0 = 2026-01-08.
    dates = ["2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09", "2026-01-12", "2026-01-13"]
    ticker_closes = [100.0, 101.0, 103.0, 104.03, 106.11, 107.17]  # +1%, +2%, +1%, +2%, +1%
    benchmark_closes = [200.0, 202.0, 204.02, 204.02, 204.02, 206.06]  # +1%, +1%, 0%, 0%, +1%

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, start=None, end=None):
            if self.symbol == "STOCK.NS":
                return _history_df(dates, ticker_closes)
            return _history_df(dates, benchmark_closes)

    monkeypatch.setattr(price_fetcher.yf, "Ticker", FakeTicker)

    result = price_fetcher.fetch_cumulative_excess_return(
        "STOCK.NS", "^BENCH", datetime(2026, 1, 8, tzinfo=timezone.utc),
    )

    # daily excess = ticker_return - benchmark_return for days -1,0,+1,+2,+3:
    # day-1: 1% - 1% = 0%% ; day0: ~1.98% - ~1% = ~0.98%% ; day+1: 1% - 0% = 1%%
    # day+2: ~2% - 0% = ~2%% ; day+3: ~1% - 1% = 0%%
    assert result is not None
    assert round(result, 1) == round(0.0 + 0.9803 + 1.0 + 1.9993 + 0.0, 1)


def test_fetch_cumulative_excess_return_returns_none_when_window_not_fully_traded_yet(monkeypatch):
    # Only 4 trading days available -- day+2 and day+3 haven't happened yet.
    dates = ["2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09"]
    closes = [100.0, 101.0, 103.0, 104.0]

    class FakeTicker:
        def __init__(self, symbol):
            pass

        def history(self, start=None, end=None):
            return _history_df(dates, closes)

    monkeypatch.setattr(price_fetcher.yf, "Ticker", FakeTicker)

    result = price_fetcher.fetch_cumulative_excess_return(
        "STOCK.NS", "^BENCH", datetime(2026, 1, 8, tzinfo=timezone.utc),
    )

    assert result is None


def test_fetch_cumulative_excess_return_returns_none_when_no_data(monkeypatch):
    class FakeTicker:
        def __init__(self, symbol):
            pass

        def history(self, start=None, end=None):
            return pd.DataFrame({"Close": []})

    monkeypatch.setattr(price_fetcher.yf, "Ticker", FakeTicker)

    result = price_fetcher.fetch_cumulative_excess_return(
        "STOCK.NS", "^BENCH", datetime(2026, 1, 8, tzinfo=timezone.utc),
    )

    assert result is None


def test_fetch_cumulative_excess_return_handles_tz_aware_index(monkeypatch):
    # Real yfinance returns a tz-aware DatetimeIndex for NSE tickers
    # (localized to Asia/Kolkata) -- comparing that directly against a
    # tz-naive event Timestamp raises TypeError, which the function's own
    # bare except previously swallowed into "None" unconditionally,
    # invisible to every other test here since _history_df's plain
    # pd.DatetimeIndex(dates) is tz-naive and never exercised this path.
    dates = ["2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09", "2026-01-12", "2026-01-13"]
    ticker_closes = [100.0, 101.0, 103.0, 104.03, 106.11, 107.17]
    benchmark_closes = [200.0, 202.0, 204.02, 204.02, 204.02, 206.06]

    def _tz_aware_history_df(dates, closes):
        index = pd.DatetimeIndex(dates).tz_localize("Asia/Kolkata")
        return pd.DataFrame({"Close": closes}, index=index)

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, start=None, end=None):
            if self.symbol == "STOCK.NS":
                return _tz_aware_history_df(dates, ticker_closes)
            return _tz_aware_history_df(dates, benchmark_closes)

    monkeypatch.setattr(price_fetcher.yf, "Ticker", FakeTicker)

    result = price_fetcher.fetch_cumulative_excess_return(
        "STOCK.NS", "^BENCH", datetime(2026, 1, 8, tzinfo=timezone.utc),
    )

    assert result is not None
    assert round(result, 1) == round(0.0 + 0.9803 + 1.0 + 1.9993 + 0.0, 1)


def test_fetch_cumulative_excess_return_returns_none_on_exception(monkeypatch):
    class FakeTicker:
        def __init__(self, symbol):
            raise RuntimeError("network error")

    monkeypatch.setattr(price_fetcher.yf, "Ticker", FakeTicker)

    result = price_fetcher.fetch_cumulative_excess_return(
        "STOCK.NS", "^BENCH", datetime(2026, 1, 8, tzinfo=timezone.utc),
    )

    assert result is None
