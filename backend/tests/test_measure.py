from datetime import datetime

import pytest

from app.market import measure
from app.models import Company

# Fixture bars use fixed 2026-01 dates; anchor "now" beside them so the
# stale-bar guard (measured against today) doesn't fire on old fixtures.
_NOW_JAN22 = datetime(2026, 1, 22, 18, 0, tzinfo=measure.IST)
_NOW_JAN02 = datetime(2026, 1, 2, 18, 0, tzinfo=measure.IST)


class _FakeCompany:
    def __init__(self, ticker, sector, company_id=1, market_cap=None):
        self.id = company_id
        self.ticker = ticker
        self.sector = sector
        self.market_cap = market_cap


def test_compute_excess_move_pct_positive():
    assert measure.compute_excess_move_pct(raw_move_pct=3.0, sector_move_pct=1.0) == 2.0


def test_compute_excess_move_pct_negative():
    assert measure.compute_excess_move_pct(raw_move_pct=-4.8, sector_move_pct=-0.6) == pytest.approx(-4.2)


def test_compute_volume_multiple_normal():
    assert measure.compute_volume_multiple(day_volume=300.0, avg_volume_20d=100.0) == 3.0


def test_compute_volume_multiple_zero_average_returns_none():
    assert measure.compute_volume_multiple(day_volume=300.0, avg_volume_20d=0.0) is None


def test_compute_volume_multiple_absent_average_returns_none():
    assert measure.compute_volume_multiple(day_volume=300.0, avg_volume_20d=None) is None


def _bars(closes, volumes, dates):
    return [{"date": d, "close": c, "volume": v} for d, c, v in zip(dates, closes, volumes)]


def test_measure_company_move_ok_path(monkeypatch):
    company = _FakeCompany(ticker="RELIANCE.NS", sector="oil_gas")
    dates = [f"2026-01-{i:02d}" for i in range(1, 23)]  # 22 trading days
    company_closes = [100.0] * 21 + [95.2]  # index 20 (prev close) -> index 21 (today): -4.8%
    # bars[-21:-1] (the 20-day trailing window) is indices 1..20 -- index 0
    # is padding excluded from that window, index 21 is "today"'s volume.
    company_volumes = [0.0] + [100.0] * 20 + [300.0]  # 20d avg = 100, today = 300 -> 3x
    benchmark_closes = [1000.0] * 21 + [994.0]  # index 20 -> index 21: -0.6%
    benchmark_volumes = [0.0] * 22

    def fake_fetch_daily_bars(ticker, period):
        if ticker == "RELIANCE.NS":
            return _bars(company_closes, company_volumes, dates)
        return _bars(benchmark_closes, benchmark_volumes, dates)

    monkeypatch.setattr(measure, "fetch_daily_bars", fake_fetch_daily_bars)

    move = measure.measure_company_move(session=None, company=company, now=_NOW_JAN22)

    assert move.measurement_status == "ok"
    assert move.company_id == 1
    assert move.benchmark_ticker == "^CNXENERGY"
    assert move.raw_move_pct == pytest.approx(-4.8, abs=0.01)
    assert move.sector_move_pct == pytest.approx(-0.6, abs=0.01)
    assert move.excess_move_pct == pytest.approx(-4.2, abs=0.02)
    assert move.volume == 300.0
    assert move.avg_volume_20d == pytest.approx(100.0, abs=0.01)
    assert move.volume_multiple == pytest.approx(3.0, abs=0.01)


def test_measure_company_move_no_data_when_company_bars_missing(monkeypatch):
    company = _FakeCompany(ticker="UNKNOWN.NS", sector="other")

    def fake_fetch_daily_bars(ticker, period):
        return None

    monkeypatch.setattr(measure, "fetch_daily_bars", fake_fetch_daily_bars)

    move = measure.measure_company_move(session=None, company=company)

    assert move.measurement_status == "no_data"
    assert move.raw_move_pct is None
    assert move.sector_move_pct is None
    assert move.excess_move_pct is None
    assert move.benchmark_ticker == "^NSEI"  # "other" falls back to Nifty 50


