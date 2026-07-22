"""Deterministic market-measurement service -- the spine of the app
(docs/NEWS_IMPACT_APP_SPEC.md §3-§5). Every function here is arithmetic
over price/volume bars; nothing calls an LLM. Built on
app.companies.price_series.fetch_daily_bars and
app.market.sector_indices.benchmark_ticker_for_sector.
"""
from sqlalchemy.orm import Session

from app.companies.price_series import fetch_daily_bars
from app.market.sector_indices import benchmark_ticker_for_sector
from app.models import Company, MarketMove, utcnow


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
    series, or None if fewer than 2 points exist or the prior close is 0."""
    if len(bars) < 2:
        return None
    prev_close = bars[-2]["close"]
    last_close = bars[-1]["close"]
    if not prev_close:
        return None
    return (last_close - prev_close) / prev_close * 100


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

    if not company_bars or not benchmark_bars:
        return MarketMove(
            company_id=company.id, benchmark_ticker=benchmark_ticker,
            measurement_status="no_data", measured_at=utcnow(),
        )

    raw_move_pct = _daily_return_pct(company_bars)
    sector_move_pct = _daily_return_pct(benchmark_bars)
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
        measured_at=utcnow(),
        measurement_status="ok",
    )
