from datetime import datetime, timezone

import feedparser
from sqlalchemy.orm import Session

from app.models import Article


def _parse_published(entry) -> datetime | None:
    published_parsed = entry.get("published_parsed")
    if published_parsed:
        return datetime(*published_parsed[:6], tzinfo=timezone.utc)
    return None


def fetch_new_articles(session: Session, feeds: list[dict]) -> int:
    inserted = 0
    for feed in feeds:
        parsed = feedparser.parse(feed["url"])
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
