from collections import Counter
from datetime import date as date_cls, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import get_current_user_optional
from app.companies.history import bulk_past_mentions
from app.i18n import get_lang
from app.models import Alert, AlertCompany, User
from app.pipeline import _as_aware_utc
from app.routers.alerts import _held_company_ids, _serialize_alert
from app.routers.articles import get_db
from app.translation.lookup import bulk_alert_company_translations, bulk_article_titles, bulk_category_labels

router = APIRouter(prefix="/api/calendar", tags=["calendar"])

# The app is India-focused (RSS sources, trading calendar) -- calendar days
# are always bucketed by IST regardless of viewer location, not the
# viewer's browser timezone. Alert.created_at is stored in UTC.
IST = timezone(timedelta(hours=5, minutes=30))

# A single day's news realistically never approaches this, but it mirrors
# ALERTS_LIMIT in routers/alerts.py as a defensive cap rather than leaving
# the day endpoint fully unbounded.
DAY_ALERTS_LIMIT = 200


def _month_utc_window(year: int, month: int) -> tuple[datetime, datetime]:
    """UTC [start, end) covering every instant that falls in IST calendar
    month `year`-`month`, so a single UTC-range query can't miss alerts
    created near the IST month boundary."""
    if not 1 <= month <= 12:
        raise HTTPException(status_code=400, detail="month must be between 1 and 12")
    start_ist = datetime(year, month, 1, tzinfo=IST)
    end_ist = datetime(year + 1, 1, 1, tzinfo=IST) if month == 12 else datetime(year, month + 1, 1, tzinfo=IST)
    return start_ist.astimezone(timezone.utc), end_ist.astimezone(timezone.utc)


def _day_utc_window(day: date_cls) -> tuple[datetime, datetime]:
    start_ist = datetime(day.year, day.month, day.day, tzinfo=IST)
    return start_ist.astimezone(timezone.utc), (start_ist + timedelta(days=1)).astimezone(timezone.utc)


def _to_ist_date(created_at: datetime) -> date_cls:
    # SQLite round-trips DateTime(timezone=True) columns as naive values
    # (confirmed: Alert.created_at comes back with tzinfo=None even though
    # it was written as an aware UTC datetime) -- .astimezone() on a naive
    # datetime assumes it's already in the *system's local* timezone, which
    # silently no-ops on a server whose local tz happens to be IST. Same
    # SQLite quirk _as_aware_utc exists for in app.pipeline; reuse it rather
    # than re-deriving the same fix here.
    return _as_aware_utc(created_at).astimezone(IST).date()


@router.get("/counts")
def get_calendar_counts(year: int, month: int, db: Session = Depends(get_db)):
    start_utc, end_utc = _month_utc_window(year, month)
    rows = (
        db.query(Alert.created_at)
        .filter(Alert.created_at >= start_utc, Alert.created_at < end_utc)
        .all()
    )
    counts: Counter[str] = Counter()
    for (created_at,) in rows:
        counts[_to_ist_date(created_at).isoformat()] += 1
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

    start_utc, end_utc = _day_utc_window(day)
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
