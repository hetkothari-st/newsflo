"""Corrective-v4 Task 14: trading-calendar-aware gap/stale guards, data-
quality states, reaction significance, the centralized dead zone applied to
the alert-level direction field, remeasurement of stale/partial rows, and
the honest railways_transport fallback flag. Market data stays an
observation -- none of this touches fundamental analysis."""
from datetime import date, datetime, timedelta

import pytest

from app.market import calendar
from app.market import measure
from app.market.sector_indices import FALLBACK_SECTORS, is_fallback_benchmark


class _FakeCompany:
    def __init__(self, ticker="RELIANCE.NS", sector="oil_gas", company_id=1, market_cap=None):
        self.id = company_id
        self.ticker = ticker
        self.sector = sector
        self.market_cap = market_cap


def _bars_ending(end_date, n=25, close=100.0, volume=100.0, last_close=None):
    """n real NSE trading days ending at (or just before) end_date."""
    days, cursor = [], end_date
    while len(days) < n:
        if calendar.is_trading_day(cursor):
            days.append(cursor)
        cursor -= timedelta(days=1)
    days.reverse()
    bars = [{"date": d.isoformat(), "close": close, "volume": volume} for d in days]
    if last_close is not None:
        bars[-1]["close"] = last_close
    return bars


def _patch_bars(monkeypatch, company_bars, benchmark_bars=None):
    def fake_fetch(ticker, period):
        if ticker.startswith("^"):
            return benchmark_bars if benchmark_bars is not None else company_bars
        return company_bars
    monkeypatch.setattr(measure, "fetch_daily_bars", fake_fetch)


# --- app.market.calendar ---------------------------------------------------

def test_is_trading_day_excludes_weekends():
    saturday = date(2026, 6, 27)
    sunday = date(2026, 6, 28)
    monday = date(2026, 6, 29)
    assert calendar.is_trading_day(saturday) is False
    assert calendar.is_trading_day(sunday) is False
    assert calendar.is_trading_day(monday) is True


def test_is_trading_day_excludes_hardcoded_holidays():
    assert calendar.is_trading_day(date(2026, 1, 26)) is False  # Republic Day
    assert calendar.is_trading_day(date(2026, 8, 15)) is False  # Independence Day
    assert calendar.is_trading_day(date(2026, 10, 2)) is False  # Gandhi Jayanti
    assert calendar.is_trading_day(date(2026, 12, 25)) is False  # Christmas
    assert calendar.is_trading_day(date(2025, 10, 21)) is False  # Diwali Laxmi Pujan 2025


def test_trading_days_between_zero_across_a_plain_weekend():
    friday = date(2026, 1, 23)
    monday = date(2026, 1, 26)  # also Republic Day -- both non-trading either way
    assert calendar.trading_days_between(friday, monday) == 0


def test_trading_days_between_counts_a_real_gap():
    # A week apart with no holidays in between -- 4 real trading days sit
    # strictly between them (Tue..Fri of the intervening week; the two
    # Mondays themselves are the exclusive endpoints).
    start = date(2026, 6, 1)   # Monday
    end = date(2026, 6, 8)     # the following Monday
    assert calendar.trading_days_between(start, end) == 4


def test_trading_days_between_is_order_independent():
    a, b = date(2026, 6, 1), date(2026, 6, 8)
    assert calendar.trading_days_between(a, b) == calendar.trading_days_between(b, a)


def test_session_state_distinguishes_holiday_from_weekend_closed():
    republic_day = datetime.combine(date(2026, 1, 26), datetime.min.time(), tzinfo=calendar.IST)
    sunday = datetime.combine(date(2026, 1, 25), datetime.min.time(), tzinfo=calendar.IST)
    trading_wed = datetime.combine(date(2026, 1, 28), datetime.min.time(), tzinfo=calendar.IST)
    assert calendar.session_state(republic_day.replace(hour=11)) == "holiday"
    assert calendar.session_state(sunday.replace(hour=11)) == "closed"
    assert calendar.session_state(trading_wed.replace(hour=11)) == "open"
    assert calendar.session_state(trading_wed.replace(hour=8)) == "closed"


