"""Intraday market-cap overlay for the Directory ranking: live LTP x
Company.shares_outstanding when a fresh Kite tick and a known share count
both exist; the stored Company.market_cap otherwise. Every value carries
its source label so a stale or missing input is never dressed up as live
(the app-wide never-fabricate rule).

Pure read layer: consumes LIVE_PRICE_CACHE (written by kite_ws_client)
and Company rows; writes nothing.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app import config
from app.models import Company
from app.prices.live_price import LIVE_PRICE_CACHE


@dataclass(frozen=True)
class LiveCap:
    ticker: str
    market_cap: float
    source: str  # 'live' | 'stored'
    as_of: datetime | None  # tick time for live rows, None for stored


def _tick_is_fresh(as_of: datetime, now: datetime) -> bool:
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    return now - as_of <= timedelta(minutes=config.LIVE_CAP_TICK_MAX_AGE_MINUTES)


def compute_live_cap(company: Company, now: datetime | None = None) -> LiveCap | None:
    """One company's current best-honest cap. None when it has no stored
    cap at all (nothing truthful to rank it by)."""
    now = now or datetime.now(timezone.utc)
    tick = (
        LIVE_PRICE_CACHE.get(company.instrument_token)
        if company.instrument_token is not None
        else None
    )
    if (
        tick is not None
        and company.shares_outstanding is not None
        and _tick_is_fresh(tick["as_of"], now)
    ):
        return LiveCap(
            ticker=company.ticker,
            market_cap=tick["ltp"] * company.shares_outstanding,
            source="live",
            as_of=tick["as_of"],
        )
    if company.market_cap is not None:
        return LiveCap(ticker=company.ticker, market_cap=company.market_cap, source="stored", as_of=None)
    return None


def rank_live_caps(session: Session, now: datetime | None = None) -> list[LiveCap]:
    """Every rankable company, best-honest cap each, sorted (cap desc,
    ticker asc) -- the same pool AND total order app.market.cap_tier uses
    (India-only, non-null cap), so ranks stay consistent with the
    LARGE/MID/SMALL/MICRO tags shown beside them. The India filter is
    load-bearing beyond tier parity: curated GLOBAL rows store their cap
    in the listing currency (USD), and ranking raw USD against INR would
    both skew every rank and print dollar figures as rupees."""
    now = now or datetime.now(timezone.utc)
    companies = (
        session.query(Company)
        .filter(Company.market == "INDIA", Company.market_cap.isnot(None))
        .all()
    )
    caps = [cap for company in companies if (cap := compute_live_cap(company, now)) is not None]
    caps.sort(key=lambda c: (-c.market_cap, c.ticker))
    return caps
