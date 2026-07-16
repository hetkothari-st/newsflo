"""Grounds AI reasoning in real financial data and detects when reasoning
contradicts actual recent price momentum. See docs/superpowers/specs/
2026-07-16-financial-grounding-contradiction-detection-design.md.

fetch_financial_snapshot and detect_price_contradiction are pure (no DB, no
Session) -- get_or_fetch_financial_snapshot (added in a later task) is the
DB-backed caching layer on top, mirroring how app.calibration.blender mixes
pure and DB-dependent functions in one small file.
"""

from datetime import timedelta

from app.companies.price_series import fetch_price_series
from app.models import FinancialSnapshot, utcnow
from app.outcomes.price_fetcher import fetch_price_change_pct
from sqlalchemy.orm import Session

# How large a mismatch between reasoning direction and actual 1-month price
# momentum counts as a real contradiction, not normal noise. Named constant,
# not inlined, so it can be retuned like the Confidence Engine's weights.
CONTRADICTION_THRESHOLD_PCT = 5.0


def fetch_financial_snapshot(ticker: str) -> dict | None:
    """Fetch {"price", "return_1m", "return_3m"} for `ticker`, backward-
    looking from now. Returns None only if the current price itself is
    unavailable (a snapshot with no price is useless); a missing individual
    return degrades to None for that field alone -- same "never raise,
    degrade to None" contract as every other yfinance-touching function in
    this codebase.
    """
    series = fetch_price_series(ticker, period="5d")
    if not series:
        return None
    price = series[-1]["close"]

    return_1m = fetch_price_change_pct(ticker, utcnow() - timedelta(days=30), 30)
    return_3m = fetch_price_change_pct(ticker, utcnow() - timedelta(days=90), 90)

    return {"price": price, "return_1m": return_1m, "return_3m": return_3m}


def detect_price_contradiction(direction: str, return_1m: float | None) -> str | None:
    """Returns a human-readable contradiction note, or None if there is no
    contradiction -- including when return_1m is unavailable (absence of
    data is not evidence of a contradiction) or direction is anything other
    than "bullish"/"bearish".
    """
    if return_1m is None:
        return None
    if direction == "bullish" and return_1m <= -CONTRADICTION_THRESHOLD_PCT:
        return f"Price down {abs(return_1m):.1f}% over the past month despite bullish call."
    if direction == "bearish" and return_1m >= CONTRADICTION_THRESHOLD_PCT:
        return f"Price up {return_1m:.1f}% over the past month despite bearish call."
    return None


# How long a cached snapshot stays fresh before a company's price/return
# data is refetched.
SNAPSHOT_CACHE_HOURS = 1


def _as_aware_utc(dt):
    """SQLite (used by the test suite) silently drops tzinfo on
    ``DateTime(timezone=True)`` columns when a row is reloaded after commit
    -- Postgres (production) does not have this quirk. Mirrors
    app.pipeline._as_aware_utc -- duplicated rather than imported to avoid a
    circular import (app.pipeline imports this module).
    """
    from datetime import timezone
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def get_or_fetch_financial_snapshot(session: Session, ticker: str) -> dict | None:
    """Cache-then-fetch: reuse a FinancialSnapshot row younger than
    SNAPSHOT_CACHE_HOURS, otherwise fetch fresh and upsert. If a fresh fetch
    fails but a stale cached row exists, the stale data is returned rather
    than dropping the Facts block entirely for one bad fetch cycle. Returns
    None only when there is no cached row AND the fetch failed.
    """
    existing = session.query(FinancialSnapshot).filter_by(ticker=ticker).one_or_none()
    if existing is not None:
        age_hours = (utcnow() - _as_aware_utc(existing.fetched_at)).total_seconds() / 3600
        if age_hours < SNAPSHOT_CACHE_HOURS:
            return {"price": existing.price, "return_1m": existing.return_1m, "return_3m": existing.return_3m}

    fresh = fetch_financial_snapshot(ticker)
    if fresh is None:
        if existing is not None:
            return {"price": existing.price, "return_1m": existing.return_1m, "return_3m": existing.return_3m}
        return None

    if existing is not None:
        existing.price = fresh["price"]
        existing.return_1m = fresh["return_1m"]
        existing.return_3m = fresh["return_3m"]
        existing.fetched_at = utcnow()
    else:
        session.add(FinancialSnapshot(
            ticker=ticker, price=fresh["price"], return_1m=fresh["return_1m"],
            return_3m=fresh["return_3m"], fetched_at=utcnow(),
        ))
    session.flush()

    return fresh
