"""Raw Pulse-by-Zerodha live feed: the pulse_zerodha articles exactly as
ingested, newest first. NO LLM anywhere in this path -- no relevance
gate, no analysis, no Gemini, no Groq: a plain DB read over rows the
ingestion collector already wrote. Curation is Pulse's own; dedup against
the other sources already happened at ingestion (collector idempotency
tiers).

Day-scoped (IST): the live tab shows ONE day's wire -- the requested
?date=, or the latest day that has items. Back days are listed by
/dates for the archive. Pulse is Indian-market news, so days cut at
IST midnight, not UTC."""
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.models import Article
from app.routers.articles import get_db

router = APIRouter(prefix="/api/pulse-live", tags=["pulse-live"])

IST = timezone(timedelta(hours=5, minutes=30))

# How far back the archive lists pulse days. The wire is high-volume and
# upstream of analysis -- a bounded window, not an unbounded scan.
DATES_WINDOW_DAYS = 45


def _ist_day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=IST)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def _ist_date(moment: datetime) -> date:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(IST).date()


def _pulse_query(db: Session):
    return db.query(Article).filter(Article.provider == "pulse_zerodha")


@router.get("/dates")
def pulse_dates(db: Session = Depends(get_db)):
    """IST days that have pulse items, newest first, with counts -- the
    archive's pulse-wire index. Bounded to DATES_WINDOW_DAYS."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=DATES_WINDOW_DAYS)
    rows = (
        _pulse_query(db)
        .filter(Article.published_at.isnot(None), Article.published_at >= cutoff)
        .with_entities(Article.published_at)
        .all()
    )
    counts = Counter(_ist_date(published_at).isoformat() for (published_at,) in rows)
    return [
        {"date": day, "count": counts[day]}
        for day in sorted(counts, reverse=True)
    ]


@router.get("")
def pulse_live(
    date_param: str | None = Query(default=None, alias="date"),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """One IST day of the wire: the requested ?date=, or the latest day
    that has any items (never a multi-day mix -- the tab is 'today's
    paper', back days live in the archive)."""
    if date_param is not None:
        try:
            day = date.fromisoformat(date_param)
        except ValueError:
            raise HTTPException(400, "Invalid date, expected YYYY-MM-DD")
    else:
        newest = (
            _pulse_query(db)
            .filter(Article.published_at.isnot(None))
            .order_by(Article.published_at.desc())
            .first()
        )
        if newest is None:
            return []
        day = _ist_date(newest.published_at)

    start, end = _ist_day_bounds(day)
    rows = (
        _pulse_query(db)
        .filter(Article.published_at.isnot(None))
        .filter(Article.published_at >= start, Article.published_at < end)
        .order_by(Article.published_at.desc(), Article.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": row.id,
            "title": row.title,
            "url": row.url,
            "summary": (row.content or "")[:300],
            "published_at": row.published_at.isoformat() if row.published_at else None,
            "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
            "image_url": row.image_url or None,  # "" = scrape attempted, no image found
        }
        for row in rows
    ]
