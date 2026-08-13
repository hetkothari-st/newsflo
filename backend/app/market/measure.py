"""Deterministic market-measurement service -- the spine of the app
(docs/NEWS_IMPACT_APP_SPEC.md §3-§5). Every function here is arithmetic
over price/volume bars; nothing calls an LLM. Built on
app.companies.price_series.fetch_daily_bars and
app.market.sector_indices.benchmark_ticker_for_sector.
"""
import math
import os
from datetime import (
    date as _date, datetime, timedelta as _timedelta,
    timezone as _timezone,
)

from sqlalchemy.orm import Session

from app.companies.price_series import fetch_daily_bars
from app.market import calendar as _calendar
# _SESSION_OPEN/_SESSION_CLOSE re-exported under their original private
# names for backward compatibility -- the session bounds themselves now
# live in app.market.calendar alongside the rest of the trading calendar.
from app.market.calendar import IST, SESSION_CLOSE as _SESSION_CLOSE, SESSION_OPEN as _SESSION_OPEN  # noqa: F401
from app.market.sector_indices import NIFTY50_TICKER, benchmark_ticker_for_sector
from app.models import Company, MarketMove, utcnow

# Max REAL trading days that may sit strictly between the last two bars for
# them to still count as "consecutive sessions". Trading-day counting (Task
# 14, spec §21 hardening) via app.market.calendar.trading_days_between --
# NOT plain calendar days -- so a long weekend or a multi-day holiday
# cluster (all non-trading days) contributes 0 regardless of how many
# calendar days it spans, while a genuine feed hole (real trading days with
# no bar) does not. Yahoo's NSE sector-index feeds go dark for weeks at a
# time -- ^CNXAUTO once gapped Jul 17 -> Aug 12 and the naive close-to-close
# read reported "+8.35% today", corrupting every auto company's excess move
# by ~-8pp (measured live 2026-08-12).
_MAX_BAR_GAP_TRADING_DAYS = 0

# A feed whose LAST bar is more than this many REAL trading days behind
# today (IST) is a dead/stale feed: its close must not pass as "today's
# move". Trading-day counting means a weekend + any length holiday cluster
# never inflates this -- only actual missed trading sessions do. Writes the
# measurement_status="stale" (spec §21).
_STALE_BAR_MAX_TRADING_DAYS = 0

# Meaningful-move dead zone (spec §22): |excess| below this is market
# noise and classifies as "flat", never a confident direction. Applies to
# REACTION classification only -- excess_move_pct itself stays exact, and
# fundamental analysis is untouched by definition. THE single sanctioned
# dead-zone constant for the whole codebase -- every other consumer
# (app.market.ripple_layers, app.market.alert_measurement,
# app.analysis.refinement) imports classify_reaction from this module
# rather than re-deriving its own threshold.
MARKET_REACTION_DEAD_ZONE_PCT = float(os.environ.get("MARKET_REACTION_DEAD_ZONE_PCT", "0.25"))


def market_session_state(now_ist: datetime) -> str:
    """"open" during the NSE cash session (Mon-Fri 09:15-15:30 IST),
    "closed" otherwise (including NSE holidays). Thin re-export of
    app.market.calendar.session_state, kept here under its original name
    for backward compatibility with existing importers of this module."""
    state = _calendar.session_state(now_ist)
    # Pre-calendar callers only ever saw "open"/"closed" -- fold "holiday"
    # into "closed" so this function's return contract is unchanged; the
    # richer 3-state value is available from measured MarketMove rows via
    # the new session_state column / app.market.calendar.session_state
    # directly for callers that want to distinguish them.
    return "closed" if state == "holiday" else state


def classify_reaction(excess_move_pct: float | None) -> str:
    """Deterministic market-reaction class: positive/negative beyond the
    dead zone, flat inside it, unknown when unmeasured. This is the ONLY
    sanctioned excess->direction mapping; it never feeds back into
    fundamental analysis (spec §22/§25)."""
    if excess_move_pct is None:
        return "unknown"
    if abs(excess_move_pct) < MARKET_REACTION_DEAD_ZONE_PCT:
        return "flat"
    return "positive" if excess_move_pct > 0 else "negative"


