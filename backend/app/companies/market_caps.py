"""Market-cap refresh (spec v2 §4.5): Company.market_cap is the input to
the AMFI-style cap-tier ranking that drives every LARGE/MID/SMALL/MICRO
tag and the feed's cap filter. Fetched from yfinance; caps go stale, so
the tier RANKING recomputes on every read (app.market.cap_tier) while the
raw caps refresh here on a schedule.

Same "never raise, degrade to skip" contract as the rest of the market
plumbing -- a single ticker's failed fetch never blocks the batch.
"""
import math
from datetime import date, timedelta

import yfinance as yf
from sqlalchemy.orm import Session

from app import config
from app.models import Alert, AlertCompany, Company, utcnow


def fetch_market_cap(ticker: str) -> float | None:
    """Live market cap for one ticker, or None on any failure."""
    try:
        value = yf.Ticker(ticker).fast_info["marketCap"]
        if value is None:
            return None
        value = float(value)
        if not math.isfinite(value) or value <= 0:
            return None
        return value
    except Exception:
        return None


def refresh_market_caps(session: Session, tickers: list[str], today: date | None = None) -> int:
    """Fetch + persist market caps for ``tickers``. Returns how many
    companies were updated. A failed fetch keeps the previous value (a
    stale cap beats a nulled-out tier).

    yfinance is the FALLBACK source (spec §6.2). The primary is BSE's
    published Mktcap, loaded in bulk by the universe ingest. A fresh
    exchange-published cap is never overwritten by a scraped one -- only a
    stale one is, and the replacement is labelled so
    app.market.cap_tier.resolve_cap_tier can report where the number came
    from.
    """
    today = today or date.today()
    updated = 0
    for ticker in tickers:
        company = session.query(Company).filter_by(ticker=ticker).one_or_none()
        if company is None:
            continue
        if (
            company.market_cap_source == "BSE"
            and company.market_cap_as_of is not None
            and (today - company.market_cap_as_of).days <= config.MARKET_CAP_MAX_AGE_DAYS
        ):
            continue
        cap = fetch_market_cap(ticker)
        if cap is None:
            continue
        company.market_cap = cap
        company.market_cap_source = "yfinance"
        company.market_cap_as_of = today
        session.commit()
        updated += 1
    return updated


def alert_referenced_tickers(session: Session, days: int = 7) -> list[str]:
    """Tickers of every company attached to an alert in the last ``days``
    days -- the working set whose cap tags users actually see."""
    cutoff = utcnow() - timedelta(days=days)
    rows = (
        session.query(Company.ticker)
        .join(AlertCompany, AlertCompany.company_id == Company.id)
        .join(Alert, AlertCompany.alert_id == Alert.id)
        .filter(Alert.created_at >= cutoff)
        .distinct()
        .all()
    )
    return [ticker for (ticker,) in rows]
