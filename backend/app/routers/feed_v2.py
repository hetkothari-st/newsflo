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

from app.auth.dependencies import get_current_user_optional
from app.ist_time import day_utc_window, today_ist
from app.market.alert_measurement import compute_alert_measurement
from app.models import Alert, AlertCompany, Holding, User
from app.routers.articles import get_db

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

    results = []
    for alert in alerts:
        measurement = compute_alert_measurement(db, alert)
        if measurement is not None:
            results.append(_serialize(alert, measurement, held_company_ids))
    return results


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
    return _serialize(alert, measurement, held_company_ids)
