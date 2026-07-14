from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.calibration.track_record import get_win_rate
from app.companies.history import get_company_history_page
from app.companies.market import infer_market
from app.companies.price_series import fetch_price_series
from app.config import settings
from app.i18n import get_lang
from app.models import Alert, AlertCompany, Article, Company
from app.pipeline import decode_key_points
from app.routers.articles import get_db
from app.translation.lookup import bulk_alert_company_translations, bulk_article_titles, bulk_category_labels

router = APIRouter(prefix="/api/companies", tags=["companies"])

PRICE_SERIES_PERIODS = {"1mo", "3mo", "6mo", "1y"}


def _logo_url(company: Company) -> str | None:
    if not settings.brandfetch_client_id:
        return None
    if company.isin:
        return f"https://cdn.brandfetch.io/isin/{company.isin}?c={settings.brandfetch_client_id}"
    return f"https://cdn.brandfetch.io/ticker/{company.ticker}?c={settings.brandfetch_client_id}"


def _get_indian_company_or_404(db: Session, company_id: int) -> Company:
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None or infer_market(company.ticker) != "IN":
        raise HTTPException(404, "Company not found")
    return company


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


@router.get("/{company_id}/profile")
def get_company_profile(company_id: int, db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    # Public reference data (no auth) restricted to Indian/Nifty companies --
    # this feature isn't built out for GLOBAL_LARGE_CAP companies yet.
    company = _get_indian_company_or_404(db, company_id)

    latest = (
        db.query(AlertCompany, Alert, Article)
        .join(Alert, AlertCompany.alert_id == Alert.id)
        .join(Article, Alert.article_id == Article.id)
        .filter(AlertCompany.company_id == company_id)
        .order_by(Alert.created_at.desc())
        .first()
    )
    latest_alert = None
    if latest is not None:
        ac, alert, article = latest
        rationale, key_points = bulk_alert_company_translations(db, [ac.id], lang).get(
            ac.id, (ac.rationale, decode_key_points(ac)),
        )
        category_label = bulk_category_labels(db, [alert.category], lang).get(alert.category, alert.category)
        title = bulk_article_titles(db, [article.id], lang).get(article.id, article.title)
        latest_alert = {
            "alert_id": alert.id,
            "created_at": alert.created_at.isoformat(),
            "direction": ac.direction,
            "rationale": rationale,
            "key_points": key_points,
            "confidence": ac.confidence,
            "category": alert.category,
            "category_label": category_label,
            "article": {"id": article.id, "title": title, "url": article.url, "image_url": article.image_url},
        }

    return {
        "id": company.id, "ticker": company.ticker, "name": company.name,
        "sector": company.sector, "index_tier": company.index_tier, "market": "IN",
        "isin": company.isin, "logo_url": _logo_url(company),
        "latest_alert": latest_alert,
        "track_record": get_win_rate(db, company_id),
    }


@router.get("/{company_id}/history")
def get_company_history(company_id: int, before: str | None = None, limit: int = 20, db: Session = Depends(get_db)):
    _get_indian_company_or_404(db, company_id)
    if before is not None:
        try:
            datetime.fromisoformat(before)
        except ValueError:
            raise HTTPException(400, "Invalid `before` cursor")
    page = get_company_history_page(db, company_id, before=before, limit=limit)
    return {"mentions": page["items"], "has_more": page["has_more"]}


@router.get("/{company_id}/prices")
def get_company_prices(company_id: int, period: str = "6mo", db: Session = Depends(get_db)):
    company = _get_indian_company_or_404(db, company_id)
    if period not in PRICE_SERIES_PERIODS:
        raise HTTPException(400, f"Invalid period, must be one of {sorted(PRICE_SERIES_PERIODS)}")
    points = fetch_price_series(company.ticker, period)
    return {"period": period, "points": points or [], "available": points is not None}
