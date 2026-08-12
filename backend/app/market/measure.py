"""Deterministic market-measurement service -- the spine of the app
(docs/NEWS_IMPACT_APP_SPEC.md §3-§5). Every function here is arithmetic
over price/volume bars; nothing calls an LLM. Built on
app.companies.price_series.fetch_daily_bars and
app.market.sector_indices.benchmark_ticker_for_sector.
"""
from datetime import date as _date

from sqlalchemy.orm import Session

from app.companies.price_series import fetch_daily_bars
from app.market.sector_indices import NIFTY50_TICKER, benchmark_ticker_for_sector
from app.models import Company, MarketMove, utcnow

# Max calendar days between the last two bars for them to count as
# "consecutive sessions" (a long weekend + holiday cluster fits; a data
# hole does not). Yahoo's NSE sector-index feeds go dark for weeks at a
# time -- ^CNXAUTO once gapped Jul 17 -> Aug 12 and the naive
# close-to-close read reported "+8.35% today", corrupting every auto
# company's excess move by ~-8pp (measured live 2026-08-12).
_MAX_BAR_GAP_DAYS = 5


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
    gap_days = (
        _date.fromisoformat(bars[-1]["date"]) - _date.fromisoformat(bars[-2]["date"])
    ).days
    if gap_days > _MAX_BAR_GAP_DAYS:
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


def measure_company_move(session: Session, company: Company) -> MarketMove:
    """Fetch real price/volume bars for ``company`` and its sector
    benchmark, compute the measured facts, and return an unattached
    MarketMove row (caller must set alert_id and session.add it). Never
    raises -- any missing upstream data produces measurement_status=
    'no_data' with null metric columns rather than a fabricated number or
    a crashed alert.
    """
    benchmark_ticker = benchmark_ticker_for_sector(company.sector)
    company_bars = fetch_daily_bars(company.ticker, period="2mo")
    benchmark_bars = fetch_daily_bars(benchmark_ticker, period="2mo")

    if not company_bars:
        return MarketMove(
            company_id=company.id, benchmark_ticker=benchmark_ticker,
            measurement_status="no_data", measured_at=utcnow(),
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
        )

    day_volume = company_bars[-1]["volume"]
    trailing = [b["volume"] for b in company_bars[-21:-1]]  # 20 days before today
    avg_volume_20d = (sum(trailing) / len(trailing)) if trailing else None
    volume_multiple = compute_volume_multiple(day_volume, avg_volume_20d)

    return MarketMove(
        company_id=company.id,
        raw_move_pct=raw_move_pct,
        sector_move_pct=sector_move_pct,
        benchmark_ticker=benchmark_ticker,
        excess_move_pct=compute_excess_move_pct(raw_move_pct, sector_move_pct),
        volume=day_volume,
        avg_volume_20d=avg_volume_20d,
        volume_multiple=volume_multiple,
        # delivery_pct deliberately left NULL -- no real NSE delivery-data
        # source is wired yet; intensity renormalizes without it rather
        # than fabricating (spec v2 §4.2 + Ground Rules).
        vol_normalized=compute_vol_normalized(raw_move_pct, company_bars),
        materiality=compute_materiality(
            company_bars[-1]["close"], day_volume, avg_volume_20d, company.market_cap,
        ),
        avg_traded_value=compute_avg_traded_value(company_bars),
        measured_at=utcnow(),
        measurement_status="ok",
    )
