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

from app.models import (
    AlertCompany,
    AlertCompanyTranslation,
    CalibrationSample,
    CarOutcome,
    Company,
    CompanyIndexMembership,
    EmailNotification,
    Holding,
    ImpactEdge,
    MarketMove,
    UserWatchlistCompany,
)
from app.companies.sub_sectors import SUB_SECTOR_TAXONOMY

# Explicit ticker list rather than a name-pattern heuristic: a substring
# match on "Demo" would also delete a legitimately-named company, and this
# table is production master data.
DEMO_TICKERS = frozenset({"SOMETEXTILE.NS"})

# Tables that reference alert_companies.id via alert_company_id -- must be
# cleared before an about-to-be-deleted alert_companies row, or they become
# orphans themselves (see the docstring below for the incident that found
# this: SOMETEXTILE.NS's own alert_companies rows were left dangling by an
# earlier version of this function, and 7 alert_company_translations rows
# referencing them were themselves one silent step from becoming orphans).
_ALERT_COMPANY_DEPENDENTS = (CalibrationSample, CarOutcome, EmailNotification, AlertCompanyTranslation)


def is_demo_company(ticker: str) -> bool:
    return ticker in DEMO_TICKERS


def delete_demo_companies(session: Session) -> list[str]:
    """Deletes every demo/seed row from `companies`, and every row anywhere
    in the schema that references it -- directly (alert_companies.company_id,
    market_moves.company_id, company_index_memberships.company_id,
    holdings.company_id, user_watchlist_companies.company_id) or via a
    nullable link that should simply be cleared rather than cascade the
    delete further (alert_companies.parent_company_id, impact_edges.
    from_company_id/to_company_id) -- so no foreign key is left dangling.

    An earlier version of this function deleted only the Company row.
    SQLite leaves FK enforcement off by default, so the resulting orphans
    in alert_companies and market_moves were invisible until a later,
    unrelated schema-rebuild script ran `PRAGMA foreign_key_check` for the
    first time and found them (confirmed live: SOMETEXTILE.NS,
    alert_companies rows 858/887, market_moves rows 21/50). This is that
    fix, applied at the root cause instead of cleaned up after the fact.

    Returns the tickers actually deleted (empty when there were none), so a
    caller can log a real result rather than assuming. Idempotent."""
    rows = session.query(Company).filter(Company.ticker.in_(DEMO_TICKERS)).all()
    deleted = [c.ticker for c in rows]
    if not rows:
        return deleted

    company_ids = [c.id for c in rows]

    alert_company_ids = [
        row.id for row in
        session.query(AlertCompany.id).filter(AlertCompany.company_id.in_(company_ids)).all()
    ]

    # Rows that reference this company's own alert_companies rows -- gone
    # before the alert_companies rows themselves.
    if alert_company_ids:
        for model in _ALERT_COMPANY_DEPENDENTS:
            session.query(model).filter(
                model.alert_company_id.in_(alert_company_ids)
            ).delete(synchronize_session=False)

    # Rows that reference the company directly and have nothing else
    # pointing at them -- safe to delete outright.
    session.query(CompanyIndexMembership).filter(
        CompanyIndexMembership.company_id.in_(company_ids)
    ).delete(synchronize_session=False)
    session.query(CalibrationSample).filter(
        CalibrationSample.company_id.in_(company_ids)
    ).delete(synchronize_session=False)
    session.query(CarOutcome).filter(
        CarOutcome.company_id.in_(company_ids)
    ).delete(synchronize_session=False)
    session.query(MarketMove).filter(
        MarketMove.company_id.in_(company_ids)
    ).delete(synchronize_session=False)
    session.query(Holding).filter(
        Holding.company_id.in_(company_ids)
    ).delete(synchronize_session=False)
    session.query(UserWatchlistCompany).filter(
        UserWatchlistCompany.company_id.in_(company_ids)
    ).delete(synchronize_session=False)

    # Nullable references to the company from rows that are otherwise
    # unrelated to it -- cleared, not deleted: an ImpactEdge's own alert may
    # have nothing to do with this company, and an AlertCompany's own
    # company_id may be a real, unrelated company that merely chained its
    # indirect impact off this one.
    session.query(ImpactEdge).filter(ImpactEdge.from_company_id.in_(company_ids)).update(
        {ImpactEdge.from_company_id: None}, synchronize_session=False
    )
    session.query(ImpactEdge).filter(ImpactEdge.to_company_id.in_(company_ids)).update(
        {ImpactEdge.to_company_id: None}, synchronize_session=False
    )
    session.query(AlertCompany).filter(AlertCompany.parent_company_id.in_(company_ids)).update(
        {AlertCompany.parent_company_id: None}, synchronize_session=False
    )

    # Finally, this company's own alert_companies rows, now that everything
    # that referenced THEM has already been removed above.
    session.query(AlertCompany).filter(AlertCompany.company_id.in_(company_ids)).delete(
        synchronize_session=False
    )

    for company in rows:
        session.delete(company)
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
