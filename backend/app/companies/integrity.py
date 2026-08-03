"""Deterministic company-table integrity checks -- no LLM calls.

Two concerns:
1. Demo/seed rows must never resolve into a production alert. Confirmed live:
   SOMETEXTILE.NS ("Demo Textiles Ltd", from seed_feed_v2_demo.py) was
   injected into real alerts by app.companies.resolution's sector fan-out.
2. A company's sub_sector must belong to its own sector's branch of
   app.companies.sub_sectors.SUB_SECTOR_TAXONOMY (see check_sub_sectors,
   added in a later task).
"""
from dataclasses import dataclass
from sqlalchemy.orm import Session

from app.models import Company
from app.companies.sub_sectors import SUB_SECTOR_TAXONOMY

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


@dataclass(frozen=True)
class SubSectorViolation:
    ticker: str
    name: str
    sector: str
    sub_sector: str
    # The sector this sub_sector actually belongs to, when it appears in
    # exactly ONE sector's branch of the taxonomy (so the fix is
    # unambiguous). None when the value is unknown to the taxonomy entirely,
    # or -- not currently possible, but not assumed -- appears under more
    # than one sector.
    correct_sector: str | None


def _sector_owning(sub_sector: str) -> str | None:
    owners = [sector for sector, subs in SUB_SECTOR_TAXONOMY.items() if sub_sector in subs]
    return owners[0] if len(owners) == 1 else None


def check_sub_sectors(session: Session) -> list[SubSectorViolation]:
    """Every company whose sub_sector does not belong to its own sector's
    branch of SUB_SECTOR_TAXONOMY. A NULL sub_sector is not a violation --
    189 rows are legitimately unclassified, and the "other" sector has no
    sub-classification by design (see sub_sectors.py's module docstring).
    """
    violations = []
    rows = session.query(Company).filter(Company.sub_sector.isnot(None)).all()
    for company in rows:
        if company.sub_sector in SUB_SECTOR_TAXONOMY.get(company.sector, []):
            continue
        violations.append(SubSectorViolation(
            ticker=company.ticker, name=company.name,
            sector=company.sector, sub_sector=company.sub_sector,
            correct_sector=_sector_owning(company.sub_sector),
        ))
    return violations
