from datetime import datetime, timedelta, timezone

import pytest

from app.reasoning import financial_context


def test_fetch_financial_snapshot_returns_price_and_returns(monkeypatch):
    monkeypatch.setattr(
        financial_context, "fetch_price_series",
        lambda ticker, period: [{"date": "2026-07-15", "close": 2500.5}],
    )

    def fake_change(ticker, start_date, horizon_days):
        return 8.3 if horizon_days == 30 else -2.1

    monkeypatch.setattr(financial_context, "fetch_price_change_pct", fake_change)

    result = financial_context.fetch_financial_snapshot("RELIANCE.NS")

    assert result == {"price": 2500.5, "return_1m": 8.3, "return_3m": -2.1}


def test_fetch_financial_snapshot_returns_none_when_price_unavailable(monkeypatch):
    monkeypatch.setattr(financial_context, "fetch_price_series", lambda ticker, period: None)
    monkeypatch.setattr(
        financial_context, "fetch_price_change_pct",
        lambda ticker, start_date, horizon_days: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    assert financial_context.fetch_financial_snapshot("UNKNOWN.NS") is None


def test_fetch_financial_snapshot_degrades_individual_return_to_none(monkeypatch):
    monkeypatch.setattr(
        financial_context, "fetch_price_series",
        lambda ticker, period: [{"date": "2026-07-15", "close": 100.0}],
    )

    def fake_change(ticker, start_date, horizon_days):
        return None if horizon_days == 30 else 4.0

    monkeypatch.setattr(financial_context, "fetch_price_change_pct", fake_change)

    result = financial_context.fetch_financial_snapshot("PARTIAL.NS")

    assert result == {"price": 100.0, "return_1m": None, "return_3m": 4.0}


def test_threshold_is_five_percent():
    assert financial_context.CONTRADICTION_THRESHOLD_PCT == 5.0


def test_detect_price_contradiction_bullish_at_threshold_triggers():
    note = financial_context.detect_price_contradiction("bullish", -5.0)
    assert note is not None
    assert "bullish" in note.lower()
    assert "5.0%" in note


def test_detect_price_contradiction_bullish_just_under_threshold_no_trigger():
    assert financial_context.detect_price_contradiction("bullish", -4.9) is None


def test_detect_price_contradiction_bearish_at_threshold_triggers():
    note = financial_context.detect_price_contradiction("bearish", 5.0)
    assert note is not None
    assert "bearish" in note.lower()


def test_detect_price_contradiction_bearish_just_under_threshold_no_trigger():
    assert financial_context.detect_price_contradiction("bearish", 4.9) is None


def test_detect_price_contradiction_none_return_never_triggers():
    assert financial_context.detect_price_contradiction("bullish", None) is None
    assert financial_context.detect_price_contradiction("bearish", None) is None


def test_detect_price_contradiction_ignores_unrecognized_direction():
    assert financial_context.detect_price_contradiction("neutral", -50.0) is None