# --- gap/stale guards count TRADING days, not calendar days ---------------

def test_holiday_cluster_not_marked_stale(monkeypatch):
    """A feed whose last bar predates a weekend + holiday cluster by more
    than 4 CALENDAR days (the old, now-removed threshold) must still read
    as fresh once zero REAL trading days separate the bar from "now" --
    this is the false-stale-over-holiday-cluster bug the trading calendar
    fixes. Two synthetic weekday holidays are patched in beside a real
    weekend so the calendar-day gap (5) exceeds the old threshold while the
    trading-day gap (0) does not."""
    last_bar_date = date(2026, 6, 24)   # Wednesday
    holiday_thu = date(2026, 6, 25)
    holiday_fri = date(2026, 6, 26)
    monkeypatch.setattr(calendar, "NSE_HOLIDAYS", calendar.NSE_HOLIDAYS | {holiday_thu, holiday_fri})
    now = datetime.combine(date(2026, 6, 29), datetime.min.time(),  # Monday, post-cluster
                           tzinfo=calendar.IST).replace(hour=18)

    _patch_bars(monkeypatch, _bars_ending(last_bar_date, last_close=95.0))

    move = measure.measure_company_move(session=None, company=_FakeCompany(), now=now)

    assert move.measurement_status == "ok"
    assert move.data_quality == "ok"


def test_genuine_multi_session_gap_still_marked_stale(monkeypatch):
    """The trading-day guard must still catch a REAL data outage -- this is
    not a blanket relaxation, only a holiday-aware one."""
    last_bar_date = date(2026, 6, 1)  # Monday
    now = datetime.combine(date(2026, 6, 8), datetime.min.time(),  # a full week later
                           tzinfo=calendar.IST).replace(hour=18)
    _patch_bars(monkeypatch, _bars_ending(last_bar_date, last_close=95.0))

    move = measure.measure_company_move(session=None, company=_FakeCompany(), now=now)

    assert move.measurement_status == "stale"
    assert move.data_quality == "stale"


def test_daily_return_tolerates_a_synthetic_holiday_cluster(monkeypatch):
    holiday_thu = date(2026, 6, 25)
    holiday_fri = date(2026, 6, 26)
    monkeypatch.setattr(calendar, "NSE_HOLIDAYS", calendar.NSE_HOLIDAYS | {holiday_thu, holiday_fri})
    bars = [
        {"date": "2026-06-24", "close": 100.0, "volume": 0.0},  # Wed
        {"date": "2026-06-29", "close": 104.0, "volume": 0.0},  # Mon, post-cluster
    ]

    assert measure._daily_return_pct(bars) == pytest.approx(4.0)


# --- data_quality / measurement_status="data_invalid" ---------------------

def test_garbage_close_is_data_invalid_not_no_data(monkeypatch):
    """A bar DID come back (unlike no_data) but its close is nonsense --
    distinct new state so a consumer can tell "nothing available" apart
    from "a provider glitch produced garbage"."""
    bars = _bars_ending(date(2026, 1, 22), last_close=float("nan"))
    _patch_bars(monkeypatch, bars)

    move = measure.measure_company_move(
        session=None, company=_FakeCompany(),
        now=datetime(2026, 1, 22, 18, 0, tzinfo=calendar.IST))

    assert move.measurement_status == "data_invalid"
    assert move.data_quality == "invalid"
    assert move.excess_move_pct is None


def test_negative_close_is_data_invalid():
    assert measure._bar_is_valid({"close": -5.0, "volume": 100.0}) is False
    assert measure._bar_is_valid({"close": 0.0, "volume": 100.0}) is False
    assert measure._bar_is_valid({"close": 100.0, "volume": -1.0}) is False
    assert measure._bar_is_valid({"close": float("inf"), "volume": 100.0}) is False
    assert measure._bar_is_valid({"close": 100.0, "volume": 100.0}) is True


