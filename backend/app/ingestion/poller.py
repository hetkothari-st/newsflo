from datetime import datetime, timezone

import feedparser
import httpx
from sqlalchemy.orm import Session

from app.models import Article

# feedparser.parse(url) fetches the URL itself with NO timeout -- a single
# slow/unresponsive RSS source hangs forever, and since this runs inside a
# scheduled job with max_instances=1, one hang blocks every future poll
# cycle permanently (confirmed in production: the very first poll after
# deploy hung, and no ingestion ever ran again). Fetching the raw bytes
# ourselves with an explicit httpx timeout, then handing feedparser only the
# already-downloaded bytes (pure parsing, no network I/O), makes a hang
# structurally impossible.
FEED_FETCH_TIMEOUT_SECONDS = 10


def _parse_published(entry) -> datetime | None:
    published_parsed = entry.get("published_parsed")
    if published_parsed:
        return datetime(*published_parsed[:6], tzinfo=timezone.utc)
    return None


def fetch_new_articles(session: Session, feeds: list[dict]) -> int:
    inserted = 0
    for feed in feeds:
        try:
            response = httpx.get(feed["url"], timeout=FEED_FETCH_TIMEOUT_SECONDS, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError:
            # One unreachable/slow/erroring feed must never block the rest --
            # skip it this cycle, try again next cycle.
            continue
        parsed = feedparser.parse(response.content)
        for entry in parsed.entries:
            url = entry.get("link")
            if not url:
                continue
            if session.query(Article).filter_by(url=url).one_or_none():
                continue
            session.add(Article(
                source=feed["source"],
                url=url,
                title=entry.get("title", ""),
                content=entry.get("summary", ""),
                published_at=_parse_published(entry),
                status="NEW",
            ))
            inserted += 1
    session.commit()
    return inserted
