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


class FakeTickerWithVolume:
    def __init__(self, df):
        self._df = df

    def history(self, period, interval):
        return self._df


def test_fetch_daily_bars_returns_date_close_volume_points(monkeypatch):
    df = pd.DataFrame(
        {"Close": [100.0, 105.0], "Volume": [1000.0, 2000.0]},
        index=pd.to_datetime(["2026-01-01", "2026-01-02"]),
    )
    monkeypatch.setattr(price_series.yf, "Ticker", lambda ticker: FakeTickerWithVolume(df))

    result = price_series.fetch_daily_bars("RELIANCE.NS", period="2mo")

    assert result == [
        {"date": "2026-01-01", "close": 100.0, "volume": 1000.0},
        {"date": "2026-01-02", "close": 105.0, "volume": 2000.0},
    ]


def test_fetch_daily_bars_drops_nan_close_days(monkeypatch):
    df = pd.DataFrame(
        {"Close": [100.0, float("nan")], "Volume": [1000.0, 2000.0]},
        index=pd.to_datetime(["2026-01-01", "2026-01-02"]),
    )
    monkeypatch.setattr(price_series.yf, "Ticker", lambda ticker: FakeTickerWithVolume(df))

    result = price_series.fetch_daily_bars("RELIANCE.NS", period="2mo")

    assert result == [{"date": "2026-01-01", "close": 100.0, "volume": 1000.0}]


def test_fetch_daily_bars_treats_nan_volume_as_zero_not_a_dropped_day(monkeypatch):
    # A close price with no reliable volume that day must still be usable
    # for excess-move math -- only a bad CLOSE should drop the day.
    df = pd.DataFrame(
        {"Close": [100.0, 105.0], "Volume": [1000.0, float("nan")]},
        index=pd.to_datetime(["2026-01-01", "2026-01-02"]),
    )
    monkeypatch.setattr(price_series.yf, "Ticker", lambda ticker: FakeTickerWithVolume(df))

    result = price_series.fetch_daily_bars("RELIANCE.NS", period="2mo")

    assert result == [
        {"date": "2026-01-01", "close": 100.0, "volume": 1000.0},
        {"date": "2026-01-02", "close": 105.0, "volume": 0.0},
    ]


def test_fetch_daily_bars_returns_none_for_empty(monkeypatch):
    df = pd.DataFrame({"Close": [], "Volume": []})
    monkeypatch.setattr(price_series.yf, "Ticker", lambda ticker: FakeTickerWithVolume(df))

    assert price_series.fetch_daily_bars("RELIANCE.NS", period="2mo") is None


def test_fetch_daily_bars_returns_none_on_exception(monkeypatch):
    def boom(ticker):
        raise RuntimeError("network down")

    monkeypatch.setattr(price_series.yf, "Ticker", boom)

    assert price_series.fetch_daily_bars("RELIANCE.NS", period="2mo") is None


def test_fetch_pe_ratio_returns_trailing_pe(monkeypatch):
    class FakeTicker:
        def __init__(self, ticker):
            self.info = {"trailingPE": 24.7}

    monkeypatch.setattr("yfinance.Ticker", FakeTicker)

    assert price_series.fetch_pe_ratio("RELIANCE.NS") == 24.7


def test_fetch_pe_ratio_returns_none_when_missing(monkeypatch):
    class FakeTicker:
        def __init__(self, ticker):
            self.info = {}

    monkeypatch.setattr("yfinance.Ticker", FakeTicker)

    assert price_series.fetch_pe_ratio("SOMETICKER.NS") is None


def test_fetch_pe_ratio_returns_none_on_non_finite_value(monkeypatch):
    class FakeTicker:
        def __init__(self, ticker):
            self.info = {"trailingPE": float("nan")}

    monkeypatch.setattr("yfinance.Ticker", FakeTicker)

    assert price_series.fetch_pe_ratio("SOMETICKER.NS") is None


def test_fetch_pe_ratio_returns_none_on_exception(monkeypatch):
    class FakeTicker:
        def __init__(self, ticker):
            raise RuntimeError("network error")

    monkeypatch.setattr("yfinance.Ticker", FakeTicker)

    assert price_series.fetch_pe_ratio("SOMETICKER.NS") is None
