import pandas as pd
import pytest

from app.companies import price_series


class FakeTicker:
    def __init__(self, df):
        self._df = df

    def history(self, period, interval):
        return self._df


def test_fetch_price_series_returns_date_close_points(monkeypatch):
    df = pd.DataFrame(
        {"Close": [100.0, 105.0, 103.0]},
        index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05"]),
    )
    monkeypatch.setattr(price_series.yf, "Ticker", lambda ticker: FakeTicker(df))

    result = price_series.fetch_price_series("RELIANCE.NS", period="1mo")

    assert result == [
        {"date": "2026-01-01", "close": 100.0},
        {"date": "2026-01-02", "close": 105.0},
        {"date": "2026-01-05", "close": 103.0},
    ]


def test_fetch_price_series_drops_nan_days(monkeypatch):
    # yfinance can report NaN for an illiquid ticker on a given day -- must
    # be filtered rather than propagated, both because NaN isn't valid JSON
    # and because callers treat the *last* point as "current price".
    df = pd.DataFrame(
        {"Close": [100.0, float("nan"), 103.0]},
        index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05"]),
    )
    monkeypatch.setattr(price_series.yf, "Ticker", lambda ticker: FakeTicker(df))

    result = price_series.fetch_price_series("RELIANCE.NS", period="1mo")

    assert result == [
        {"date": "2026-01-01", "close": 100.0},
        {"date": "2026-01-05", "close": 103.0},
    ]


def test_fetch_price_series_returns_none_when_every_day_is_nan(monkeypatch):
    df = pd.DataFrame(
        {"Close": [float("nan"), float("nan")]},
        index=pd.to_datetime(["2026-01-01", "2026-01-02"]),
    )
    monkeypatch.setattr(price_series.yf, "Ticker", lambda ticker: FakeTicker(df))

    assert price_series.fetch_price_series("RELIANCE.NS", period="1mo") is None


def test_fetch_price_series_returns_none_for_empty(monkeypatch):
    df = pd.DataFrame({"Close": []})
    monkeypatch.setattr(price_series.yf, "Ticker", lambda ticker: FakeTicker(df))

    assert price_series.fetch_price_series("RELIANCE.NS", period="1mo") is None


def test_fetch_price_series_returns_none_on_exception(monkeypatch):
    def boom(ticker):
        raise RuntimeError("network down")

    monkeypatch.setattr(price_series.yf, "Ticker", boom)

    assert price_series.fetch_price_series("RELIANCE.NS", period="1mo") is None
