from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from app.models import Article

INDIANAPI_NEWS_URL = "https://stock.indianapi.in/news"
FETCH_TIMEOUT_SECONDS = 10

# IndianAPI's pub_date has no timezone offset (e.g. "2026-07-17T10:43:00") --
# every source it aggregates (Financial Express, LiveMint, Economic Times,
# etc.) is an Indian publication, so that's always IST wall-clock time, not
# naive UTC.
IST = timezone(timedelta(hours=5, minutes=30))


def _parse_pub_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    aware = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=IST)
    return aware.astimezone(timezone.utc)


def fetch_new_indianapi_articles(session: Session, api_key: str) -> int:
    """Poll IndianAPI's /news endpoint (direct Indian financial news --
    Economic Times, LiveMint, Financial Express, etc., pre-aggregated) and
    insert any story not already seen (deduped by url, same convention as
    every other ingestion source in this package).

    IMPORTANT: this key is capped at 500 requests/month -- this function
    must only be called from the low-frequency indianapi_poll_interval_minutes
    scheduler job (see scheduler.py), never from the fast per-minute analysis
    cycle. A request/parse failure never raises -- skip this cycle, retry
    next, same contract as every other ingestion source.
    """
    if not api_key:
        return 0

    try:
        response = httpx.get(
            INDIANAPI_NEWS_URL,
            headers={"x-api-key": api_key},
            timeout=FETCH_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        items = response.json()
    except (httpx.HTTPError, ValueError):
        return 0

    if not isinstance(items, list):
        return 0

    inserted = 0
    for item in items:
        url = item.get("url")
        if not url:
            continue
        if session.query(Article).filter_by(url=url).one_or_none():
            continue
        session.add(Article(
            source=item.get("source") or "indianapi",
            url=url,
            title=item.get("title", ""),
            content=item.get("summary", ""),
            published_at=_parse_pub_date(item.get("pub_date")),
            image_url=item.get("image_url"),
            status="NEW",
        ))
        inserted += 1
    session.commit()
    return inserted