def test_stale_data_quality_distinct_from_unavailable_no_data(monkeypatch):
    """A "stale" row (real bars exist, just too old) must carry a distinct
    data_quality from a "no_data" row (nothing measured at all) -- the
    latter has no quality to grade, so its data_quality stays None rather
    than reusing "stale" or inventing an "unavailable" data_quality value."""
    stale_bars = _bars_ending(date(2026, 6, 1), last_close=95.0)
    _patch_bars(monkeypatch, stale_bars)
    stale_move = measure.measure_company_move(
        session=None, company=_FakeCompany(),
        now=datetime(2026, 6, 10, 18, 0, tzinfo=calendar.IST))
    assert stale_move.measurement_status == "stale"
    assert stale_move.data_quality == "stale"

    def fake_fetch_none(ticker, period):
        return None
    monkeypatch.setattr(measure, "fetch_daily_bars", fake_fetch_none)
    no_data_move = measure.measure_company_move(session=None, company=_FakeCompany())
    assert no_data_move.measurement_status == "no_data"
    assert no_data_move.data_quality is None
    assert stale_move.data_quality != no_data_move.data_quality


def test_ok_partial_bar_data_quality(monkeypatch):
    today = date(2026, 1, 22)
    while not calendar.is_trading_day(today):
        today += timedelta(days=1)
    _patch_bars(monkeypatch, _bars_ending(today, last_close=95.0))
    session_open = datetime.combine(today, datetime.min.time(), tzinfo=calendar.IST).replace(hour=11)

    move = measure.measure_company_move(session=None, company=_FakeCompany(), now=session_open)

    assert move.measurement_status == "ok"
    assert move.bar_complete == 0
    assert move.data_quality == "partial_bar"


# --- reaction_significance --------------------------------------------------

def test_reaction_significance_unknown_when_unmeasured():
    assert measure.reaction_significance(None, None) == "unknown"
    assert measure.reaction_significance(None, 2.0) == "unknown"


def test_reaction_significance_noise_inside_dead_zone():
    assert measure.reaction_significance(0.1, None) == "noise"
    assert measure.reaction_significance(-0.2, 5.0) == "noise"


def test_reaction_significance_normal_band():
    # Clears the dead zone but not 2x it.
    assert measure.reaction_significance(0.3, None) == "normal"
    # Clears 2x the dead zone but vol_normalized says it's not unusual.
    assert measure.reaction_significance(0.6, 1.0) == "normal"


def test_reaction_significance_significant_band():
    # Clears 2x the dead zone with no volatility context to check against.
    assert measure.reaction_significance(0.6, None) == "significant"
    # Clears 2x the dead zone AND is >= 1.5x the stock's own volatility.
    assert measure.reaction_significance(-0.6, 2.0) == "significant"
    assert measure.reaction_significance(0.6, -1.5) == "significant"  # abs() on vol_normalized


# --- alert-level direction respects the dead zone --------------------------

def test_alert_direction_respects_dead_zone(db_session):
    """The alert-level `direction` field used to be a raw sign(excess) with
    NO dead zone applied (bug) -- +0.1% excess must read as "flat", never
    "positive"."""
    from app.market.alert_measurement import compute_alert_measurement
    from app.models import Alert, AlertCompany, Article, Company, MarketMove, utcnow

    article = Article(source="s", provider="finnhub", url="https://ex.com/a",
                      title="t", content="c", status="ALERTED")
    company = Company(name="Reliance", ticker="RELIANCE.NS", sector="oil_gas", index_tier="NIFTY50")
    db_session.add_all([article, company])
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.commit()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, basis="direct_mention"))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=0.2, sector_move_pct=0.1, excess_move_pct=0.1,
        measurement_status="ok", measured_at=utcnow()))
    db_session.commit()

    result = compute_alert_measurement(db_session, alert)

    assert result["direction"] == "flat"
    assert result["market_reaction"]["direction"] == "flat"
    assert result["excess_move_pct"] == 0.1  # exact value untouched


