from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.companies.market import infer_market
from app.config import settings
from app.models import Company
from app.routers.articles import get_db

router = APIRouter(prefix="/api/companies", tags=["companies"])


def _logo_url(company: Company) -> str | None:
    if not settings.brandfetch_client_id:
        return None
    if company.isin:
        return f"https://cdn.brandfetch.io/isin/{company.isin}?c={settings.brandfetch_client_id}"
    return f"https://cdn.brandfetch.io/ticker/{company.ticker}?c={settings.brandfetch_client_id}"


@router.get("")
def list_companies(market: str | None = None, db: Session = Depends(get_db)):
    # Public reference data (no auth), matching GET /api/articles' pattern.
    # market is computed in Python (not a DB column); for v1 scale a full scan
    # + in-Python filter is fine — no SQL-level LIKE filter needed.
    companies = db.query(Company).order_by(Company.name.asc()).all()
    result = []
    for c in companies:
        c_market = infer_market(c.ticker)
        if market is not None and c_market != market:
            continue
        result.append({
            "id": c.id, "ticker": c.ticker, "name": c.name,
            "sector": c.sector, "index_tier": c.index_tier, "market": c_market,
            "isin": c.isin, "logo_url": _logo_url(c),
        })
    return result
