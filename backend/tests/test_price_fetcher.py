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
