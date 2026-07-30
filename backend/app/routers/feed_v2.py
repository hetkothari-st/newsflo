"""Level 0/1 feed endpoints for the measurement-first UI rebuild
(docs/NEWS_IMPACT_APP_SPEC.md §2, §9) -- a new, parallel set of routes
alongside the existing GET /api/alerts (kept untouched; see this plan's
Global Constraints). Returns only alerts with at least one measured
company (excess_move_pct computed, measurement_status == "ok") -- an
alert with nothing measured has no headline number and is omitted
entirely (Ground Rules: never fabricate, omit rather than invent).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import get_current_user, get_current_user_optional
from app.companies.branding import logo_url
from app.ist_time import day_utc_window, today_ist
from app.market.alert_measurement import compute_alert_measurement
from app.market.discovery import (
    compute_materiality_feed,
    compute_related_to_holdings,
    compute_unusual_activity,
)
from app.market.cap_tier import compute_cap_tiers
from app.market.ripple_layers import compute_ripple_layers
from app.market.timeline_entries import get_timeline_entries
from app.models import Alert, AlertCompany, Company, Holding, User
from app.routers.articles import get_db

# -- COMMENTED OUT (superseded by compute_ripple_layers, spec v2 §5/§7's
# layered card back -- the flat ripple list + separate impact_companies
# split is the old, pre-swipe-card UI's shape):
# from app.market.alert_measurement import compute_impact_companies
# from app.market.ripple import compute_ripple_companies

router = APIRouter(prefix="/api/feed-v2", tags=["feed-v2"])

ALERTS_LIMIT = 200


def _held_company_ids(db: Session, current_user: User | None) -> set[int]:
    if current_user is None:
        return set()
    return {h.company_id for h in db.query(Holding).filter_by(user_id=current_user.id).all()}


def _serialize(alert: Alert, measurement: dict, held_company_ids: set[int]) -> dict:
    in_my_holdings = any(ac.company_id in held_company_ids for ac in alert.companies)
    return {
        "id": alert.id,
        "category": alert.category,
        "created_at": alert.created_at.isoformat(),
        "summary_short": alert.summary_short,
        "summary_long": alert.summary_long,
        "article": {
            "id": alert.article.id,
            "image_url": alert.article.image_url,
            "title": alert.article.title,
            "url": alert.article.url,
            "source": alert.article.source,
            "published_at": alert.article.published_at.isoformat() if alert.article.published_at else None,
        },
        "in_my_holdings": in_my_holdings,
        **measurement,
    }


def _query_with_relations(db: Session):
    return db.query(Alert).options(
        selectinload(Alert.article),
        selectinload(Alert.companies).selectinload(AlertCompany.company),
    )


@router.get("")
def list_feed_v2_alerts(
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    start_utc, end_utc = day_utc_window(today_ist())
    alerts = (
        _query_with_relations(db)
        .filter(Alert.created_at >= start_utc, Alert.created_at < end_utc)
        .order_by(Alert.created_at.desc())
        .limit(ALERTS_LIMIT)
        .all()
    )
    held_company_ids = _held_company_ids(db, current_user)

    # Peak company's cap tier -- drives the top-bar cap filter on the card
    # feed (spec v2 §6: "Provide a cap-tier filter (All / Large / Mid /
    # Small / Micro)") without computing full layers per alert. One ranking
    # pass for the whole list, derived fresh (spec §3.2).
    cap_rows = db.query(Company.ticker, Company.market_cap).filter(Company.market_cap.isnot(None)).all()
    cap_tiers = compute_cap_tiers([(t, c) for t, c in cap_rows])

    results = []
    for alert in alerts:
        measurement = compute_alert_measurement(db, alert)
        if measurement is not None:
            row = _serialize(alert, measurement, held_company_ids)
            row["peak_cap_tier"] = cap_tiers.get(measurement["peak_ticker"])
            results.append(row)
    return results


# NOTE: static paths (/discovery/..., /portfolio) are declared BEFORE the
# catch-all /{alert_id} route -- FastAPI matches in declaration order, and
# "/portfolio" would otherwise 422 against the int alert_id parser.
@router.get("/discovery/{tab}")
def get_discovery(
    tab: str,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Discovery paths (spec v2 §6): materiality / holdings / unusual.
    Factual framing only -- "most affected by news", never "best to buy"."""
    if tab == "materiality":
        return compute_materiality_feed(db)
    if tab == "holdings":
        return compute_related_to_holdings(db, current_user)
    if tab == "unusual":
        return compute_unusual_activity(db)
    raise HTTPException(status_code=404, detail="Unknown discovery tab")


@router.get("/portfolio")
def get_portfolio_overlay(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Portfolio overlay (spec v2 §2 portfolio dot / §8): the user's
    holdings and which of today's alerts touches each. Requires login --
    holdings are sensitive (spec §9)."""
    start_utc, end_utc = day_utc_window(today_ist())
    holdings = (
        db.query(Holding, Company)
        .join(Company, Holding.company_id == Company.id)
        .filter(Holding.user_id == current_user.id)
        .order_by(Company.name.asc())
        .all()
    )
    todays_alert_companies = (
        db.query(AlertCompany, Alert)
        .join(Alert, AlertCompany.alert_id == Alert.id)
        .filter(Alert.created_at >= start_utc, Alert.created_at < end_utc)
        .order_by(Alert.created_at.desc())
        .all()
    )
    latest_alert_by_company_id: dict[int, Alert] = {}
    for alert_company, alert in todays_alert_companies:
        latest_alert_by_company_id.setdefault(alert_company.company_id, alert)

    results = []
    for holding, company in holdings:
        alert = latest_alert_by_company_id.get(company.id)
        results.append({
            "ticker": company.ticker,
            "name": company.name,
            "quantity": holding.quantity,
            "logo_url": logo_url(company),
            "affected_alert_id": alert.id if alert else None,
            "affected_headline": (alert.summary_short or alert.article.title) if alert else None,
        })
    return {
        "holdings": results,
        "affected_count": sum(1 for r in results if r["affected_alert_id"] is not None),
    }


@router.get("/{alert_id}")
def get_feed_v2_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    alert = _query_with_relations(db).filter(Alert.id == alert_id).first()
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    measurement = compute_alert_measurement(db, alert)
    if measurement is None:
        raise HTTPException(status_code=404, detail="Alert has no measured companies")

    held_company_ids = _held_company_ids(db, current_user)
    result = _serialize(alert, measurement, held_company_ids)
    # Layered card back (spec v2 §5/§7): every affected company, grouped by
    # relationship into ordered winners/losers layers.
    result["layers"] = compute_ripple_layers(db, alert, held_company_ids)
    result["timeline"] = get_timeline_entries(db, alert)
    # -- COMMENTED OUT (superseded by result["layers"] above -- the old flat
    # ripple + impact_companies split served the pre-swipe-card UI):
    # result["ripple"] = compute_ripple_companies(
    #     db, alert, exclude_company_id=measurement["peak_company_id"], held_company_ids=held_company_ids,
    # )
    # result["impact_companies"] = compute_impact_companies(db, alert)
    return result