def reaction_significance(excess_move_pct: float | None, vol_normalized: float | None) -> str:
    """Whether a reaction is statistically worth calling out, distinct from
    classify_reaction's sign (spec Task 14): "unknown" when unmeasured,
    "noise" inside the same dead zone classify_reaction uses (never a
    confident reaction, same threshold, same single constant), "significant"
    when the move both clears TWICE the dead zone AND (no volatility
    context to check against, or the move is at least 1.5x the stock's own
    trailing volatility), else "normal" -- a real, dead-zone-clearing move
    that isn't large enough (in absolute or vol-normalized terms) to flag as
    standout. Pure classification; never written back into fundamentals."""
    if excess_move_pct is None:
        return "unknown"
    if abs(excess_move_pct) < MARKET_REACTION_DEAD_ZONE_PCT:
        return "noise"
    if abs(excess_move_pct) >= 2 * MARKET_REACTION_DEAD_ZONE_PCT and (
        vol_normalized is None or abs(vol_normalized) >= 1.5
    ):
        return "significant"
    return "normal"


def _bar_is_valid(bar: dict) -> bool:
    """A bar is usable only if its close/volume are real, finite, sane
    numbers -- a NaN/inf/non-positive close or a negative volume is a data
    provider glitch, not a real price, and must never flow into an excess-
    move computation (measurement_status="data_invalid", spec Task 14,
    distinct from "no_data": a row DID come back, it's just garbage)."""
    close = bar.get("close")
    if not isinstance(close, (int, float)) or isinstance(close, bool) or not math.isfinite(close) or close <= 0:
        return False
    volume = bar.get("volume")
    if volume is not None and (
        not isinstance(volume, (int, float)) or isinstance(volume, bool)
        or not math.isfinite(volume) or volume < 0
    ):
        return False
    return True


def compute_excess_move_pct(raw_move_pct: float, sector_move_pct: float) -> float:
    """§4.1 simple tier: excess = raw - sector. The beta-adjusted tier
    (spec §4.1) is a deliberate, unbuilt seam -- this (raw, sector) ->
    excess signature is what a future beta-adjusted variant would still
    need to satisfy, so callers never change."""
    return raw_move_pct - sector_move_pct


def compute_volume_multiple(day_volume: float, avg_volume_20d: float | None) -> float | None:
    """day_volume / trailing_20d_avg_volume, or None if the average is
    zero or absent -- never a fabricated or divide-by-zero number."""
    if not avg_volume_20d:
        return None
    return day_volume / avg_volume_20d


def _daily_return_pct(bars: list[dict]) -> float | None:
    """Latest day's own % close-to-close move from a fetch_daily_bars()
    series, or None if fewer than 2 points exist, the prior close is 0,
    or the last two bars are not consecutive sessions (a multi-week feed
    hole must never masquerade as a one-day move)."""
    if len(bars) < 2:
        return None
    prev_date = _date.fromisoformat(bars[-2]["date"])
    last_date = _date.fromisoformat(bars[-1]["date"])
    if _calendar.trading_days_between(prev_date, last_date) > _MAX_BAR_GAP_TRADING_DAYS:
        return None
    prev_close = bars[-2]["close"]
    last_close = bars[-1]["close"]
    if not prev_close:
        return None
    return (last_close - prev_close) / prev_close * 100


