from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.models import Article

BENZINGA_NEWS_URL = "https://api.benzinga.com/api/v2/news"
FETCH_TIMEOUT_SECONDS = 10
# How many of the most recent stories to request per poll cycle -- generous
# relative to the poll interval (2 min default) so a slow cycle or a brief
# outage never lets a story fall through the gap between two polls.
PAGE_SIZE = 50


def _parse_created(value: str | None) -> datetime | None:
    # Benzinga returns an RFC 822-style date string, e.g.
    # "Fri, 17 Jul 2026 03:10:30 -0400" -- always carries its own offset, but
    # normalize to aware UTC defensively (matches every other ingestion
    # source's contract: Article.published_at is timezone-aware or None).
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clean_html(html: str | None) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)


def _image_url(item: dict) -> str | None:
    # "small" (~1024px) is the best fit for the feed card's portrait banner --
    # "thumb" is too low-res once stretched to fill it, "large" (~2048px) is
    # needlessly heavy for the same display size.
    for image in item.get("image") or []:
        if image.get("size") == "small" and image.get("url"):
            return image["url"]
    return None


def fetch_new_benzinga_articles(session: Session, api_key: str) -> int:
    """Poll Benzinga's News API for the latest stories and insert any not
    already seen (deduped by url, same convention as
    app.ingestion.poller.fetch_new_articles). A request/parse failure never
    raises -- skip this cycle, retry next, same contract as every other
    ingestion source.

    Populates Article.image_url directly from Benzinga's own response when
    available, so app.pipeline's later `if article.image_url is None:
    fetch_og_image(...)` step has nothing left to do for these articles.
    """
    if not api_key:
        return 0

    try:
        response = httpx.get(
            BENZINGA_NEWS_URL,
            params={"token": api_key, "pageSize": PAGE_SIZE, "displayOutput": "full"},
            headers={"Accept": "application/json"},
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
            source="benzinga",
            url=url,
            title=item.get("title", ""),
            content=_clean_html(item.get("body")) or item.get("teaser", ""),
            published_at=_parse_created(item.get("created")),
            image_url=_image_url(item),
            status="NEW",
        ))
        inserted += 1
    session.commit()
    return inserted
