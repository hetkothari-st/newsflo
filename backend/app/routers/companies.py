from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.calibration.track_record import get_win_rate
from app.companies.branding import logo_url as _logo_url
from app.companies.descriptions import sourced_description
from app.companies.fundamentals import fundamentals_payload
from app.companies.history import get_company_history_page
from app.companies.market import infer_market
from app.companies.price_series import fetch_price_series
from app.i18n import get_lang
from app.market.cap_tier import resolve_cap_tier
from app.models import Alert, AlertCompany, Article, Company, CompanyIndexMembership, Listing, MarketMove
from app.pipeline import decode_key_points
from app.prices.live_cap import compute_live_cap
from app.prices.live_price import LIVE_PRICE_CACHE, compute_change_pct, get_previous_close
from app.routers.articles import get_db
from app.translation.lookup import bulk_alert_company_translations, bulk_article_titles, bulk_category_labels

router = APIRouter(prefix="/api/companies", tags=["companies"])

PRICE_SERIES_PERIODS = {"1mo", "3mo", "6mo", "1y", "5y"}


def _get_indian_company_or_404(db: Session, company_id: int) -> Company:
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None or infer_market(company.ticker) != "IN":
        raise HTTPException(404, "Company not found")
    return company


def _get_company_or_404(db: Session, company_id: int) -> Company:
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
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
            "sector": c.sector, "sub_sector": c.sub_sector, "index_tier": c.index_tier, "market": c_market,
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
        "sector": company.sector, "sub_sector": company.sub_sector,
        "index_tier": company.index_tier, "market": "IN",
        "isin": company.isin, "logo_url": _logo_url(company),
        "latest_alert": latest_alert,
        "track_record": get_win_rate(db, company_id),
    }


# How many measured news entries the dossier carries inline; the page can
# grow the list via the existing /history endpoint if ever needed.
DOSSIER_NEWS_LIMIT = 12


@router.get("/by-ticker/{ticker}/dossier")
def get_company_dossier(ticker: str, db: Session = Depends(get_db)):
    """Everything real we know about one company, in one payload -- the
    v4 Directory's full-page company report. Every section is sourced:
    exchange listings, index memberships, BSE fundamentals, the sourced
    (attributed) description, this company's own measured news record,
    and the prediction track record. A missing ingredient is null/empty
    -- the page hides that section, never fills it in.

    Three segments, so it can never collide with the int-typed
    /{company_id}/... routes above. Public reference data, no auth."""
    company = db.query(Company).filter(Company.ticker == ticker).one_or_none()
    if company is None:
        raise HTTPException(404, "Company not found")

    listings = (
        db.query(Listing)
        .filter(Listing.company_id == company.id)
        .order_by(Listing.exchange.asc())
        .all()
    )
    indices = [
        code
        for (code,) in db.query(CompanyIndexMembership.index_code)
        .filter(CompanyIndexMembership.company_id == company.id)
        .order_by(CompanyIndexMembership.index_code.asc())
        .all()
    ]

    # Measured news record: every alert that touched this company, with
    # the REAL measured reaction where one exists (MarketMove outer join
    # -- an unmeasured mention still appears, with a null move).
    news_rows = (
        db.query(Alert, Article, AlertCompany, MarketMove)
        .join(AlertCompany, AlertCompany.alert_id == Alert.id)
        .join(Article, Alert.article_id == Article.id)
        .outerjoin(
            MarketMove,
            (MarketMove.alert_id == Alert.id) & (MarketMove.company_id == company.id),
        )
        .filter(AlertCompany.company_id == company.id)
        .order_by(Alert.created_at.desc())
        .limit(DOSSIER_NEWS_LIMIT)
        .all()
    )
    # One row per alert: historical duplicates (an alert holding two
    # AlertCompany rows for the same company) must not double a headline.
    news = []
    seen_alert_ids: set[int] = set()
    for alert, article, ac, move in news_rows:
        if alert.id in seen_alert_ids:
            continue
        seen_alert_ids.add(alert.id)
        news.append({
            "alert_id": alert.id,
            "title": article.title,
            "url": article.url,
            "created_at": alert.created_at.isoformat(),
            "category": alert.category,
            "direction": ac.direction,
            "excess_move_pct": (
                move.excess_move_pct
                if move is not None and move.measurement_status == "ok"
                else None
            ),
        })

    desc_text, desc_url = sourced_description(company)
    cap_tier = resolve_cap_tier(db, company)
    live_cap = compute_live_cap(company)
    return {
        "id": company.id,
        "ticker": company.ticker,
        "name": company.name,
        "sector": company.sector,
        "sub_sector": company.sub_sector,
        "isin": company.isin,
        "logo_url": _logo_url(company),
        "cap_tier": cap_tier.tier if cap_tier else None,
        "listings": [
            {
                "exchange": listing.exchange,
                "symbol": listing.symbol,
                "scrip_code": listing.scrip_code,
                "series": listing.series,
                "group_code": listing.group_code,
                "status": listing.status,
                "face_value": listing.face_value,
                "listed_on": listing.listed_on.isoformat() if listing.listed_on else None,
            }
            for listing in listings
        ],
        "indices": indices,
        "fundamentals": fundamentals_payload(company),
        "business_desc": desc_text,
        "business_desc_source_url": desc_url,
        "market_cap": live_cap.market_cap if live_cap else None,
        "market_cap_source": live_cap.source if live_cap else None,
        "news": news,
        "track_record": get_win_rate(db, company.id),
        # Sourced enrichment (history / recent developments) -- filled by
        # the company-profile pipeline; null until then, section hidden.
        "history_text": None,
        "history_source_url": None,
        "developments_text": None,
        "developments_source_url": None,
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
    company = _get_company_or_404(db, company_id)
    if period not in PRICE_SERIES_PERIODS:
        raise HTTPException(400, f"Invalid period, must be one of {sorted(PRICE_SERIES_PERIODS)}")
    points = fetch_price_series(company.ticker, period)
    return {"period": period, "points": points or [], "available": points is not None}


@router.get("/{company_id}/live-price")
def get_company_live_price(company_id: int, response: Response, db: Session = Depends(get_db)):
    # This is a polling endpoint (frontend refetches every few seconds) --
    # without this, browsers can silently serve a stale cached response to
    # repeat fetch() calls against the same URL, freezing the displayed
    # price until a hard reload.
    response.headers["Cache-Control"] = "no-store"
    company = _get_indian_company_or_404(db, company_id)
    entry = LIVE_PRICE_CACHE.get(company.instrument_token) if company.instrument_token else None
    if entry is None:
        return {"ltp": None, "change_pct": None, "as_of": None, "available": False}

    points = fetch_price_series(company.ticker, "5d") or []
    previous_close = get_previous_close(points)
    return {
        "ltp": entry["ltp"],
        "change_pct": compute_change_pct(entry["ltp"], previous_close),
        "as_of": entry["as_of"].isoformat(),
        "available": True,
    }