def compute_vol_normalized(raw_move_pct: float, bars: list[dict]) -> float | None:
    """Spec v2 §4.2 vol_normalized: |today's raw move| divided by the
    standard deviation of the stock's own trailing daily returns (the 20
    days before today) -- "a 3% move is huge for a stable large cap,
    normal for a jumpy small cap". Returns None (never a fabricated
    number) when fewer than 3 trailing returns exist or the stock was
    flat throughout (zero deviation)."""
    closes = [b["close"] for b in bars[:-1]][-21:]  # up to 21 closes -> 20 returns, today excluded
    returns = [
        (closes[i] - closes[i - 1]) / closes[i - 1] * 100
        for i in range(1, len(closes))
        if closes[i - 1]
    ]
    if len(returns) < 3:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)
    stdev = variance ** 0.5
    if stdev == 0:
        return None
    return abs(raw_move_pct) / stdev


def compute_avg_traded_value(bars: list[dict]) -> float | None:
    """20-day average of close x volume (the days before today) -- the
    liquidity-tier input (spec v2 §4.6). None when no trailing days exist."""
    trailing = bars[-21:-1]
    if not trailing:
        return None
    return sum(b["close"] * b["volume"] for b in trailing) / len(trailing)


def compute_materiality(
    day_close: float, day_volume: float, avg_volume_20d: float | None, market_cap: float | None,
) -> float | None:
    """Spec v2 §4.2 materiality: news size vs company size. Deterministic
    proxy from measured bars only (no LLM): the day's EXCESS traded value
    (value traded beyond the stock's own 20-day average) as a fraction of
    market cap -- "a Rs 500 Cr order is transformational for a Rs 1,000 Cr
    micro-cap, trivial for a giant". Raw ratio; normalized within
    sector/event on read like every other intensity sub-score. None when
    market cap or the volume average is unavailable (omit, never invent)."""
    if not market_cap or avg_volume_20d is None:
        return None
    excess_traded_value = max(0.0, (day_volume - avg_volume_20d)) * day_close
    return excess_traded_value / market_cap