def test_alert_direction_positive_beyond_dead_zone(db_session):
    from app.market.alert_measurement import compute_alert_measurement
    from app.models import Alert, AlertCompany, Article, Company, MarketMove, utcnow

    article = Article(source="s", provider="finnhub", url="https://ex.com/b",
                      title="t", content="c", status="ALERTED")
    company = Company(name="ONGC", ticker="ONGC.NS", sector="oil_gas", index_tier="NIFTY50")
    db_session.add_all([article, company])
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.commit()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, basis="direct_mention"))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=2.0, sector_move_pct=0.5, excess_move_pct=1.5,
        measurement_status="ok", measured_at=utcnow()))
    db_session.commit()

    result = compute_alert_measurement(db_session, alert)

    assert result["direction"] == "positive"


def test_market_reaction_object_carries_new_integrity_fields(db_session):
    from app.market.alert_measurement import compute_alert_measurement
    from app.models import Alert, AlertCompany, Article, Company, MarketMove, utcnow

    article = Article(source="s", provider="finnhub", url="https://ex.com/c",
                      title="t", content="c", status="ALERTED")
    company = Company(name="IOC", ticker="IOC.NS", sector="oil_gas", index_tier="NIFTY50")
    db_session.add_all([article, company])
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.commit()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, basis="direct_mention"))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=2.0, sector_move_pct=0.5, excess_move_pct=1.5,
        measurement_status="ok", measured_at=utcnow(), bar_complete=1,
        data_quality="ok", session_state="closed", reaction_significance="significant"))
    db_session.commit()

    result = compute_alert_measurement(db_session, alert)
    reaction = result["market_reaction"]

    assert reaction["raw_move_pct"] == 2.0
    assert reaction["excess_move_pct"] == 1.5
    assert reaction["benchmark_ticker"] == "^CNXENERGY"
    assert reaction["benchmark_is_fallback"] is False
    assert reaction["data_quality"] == "ok"
    assert reaction["session_state"] == "closed"
    assert reaction["reaction_significance"] == "significant"


# --- remeasure: stale/data_invalid/partial-bar rows are retried -----------

def _seed_move(db, *, status, bar_complete=None, created_at=None):
    from app.models import Alert, AlertCompany, Article, Company, MarketMove, utcnow
    article = Article(source="pulse_zerodha", provider="pulse_zerodha",
                      url=f"https://ex.com/{status}-{bar_complete}", title="t", content="c",
                      status="ALERTED")
    company = Company(name="Reliance Industries", ticker="RELIANCE.NS", sector="oil_gas",
                      index_tier="NIFTY50")
    db.add_all([article, company])
    db.commit()
    alert = Alert(article_id=article.id, category="policy")
    if created_at is not None:
        alert.created_at = created_at
    db.add(alert)
    db.commit()
    alert_company = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=3.0, basis="direct_mention")
    move = MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^NSEI",
        measurement_status=status, bar_complete=bar_complete, measured_at=utcnow(),
        category="policy",
        raw_move_pct=1.0 if status == "ok" else None,
        excess_move_pct=1.0 if status == "ok" else None,
    )
    db.add_all([alert_company, move])
    db.commit()
    return alert, company, alert_company, move


def _fresh_ok_move(company, bar_complete=1):
    from app.models import MarketMove, utcnow
    return MarketMove(
        company_id=company.id, benchmark_ticker="^CNXENERGY", raw_move_pct=-2.0,
        sector_move_pct=0.5, excess_move_pct=-2.5, volume=1000.0, avg_volume_20d=500.0,
        volume_multiple=2.0, vol_normalized=1.1, materiality=0.01, avg_traded_value=9e8,
        measured_at=utcnow(), measurement_status="ok", bar_complete=bar_complete,
        data_quality="ok" if bar_complete else "partial_bar",
        session_state="closed", reaction_significance="significant",
    )


