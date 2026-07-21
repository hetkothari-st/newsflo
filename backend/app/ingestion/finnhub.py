from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.models import Article

FINNHUB_NEWS_URL = "https://finnhub.io/api/v1/news"
FETCH_TIMEOUT_SECONDS = 10
CATEGORIES = ("general", "merger")


def fetch_new_finnhub_articles(session: Session, api_key: str) -> int:
    """Poll finnhub.io's /v1/news endpoint across CATEGORIES, insert any
    article not already seen (deduped by url, same convention as every
    other ingestion source in this package).

    A request/parse failure for one category never raises and never
    blocks the other category -- skip that category this cycle, retry
    next, same contract as every other ingestion source. A missing
    api_key returns 0 without making any request.

    Dedup must catch a same-url item returned by both categories within
    one call, not just against previously-committed rows: production's
    SessionLocal runs with autoflush=False (app/db.py), so a
    same-call session.add(...) from an earlier category is not visible
    to a later session.query(...) in this same call. seen_urls tracks
    that in-memory.
    """
    if not api_key:
        return 0

    inserted = 0
    seen_urls: set[str] = set()
    for category in CATEGORIES:
        try:
            response = httpx.get(
                FINNHUB_NEWS_URL,
                params={"category": category, "token": api_key},
                timeout=FETCH_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            items = response.json()
        except (httpx.HTTPError, ValueError):
            continue

        if not isinstance(items, list):
            continue

        for item in items:
            url = item.get("url")
            if not url or url in seen_urls:
                continue
            if session.query(Article).filter_by(url=url).one_or_none():
                continue

            timestamp = item.get("datetime")
            published_at = (
                datetime.fromtimestamp(timestamp, tz=timezone.utc)
                if isinstance(timestamp, (int, float))
                else None
            )
            session.add(Article(
                source=item.get("source") or "finnhub",
                url=url,
                title=item.get("headline", ""),
                content=item.get("summary", ""),
                published_at=published_at,
                # Finnhub returns "image": "" (present, empty) rather than
                # omitting the field for imageless items -- normalize to
                # None so _persist_alert's `if article.image_url is None`
                # og:image fallback (app/pipeline.py) actually triggers.
                image_url=item.get("image") or None,
                status="NEW",
            ))
            seen_urls.add(url)
            inserted += 1

    session.commit()
    return inserted
