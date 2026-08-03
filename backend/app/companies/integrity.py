"""Deterministic company-table integrity checks -- no LLM calls.

Two concerns:
1. Demo/seed rows must never resolve into a production alert. Confirmed live:
   SOMETEXTILE.NS ("Demo Textiles Ltd", from seed_feed_v2_demo.py) was
   injected into real alerts by app.companies.resolution's sector fan-out.
2. A company's sub_sector must belong to its own sector's branch of
   app.companies.sub_sectors.SUB_SECTOR_TAXONOMY (see check_sub_sectors,
   added in a later task).
"""
from sqlalchemy.orm import Session

from app.models import Company

# Explicit ticker list rather than a name-pattern heuristic: a substring
# match on "Demo" would also delete a legitimately-named company, and this
# table is production master data.
DEMO_TICKERS = frozenset({"SOMETEXTILE.NS"})


def is_demo_company(ticker: str) -> bool:
    return ticker in DEMO_TICKERS


def delete_demo_companies(session: Session) -> list[str]:
    """Deletes every demo/seed row from `companies`. Returns the tickers
    actually deleted (empty when there were none), so a caller can log a
    real result rather than assuming. Idempotent."""
    rows = session.query(Company).filter(Company.ticker.in_(DEMO_TICKERS)).all()
    deleted = [c.ticker for c in rows]
    for company in rows:
        session.delete(company)
    if deleted:
        session.commit()
    return deleted