def test_partial_bar_remeasured_after_close(db_session, monkeypatch):
    """A bar_complete=0 row (measured mid-session) with measurement_status
    already "ok" used to never be revisited -- the remeasure sweep now
    retries it too, so after the session closes the row gets updated to the
    real completed-session reaction instead of being stuck at a stale
    intraday snapshot forever."""
    from app.pipeline import remeasure_no_data_moves
    import app.pipeline as pipeline_module

    alert, company, alert_company, move = _seed_move(db_session, status="ok", bar_complete=0)
    monkeypatch.setattr(pipeline_module, "measure_company_move",
                        lambda session, c, **kw: _fresh_ok_move(c, bar_complete=1))

    fixed = remeasure_no_data_moves(db_session)

    assert fixed == 1
    db_session.refresh(move)
    assert move.bar_complete == 1
    assert move.data_quality == "ok"
    assert move.excess_move_pct == -2.5


def test_complete_bar_ok_row_not_retried(db_session, monkeypatch):
    """A COMPLETE bar (bar_complete=1) that is already "ok" is a finished,
    trustworthy reading -- it must NOT be picked up by the remeasure
    sweep (measure_company_move would just re-read the same/next bar for
    no reason)."""
    from app.pipeline import remeasure_no_data_moves
    import app.pipeline as pipeline_module

    _seed_move(db_session, status="ok", bar_complete=1)
    calls = []
    monkeypatch.setattr(pipeline_module, "measure_company_move",
                        lambda session, c, **kw: calls.append(1) or _fresh_ok_move(c))

    assert remeasure_no_data_moves(db_session) == 0
    assert calls == []


def test_stale_row_is_retried(db_session, monkeypatch):
    from app.pipeline import remeasure_no_data_moves
    import app.pipeline as pipeline_module

    _seed_move(db_session, status="stale")
    monkeypatch.setattr(pipeline_module, "measure_company_move",
                        lambda session, c, **kw: _fresh_ok_move(c))

    assert remeasure_no_data_moves(db_session) == 1


def test_data_invalid_row_is_retried(db_session, monkeypatch):
    from app.pipeline import remeasure_no_data_moves
    import app.pipeline as pipeline_module

    _seed_move(db_session, status="data_invalid")
    monkeypatch.setattr(pipeline_module, "measure_company_move",
                        lambda session, c, **kw: _fresh_ok_move(c))

    assert remeasure_no_data_moves(db_session) == 1


# --- railways_transport honest fallback flag --------------------------------

def test_railways_transport_in_fallback_sectors_set():
    assert "railways_transport" in FALLBACK_SECTORS


def test_railways_transport_is_flagged_fallback():
    """railways_transport maps to ^CNXINFRA -- a borrowed EPC/industrials
    proxy, not a dedicated transport index -- so it must be flagged the
    same as a sector with no index at all."""
    assert is_fallback_benchmark("railways_transport") is True


def test_railways_transport_fallback_flag_through_alert_measurement(db_session):
    from app.market.alert_measurement import compute_alert_measurement
    from app.models import Alert, AlertCompany, Article, Company, MarketMove, utcnow

    article = Article(source="s", provider="finnhub", url="https://ex.com/rail",
                      title="t", content="c", status="ALERTED")
    company = Company(name="IRCTC", ticker="IRCTC.NS", sector="railways_transport",
                      index_tier="NIFTY50")
    db_session.add_all([article, company])
    db_session.commit()
    alert = Alert(article_id=article.id, category="railways_transport")
    db_session.add(alert)
    db_session.commit()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, basis="direct_mention"))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXINFRA",
        raw_move_pct=1.0, sector_move_pct=0.2, excess_move_pct=0.8,
        measurement_status="ok", measured_at=utcnow()))
    db_session.commit()

    result = compute_alert_measurement(db_session, alert)

    assert result["benchmark_ticker"] == "^CNXINFRA"
    assert result["is_fallback_benchmark"] is True
    assert result["market_reaction"]["benchmark_is_fallback"] is True