def measure_company_move(session: Session, company: Company,
                         event_time: datetime | None = None,
                         now: datetime | None = None) -> MarketMove:
    """Fetch real price/volume bars for ``company`` and its sector
    benchmark, compute the measured facts, and return an unattached
    MarketMove row (caller must set alert_id and session.add it). Never
    raises -- any missing upstream data produces measurement_status=
    'no_data' with null metric columns rather than a fabricated number or
    a crashed alert.

    Integrity guards (spec §21, hardened Task 14): a feed whose last bar is
    more than _STALE_BAR_MAX_TRADING_DAYS REAL trading days behind today
    returns "stale" (holiday clusters no longer inflate this -- see
    app.market.calendar); a bar with a non-finite/garbage close or volume
    returns "data_invalid" (distinct from "no_data": a row DID come back,
    it's just unusable); an event newer than the last bar (weekend/after-
    hours alert) returns "no_data" -- Friday's close is not Saturday's
    reaction; a bar measured mid-session is labeled bar_complete=0.

    Every returned row also carries: session_state (NSE session state at
    measurement time: open/closed/holiday), data_quality
    (ok/partial_bar/stale/invalid -- None when nothing was measured at all,
    a distinct "nothing to grade" state from any of the four), and
    reaction_significance (significant/normal/noise/unknown).
    """
    now = now or datetime.now(_timezone.utc)
    now_ist = now.astimezone(IST)
    session_state_now = _calendar.session_state(now_ist)
    benchmark_ticker = benchmark_ticker_for_sector(company.sector)
    company_bars = fetch_daily_bars(company.ticker, period="2mo")
    benchmark_bars = fetch_daily_bars(benchmark_ticker, period="2mo")

    if not company_bars:
        return MarketMove(
            company_id=company.id, benchmark_ticker=benchmark_ticker,
            measurement_status="no_data", measured_at=utcnow(),
            session_state=session_state_now, reaction_significance="unknown",
        )

    if not _bar_is_valid(company_bars[-1]):
        return MarketMove(
            company_id=company.id, benchmark_ticker=benchmark_ticker,
            measurement_status="data_invalid", measured_at=utcnow(),
            data_quality="invalid", session_state=session_state_now,
            reaction_significance="unknown",
        )

    last_bar_date = _date.fromisoformat(company_bars[-1]["date"])
    if _calendar.trading_days_between(last_bar_date, now_ist.date()) > _STALE_BAR_MAX_TRADING_DAYS:
        return MarketMove(
            company_id=company.id, benchmark_ticker=benchmark_ticker,
            measurement_status="stale", measured_at=utcnow(),
            last_bar_date=last_bar_date.isoformat(),
            data_quality="stale", session_state=session_state_now,
            reaction_significance="unknown",
        )
    if event_time is not None:
        event_ist_date = event_time.astimezone(IST).date()
        if last_bar_date < event_ist_date:
            # The market has not traded since the event: recording this
            # bar would present a PRE-event close as the reaction. Honest
            # no_data; the remeasure sweep retries once a session exists.
            return MarketMove(
                company_id=company.id, benchmark_ticker=benchmark_ticker,
                measurement_status="no_data", measured_at=utcnow(),
                last_bar_date=last_bar_date.isoformat(),
                session_state=session_state_now, reaction_significance="unknown",
            )

    raw_move_pct = _daily_return_pct(company_bars)
    sector_move_pct = _daily_return_pct(benchmark_bars) if benchmark_bars else None
    # A sector index whose feed is stale/gappy (the guard above returns
    # None) must not sink the measurement -- degrade to the Nifty 50
    # benchmark, exactly like sectors with no index of their own. The
    # stored benchmark_ticker changes with it, so the UI honestly says
    # "vs Nifty 50".
    if sector_move_pct is None and benchmark_ticker != NIFTY50_TICKER:
        nifty_bars = fetch_daily_bars(NIFTY50_TICKER, period="2mo")
        nifty_move = _daily_return_pct(nifty_bars) if nifty_bars else None
        if nifty_move is not None:
            benchmark_ticker = NIFTY50_TICKER
            sector_move_pct = nifty_move
    if raw_move_pct is None or sector_move_pct is None:
        return MarketMove(
            company_id=company.id, benchmark_ticker=benchmark_ticker,
            measurement_status="no_data", measured_at=utcnow(),
            session_state=session_state_now, reaction_significance="unknown",
        )

    day_volume = company_bars[-1]["volume"]
    trailing = [b["volume"] for b in company_bars[-21:-1]]  # 20 days before today
    avg_volume_20d = (sum(trailing) / len(trailing)) if trailing else None
    volume_multiple = compute_volume_multiple(day_volume, avg_volume_20d)
    excess_move_pct = compute_excess_move_pct(raw_move_pct, sector_move_pct)
    vol_normalized = compute_vol_normalized(raw_move_pct, company_bars)
    # A bar measured during its own session is a partial snapshot, not a
    # completed daily reaction -- labeled, never hidden.
    bar_complete = 0 if (last_bar_date == now_ist.date() and session_state_now == "open") else 1

    return MarketMove(
        company_id=company.id,
        raw_move_pct=raw_move_pct,
        sector_move_pct=sector_move_pct,
        benchmark_ticker=benchmark_ticker,
        excess_move_pct=excess_move_pct,
        volume=day_volume,
        avg_volume_20d=avg_volume_20d,
        volume_multiple=volume_multiple,
        # delivery_pct deliberately left NULL -- no real NSE delivery-data
        # source is wired yet; intensity renormalizes without it rather
        # than fabricating (spec v2 §4.2 + Ground Rules).
        vol_normalized=vol_normalized,
        materiality=compute_materiality(
            company_bars[-1]["close"], day_volume, avg_volume_20d, company.market_cap,
        ),
        avg_traded_value=compute_avg_traded_value(company_bars),
        measured_at=utcnow(),
        measurement_status="ok",
        last_bar_date=last_bar_date.isoformat(),
        bar_complete=bar_complete,
        data_quality="partial_bar" if bar_complete == 0 else "ok",
        session_state=session_state_now,
        reaction_significance=reaction_significance(excess_move_pct, vol_normalized),
    )