def test_measure_company_move_no_data_when_benchmark_bars_missing(monkeypatch):
    company = _FakeCompany(ticker="RELIANCE.NS", sector="oil_gas")

    def fake_fetch_daily_bars(ticker, period):
        if ticker == "RELIANCE.NS":
            return _bars([100.0, 101.0], [10.0, 10.0], ["2026-01-01", "2026-01-02"])
        return None  # benchmark fetch fails

    monkeypatch.setattr(measure, "fetch_daily_bars", fake_fetch_daily_bars)

    move = measure.measure_company_move(session=None, company=company, now=_NOW_JAN02)

    assert move.measurement_status == "no_data"
    assert move.excess_move_pct is None


def test_measure_company_move_fallback_benchmark_recorded_for_unmapped_sector(monkeypatch):
    company = _FakeCompany(ticker="SOMECO.NS", sector="textiles")

    def fake_fetch_daily_bars(ticker, period):
        return _bars([100.0, 101.0], [10.0, 10.0], ["2026-01-01", "2026-01-02"])

    monkeypatch.setattr(measure, "fetch_daily_bars", fake_fetch_daily_bars)

    move = measure.measure_company_move(session=None, company=company, now=_NOW_JAN02)

    assert move.benchmark_ticker == "^NSEI"
    assert move.measurement_status == "ok"


def test_daily_return_none_when_bars_span_a_feed_hole():
    """Yahoo's NSE sector-index feeds go dark for weeks (^CNXAUTO gapped
    Jul 17 -> Aug 12 live); the close-to-close read must refuse to call
    that a one-day move."""
    bars = _bars([27099.75, 29363.05], [0.0, 0.0], ["2026-07-17", "2026-08-12"])

    assert measure._daily_return_pct(bars) is None


def test_daily_return_tolerates_a_long_weekend():
    # 2026-01-02 is a Friday, 2026-01-05 the following Monday -- zero real
    # NSE trading days fall strictly between them (only the weekend does),
    # so the trading-day gap guard must treat this as consecutive sessions.
    bars = _bars([100.0, 102.0], [0.0, 0.0], ["2026-01-02", "2026-01-05"])

    assert measure._daily_return_pct(bars) == pytest.approx(2.0)


def test_daily_return_tolerates_a_holiday_cluster():
    """A holiday cluster (here: Republic Day 2026, a Monday, right after a
    weekend) must not read as a feed hole -- zero real trading days fall
    strictly between the Friday close and the Tuesday reopen."""
    bars = _bars([100.0, 103.0], [0.0, 0.0], ["2026-01-23", "2026-01-27"])

    assert measure._daily_return_pct(bars) == pytest.approx(3.0)


def test_measure_falls_back_to_nifty_when_sector_index_is_gappy(monkeypatch):
    """A stale sector index must not corrupt excess (raw - 8.35pp fake
    sector move) OR sink the row to no_data -- it degrades to the Nifty
    50 benchmark and says so via benchmark_ticker."""
    company = _FakeCompany(ticker="TVSSRICHAK.NS", sector="auto")

    def fake_fetch_daily_bars(ticker, period):
        if ticker == "TVSSRICHAK.NS":
            return _bars([3944.7, 3868.2], [10.0, 10.0], ["2026-08-11", "2026-08-12"])
        if ticker == "^CNXAUTO":  # month-long hole
            return _bars([27099.75, 29363.05], [0.0, 0.0], ["2026-07-17", "2026-08-12"])
        if ticker == "^NSEI":  # healthy
            return _bars([24500.0, 24402.0], [0.0, 0.0], ["2026-08-11", "2026-08-12"])
        raise AssertionError(f"unexpected ticker {ticker}")

    monkeypatch.setattr(measure, "fetch_daily_bars", fake_fetch_daily_bars)

    # Freeze "now" beside the hardcoded bar dates: unfrozen, this test
    # started failing the day the real calendar drifted 4+ trading days
    # past 2026-08-12 and the stale guard (correctly) fired.
    now = datetime(2026, 8, 12, 18, 0, tzinfo=measure.IST)
    move = measure.measure_company_move(session=None, company=company, now=now)

    assert move.measurement_status == "ok"
    assert move.benchmark_ticker == "^NSEI"
    assert move.raw_move_pct == pytest.approx(-1.94, abs=0.01)
    assert move.sector_move_pct == pytest.approx(-0.4, abs=0.01)
    assert move.excess_move_pct == pytest.approx(-1.54, abs=0.02)
