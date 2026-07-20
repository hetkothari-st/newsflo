from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.models import Article

THENEWSAPI_NEWS_URL = "https://api.thenewsapi.com/v1/news/all"
FETCH_TIMEOUT_SECONDS = 10
# Financially-relevant categories only, for now -- the full generic
# category set (sports, entertainment, health, science, food, travel) is
# deferred until the relevance-filter rework ships (see the design doc's
# "Explicitly out of scope" section); today's narrow keyword filter isn't
# equipped to reject that volume of genuinely irrelevant content cleanly.
CATEGORIES = "business,politics,general,tech"


def _parse_pub_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fetch_new_thenewsapi_articles(session: Session, api_token: str) -> int:
    """Poll thenewsapi.com's /v1/news/all endpoint for new articles across
    CATEGORIES, insert any not already seen (deduped by url, same
    convention as every other ingestion source in this package).

    A request/parse failure never raises -- skip this cycle, retry next,
    same contract as every other ingestion source. A missing api_token
    returns 0 without making a request -- the 100-request/day free-tier
    cap makes an accidental unauthenticated/wasted call worth guarding
    against explicitly, same as fetch_new_indianapi_articles's own key
    check.
    """
    if not api_token:
        return 0

    try:
        response = httpx.get(
            THENEWSAPI_NEWS_URL,
            params={"api_token": api_token, "categories": CATEGORIES, "language": "en"},
            timeout=FETCH_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError):
        return 0

    items = body.get("data") if isinstance(body, dict) else None
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
            source=item.get("source") or "thenewsapi",
            url=url,
            title=item.get("title", ""),
            content=item.get("description", ""),
            published_at=_parse_pub_date(item.get("published_at")),
            image_url=item.get("image_url"),
            status="NEW",
        ))
        inserted += 1
    session.commit()
    return inserted
