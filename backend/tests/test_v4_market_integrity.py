"""Phase 7 market-data integrity (spec §20-§22): stale-bar detection,
event-vs-bar ordering (no pre-event bar recorded as the reaction), partial
intraday-bar labeling, the meaningful-move dead zone, and an honest
fallback-benchmark flag. Market data stays an observation -- none of this
touches fundamental analysis."""
from datetime import datetime, timedelta, timezone

import pytest

from app.ist_time import IST, today_ist
from app.market import measure


class _FakeCompany:
    def __init__(self, ticker="RELIANCE.NS", sector="oil_gas", company_id=1, market_cap=None):
        self.id = company_id
        self.ticker = ticker
        self.sector = sector
        self.market_cap = market_cap


def _bars_ending(end_date, n=25, close=100.0, volume=100.0, last_close=None):
    days, cursor = [], end_date
    while len(days) < n:
        if cursor.weekday() < 5:
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


def test_stale_bars_marked_stale_not_ok(monkeypatch):
    """A feed 2-4+ days behind used to be silently accepted; a dead feed
    must say 'stale', never pass its last close off as today's move."""
    old_end = today_ist() - timedelta(days=6)
    _patch_bars(monkeypatch, _bars_ending(old_end, last_close=95.0))

    move = measure.measure_company_move(session=None, company=_FakeCompany())

    assert move.measurement_status == "stale"
    assert move.excess_move_pct is None


def test_event_after_last_bar_is_no_data(monkeypatch):
    """Weekend rule (spec §21): an alert created Saturday must not record
    Friday's bar as its reaction -- the market hasn't traded on the event
    yet. no_data now; the remeasure sweep picks it up Monday."""
    friday = today_ist()
    while friday.weekday() != 4:
        friday -= timedelta(days=1)
    saturday_event = datetime.combine(friday + timedelta(days=1),
                                      datetime.min.time(), tzinfo=IST)
    _patch_bars(monkeypatch, _bars_ending(friday, last_close=95.0))

    move = measure.measure_company_move(
        session=None, company=_FakeCompany(),
        event_time=saturday_event.astimezone(timezone.utc),
        now=saturday_event.replace(hour=12).astimezone(timezone.utc))

    assert move.measurement_status == "no_data"


def test_intraday_partial_bar_flagged_incomplete(monkeypatch):
    _patch_bars(monkeypatch, _bars_ending(today_ist(), last_close=95.0))
    session_open = datetime.combine(today_ist(), datetime.min.time(),
                                    tzinfo=IST).replace(hour=11)

    move = measure.measure_company_move(
        session=None, company=_FakeCompany(), now=session_open)

    assert move.measurement_status == "ok"
    assert move.bar_complete == 0


def test_closed_session_bar_is_complete(monkeypatch):
    _patch_bars(monkeypatch, _bars_ending(today_ist(), last_close=95.0))
    evening = datetime.combine(today_ist(), datetime.min.time(),
                               tzinfo=IST).replace(hour=18)

    move = measure.measure_company_move(
        session=None, company=_FakeCompany(), now=evening)

    assert move.measurement_status == "ok"
    assert move.bar_complete == 1


def test_market_session_state():
    day = today_ist()
    while day.weekday() != 2:  # a Wednesday
        day -= timedelta(days=1)
    base = datetime.combine(day, datetime.min.time(), tzinfo=IST)
    assert measure.market_session_state(base.replace(hour=11)) == "open"
    assert measure.market_session_state(base.replace(hour=8)) == "closed"
    assert measure.market_session_state(base.replace(hour=16)) == "closed"
    sunday = base + timedelta(days=4)
    assert measure.market_session_state(sunday.replace(hour=11)) == "closed"


def test_classify_reaction_dead_zone():
    """Spec §22: sub-noise moves are FLAT, never a confident direction;
    0.0 and +0.01% stop reading as 'winner'."""
    assert measure.classify_reaction(0.0) == "flat"
    assert measure.classify_reaction(0.1) == "flat"
    assert measure.classify_reaction(-0.2) == "flat"
    assert measure.classify_reaction(0.6) == "positive"
    assert measure.classify_reaction(-0.6) == "negative"
    assert measure.classify_reaction(None) == "unknown"


def test_fallback_benchmark_flag_reflects_actual_benchmark(db_session):
    """alert_measurement derived is_fallback_benchmark from the SECTOR,
    so a stale-sector-index degrade to ^NSEI still claimed 'vs sector
    index' (bug). The flag must reflect the benchmark actually used."""
    from app.market.alert_measurement import compute_alert_measurement
    from app.models import Alert, AlertCompany, Article, Company, MarketMove, utcnow

    article = Article(source="s", provider="finnhub", url="https://ex.com/a",
                      title="t", content="c", status="ALERTED")
    company = Company(name="Maruti", ticker="MARUTI.NS", sector="auto",
                      index_tier="NIFTY50")
    db_session.add_all([article, company])
    db_session.commit()
    alert = Alert(article_id=article.id, category="auto")
    db_session.add(alert)
    db_session.commit()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bearish",
        magnitude_low=1.0, magnitude_high=3.0, basis="direct_mention"))
    # ^CNXAUTO was stale -> measured against ^NSEI (the degrade path).
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^NSEI",
        measurement_status="ok", raw_move_pct=-2.0, sector_move_pct=-0.5,
        excess_move_pct=-1.5, measured_at=utcnow(), category="auto"))
    db_session.commit()

    measurement = compute_alert_measurement(db_session, alert)

    assert measurement["is_fallback_benchmark"] is True
