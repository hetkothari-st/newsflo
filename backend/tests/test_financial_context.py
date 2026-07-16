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


from app.models import FinancialSnapshot, utcnow


def test_cache_ttl_is_one_hour():
    assert financial_context.SNAPSHOT_CACHE_HOURS == 1


def test_get_or_fetch_creates_a_row_when_none_exists(db_session, monkeypatch):
    monkeypatch.setattr(
        financial_context, "fetch_financial_snapshot",
        lambda ticker: {"price": 2500.5, "return_1m": 8.3, "return_3m": -2.1},
    )

    result = financial_context.get_or_fetch_financial_snapshot(db_session, "RELIANCE.NS")

    assert result == {"price": 2500.5, "return_1m": 8.3, "return_3m": -2.1}
    row = db_session.query(FinancialSnapshot).filter_by(ticker="RELIANCE.NS").one()
    assert row.price == 2500.5


def test_get_or_fetch_reuses_a_fresh_cached_row_without_refetching(db_session, monkeypatch):
    db_session.add(FinancialSnapshot(
        ticker="RELIANCE.NS", price=100.0, return_1m=1.0, return_3m=2.0, fetched_at=utcnow(),
    ))
    db_session.commit()
    monkeypatch.setattr(
        financial_context, "fetch_financial_snapshot",
        lambda ticker: (_ for _ in ()).throw(AssertionError("should not refetch a fresh cache entry")),
    )

    result = financial_context.get_or_fetch_financial_snapshot(db_session, "RELIANCE.NS")

    assert result == {"price": 100.0, "return_1m": 1.0, "return_3m": 2.0}


def test_get_or_fetch_refetches_a_stale_cached_row(db_session, monkeypatch):
    stale_time = utcnow() - timedelta(hours=2)
    db_session.add(FinancialSnapshot(
        ticker="RELIANCE.NS", price=100.0, return_1m=1.0, return_3m=2.0, fetched_at=stale_time,
    ))
    db_session.commit()
    monkeypatch.setattr(
        financial_context, "fetch_financial_snapshot",
        lambda ticker: {"price": 200.0, "return_1m": 9.0, "return_3m": 10.0},
    )

    result = financial_context.get_or_fetch_financial_snapshot(db_session, "RELIANCE.NS")

    assert result == {"price": 200.0, "return_1m": 9.0, "return_3m": 10.0}
    row = db_session.query(FinancialSnapshot).filter_by(ticker="RELIANCE.NS").one()
    assert row.price == 200.0


def test_get_or_fetch_falls_back_to_stale_cache_when_refetch_fails(db_session, monkeypatch):
    stale_time = utcnow() - timedelta(hours=2)
    db_session.add(FinancialSnapshot(
        ticker="RELIANCE.NS", price=100.0, return_1m=1.0, return_3m=2.0, fetched_at=stale_time,
    ))
    db_session.commit()
    monkeypatch.setattr(financial_context, "fetch_financial_snapshot", lambda ticker: None)

    result = financial_context.get_or_fetch_financial_snapshot(db_session, "RELIANCE.NS")

    assert result == {"price": 100.0, "return_1m": 1.0, "return_3m": 2.0}


def test_get_or_fetch_returns_none_when_no_cache_and_fetch_fails(db_session, monkeypatch):
    monkeypatch.setattr(financial_context, "fetch_financial_snapshot", lambda ticker: None)

    result = financial_context.get_or_fetch_financial_snapshot(db_session, "UNKNOWN.NS")

    assert result is None
    assert db_session.query(FinancialSnapshot).count() == 0
