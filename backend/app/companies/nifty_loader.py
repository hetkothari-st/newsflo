from sqlalchemy.orm import Session

from app.companies.loader import _normalize_sector
from app.companies.nifty_indices_seed import CAP_TIER_COMPANIES, EXTRA_COMPANIES, INDEX_MEMBERSHIPS
from app.models import Company, CompanyIndexMembership

# Membership rows for these two are cross-checked directly against NSE's own
# ind_nifty100list.csv / ind_nifty500list.csv, not derived from the four cap
# tiers, so they are recorded exactly like every other index code.
_CAP_TIER_CODES = {"NIFTY50", "NIFTYNEXT50", "NIFTYMIDCAP150", "NIFTYSMALLCAP250"}


def _upsert_company(session: Session, ticker: str, name: str, industry: str, isin: str, index_tier: str) -> Company:
    sector = _normalize_sector(industry)
    existing = session.query(Company).filter_by(ticker=ticker).one_or_none()
    if existing:
        existing.name = name
        existing.sector = sector
        existing.isin = isin
        if index_tier in _CAP_TIER_CODES or existing.index_tier is None:
            existing.index_tier = index_tier
        return existing
    company = Company(ticker=ticker, name=name, sector=sector, index_tier=index_tier, isin=isin, market_cap=None)
    session.add(company)
    session.flush()
    return company


def _add_membership(session: Session, company_id: int, index_code: str) -> bool:
    existing = (
        session.query(CompanyIndexMembership)
        .filter_by(company_id=company_id, index_code=index_code)
        .one_or_none()
    )
    if existing:
        return False
    session.add(CompanyIndexMembership(company_id=company_id, index_code=index_code))
    return True


def load_nifty_indices(session: Session) -> dict:
    """Upsert every company from every Nifty index seed list, and record
    full index membership (a company can be in many indices at once).

    Cap-tier indices (NIFTY50/NIFTYNEXT50/NIFTYMIDCAP150/NIFTYSMALLCAP250)
    additionally set Company.index_tier -- the single "broadest tier" used
    by resolution.py's sector-inference ranking. Every other index only
    adds a CompanyIndexMembership row. EXTRA_COMPANIES (sectoral-only,
    outside the Nifty 500 cap-tier universe) get index_tier="OTHER".
    """
    ticker_by_symbol: dict[str, str] = {}
    company_count = 0

    for tier, rows in CAP_TIER_COMPANIES.items():
        for row in rows:
            symbol = row["ticker"][:-3]  # strip ".NS"
            ticker_by_symbol[symbol] = row["ticker"]
            _upsert_company(session, row["ticker"], row["name"], row["industry"], row["isin"], tier)
            company_count += 1

    for row in EXTRA_COMPANIES:
        symbol = row["ticker"][:-3]
        ticker_by_symbol[symbol] = row["ticker"]
        _upsert_company(session, row["ticker"], row["name"], row["industry"], row["isin"], "OTHER")
        company_count += 1

    membership_count = 0
    for index_code, symbols in INDEX_MEMBERSHIPS.items():
        for symbol in symbols:
            ticker = ticker_by_symbol.get(symbol)
            if ticker is None:
                continue
            company = session.query(Company).filter_by(ticker=ticker).one()
            if _add_membership(session, company.id, index_code):
                membership_count += 1

    session.commit()
    return {"companies": company_count, "memberships": membership_count}
