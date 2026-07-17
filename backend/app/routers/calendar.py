from collections import Counter
from datetime import date as date_cls

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import get_current_user_optional
from app.companies.history import bulk_past_mentions
from app.i18n import get_lang
from app.ist_time import day_utc_window, month_utc_window, to_ist_date
from app.models import Alert, AlertCompany, User
from app.routers.alerts import _held_company_ids, _serialize_alert
from app.routers.articles import get_db
from app.translation.lookup import bulk_alert_company_translations, bulk_article_titles, bulk_category_labels

router = APIRouter(prefix="/api/calendar", tags=["calendar"])

# A single day's news realistically never approaches this, but it mirrors
# ALERTS_LIMIT in routers/alerts.py as a defensive cap rather than leaving
# the day endpoint fully unbounded.
DAY_ALERTS_LIMIT = 200


@router.get("/counts")
def get_calendar_counts(year: int, month: int, db: Session = Depends(get_db)):
    if not 1 <= month <= 12:
        raise HTTPException(status_code=400, detail="month must be between 1 and 12")
    start_utc, end_utc = month_utc_window(year, month)
    rows = (
        db.query(Alert.created_at)
        .filter(Alert.created_at >= start_utc, Alert.created_at < end_utc)
        .all()
    )
    counts: Counter[str] = Counter()
    for (created_at,) in rows:
        counts[to_ist_date(created_at).isoformat()] += 1
    return dict(counts)


@router.get("/day")
def get_calendar_day(
    date: str,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
    lang: str = Depends(get_lang),
):
    try:
        day = date_cls.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")

    start_utc, end_utc = day_utc_window(day)
    alerts = (
        db.query(Alert)
        .options(
            selectinload(Alert.article),
            selectinload(Alert.companies).selectinload(AlertCompany.company),
        )
        .filter(Alert.created_at >= start_utc, Alert.created_at < end_utc)
        .order_by(Alert.created_at.desc())
        .limit(DAY_ALERTS_LIMIT)
        .all()
    )

    held_company_ids = _held_company_ids(db, current_user)
    article_titles = bulk_article_titles(db, [a.article_id for a in alerts], lang)
    ac_translations = bulk_alert_company_translations(
        db, [ac.id for a in alerts for ac in a.companies], lang
    )
    category_labels = bulk_category_labels(db, list({a.category for a in alerts}), lang)
    mentions_index = bulk_past_mentions(db, {ac.company_id for a in alerts for ac in a.companies})

    return [
        _serialize_alert(alert, held_company_ids, article_titles, ac_translations, category_labels, mentions_index)
        for alert in alerts
    ]
