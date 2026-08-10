"""Generic RSS/Atom provider, parametrized per feed. One class covers the
press feeds (Economic Times / Moneycontrol / LiveMint / BusinessLine --
superseding app/ingestion/poller.py + sources.py, which remain only as the
end-to-end test suite's ingestion harness), the government feeds (PIB /
RBI / SEBI), and -- via the NseAnnouncementsProvider subclass -- NSE's
corporate announcements feed.

The bytes-then-parse pattern is preserved verbatim from poller.py:
feedparser.parse(url) fetches with NO timeout, and one hung feed inside a
max_instances=1 scheduler job blocks every future poll permanently
(confirmed in production). Fetch the raw bytes with an explicit httpx
timeout, then hand feedparser only the already-downloaded bytes.
"""
import re
from datetime import datetime, timezone

import feedparser
import httpx

from app.ingestion.providers.base import IST, Checkpoint, NormalizedArticle

FEED_FETCH_TIMEOUT_SECONDS = 10

# Several Indian government/exchange hosts (RBI, NSE, PIB) reject default
# python-httpx User-Agents. Same header set the universe fetchers have used
# against these hosts since 2026-08 (app/companies/universe/fetchers.py).
BROWSER_UA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

# NSE announcement descriptions end in " |SUBJECT: <category>" -- the only
# structured category signal in the feed, consumed by
# app/filtering/exchange_noise.py.
_NSE_SUBJECT_RE = re.compile(r"\|\s*SUBJECT:\s*(?P<subject>.+?)\s*$")

def _entry_published(entry) -> datetime | None:
    published_parsed = entry.get("published_parsed")
    if published_parsed:
        return datetime(*published_parsed[:6], tzinfo=timezone.utc)
    return None


def _json_safe_raw(raw_item: dict) -> dict:
    """feedparser entries hold parser objects the collector's json.dumps
    would choke on -- keep only the plain scalar fields."""
    return {k: v for k, v in raw_item.items() if isinstance(v, (str, int, float, bool, type(None)))}


class RssProvider:
    """One instance per feed. ``slug`` doubles as Article.provider;
    ``source_name`` is the publisher display name written to
    Article.source (matching the legacy poller's feed["source"])."""

    default_poll_interval_minutes = 5
    max_items_per_poll = 200

    def __init__(self, slug: str, display_name: str, source_name: str, feed_url: str,
                 headers: dict | None = None, poll_interval_minutes: int | None = None):
        self.slug = slug
        self.display_name = display_name
        self.source_name = source_name
        self.feed_url = feed_url
        self.headers = headers
        if poll_interval_minutes is not None:
            self.default_poll_interval_minutes = poll_interval_minutes

    def is_configured(self) -> bool:
        return True  # RSS needs no key; gating is IngestionSource.enabled only

    def fetch(self, checkpoint: Checkpoint) -> list[dict]:
        response = httpx.get(
            self.feed_url,
            timeout=FEED_FETCH_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers=self.headers,
        )
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
        # feedparser never raises on malformed XML -- it sets .bozo and
        # returns whatever it salvaged. Zero entries WITH a parse error is a
        # broken feed, not an empty one; surface it to the breaker.
        if not parsed.entries and getattr(parsed, "bozo", 0):
            raise ValueError(f"unparseable feed {self.feed_url}: {getattr(parsed, 'bozo_exception', None)!r}")
        return [dict(entry) for entry in parsed.entries]

    def normalize(self, raw_item: dict) -> NormalizedArticle | None:
        url = raw_item.get("link")
        if not url:
            return None
        return NormalizedArticle(
            source=self.source_name,
            url=url,
            title=raw_item.get("title", ""),
            content=raw_item.get("summary", ""),
            published_at=_entry_published(raw_item),
            raw=_json_safe_raw(raw_item),
        )

    def next_checkpoint(self, raw_items: list[dict], previous: Checkpoint) -> Checkpoint:
        return previous


class NseAnnouncementsProvider(RssProvider):
    """NSE corporate announcements. Differs from a plain feed in three ways:

    * the entry title is just the company name; the announcement text lives
      in the description -- title becomes "<Company>: <description head>"
      so the downstream relevance/analysis stages (which reason from the
      headline first) see the actual event;
    * the trailing " |SUBJECT: <category>" is extracted into
      source_category for the exchange-noise gate;
    * pubDate is IST wall-clock without an offset ("10-Aug-2026 12:21:10");
      feedparser usually fails to parse it, so parse it here.

    Items with an empty <link/> (NAV declarations mostly) are dropped: no
    URL means nothing to dedup or link to -- and that class of item is
    exchange noise anyway.
    """

    default_poll_interval_minutes = 5  # feed ttl is 5 minutes
    _PUBDATE_FORMATS = ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M")

    def normalize(self, raw_item: dict) -> NormalizedArticle | None:
        url = raw_item.get("link")
        if not url:
            return None
        company = (raw_item.get("title") or "").strip()
        description = (raw_item.get("summary") or "").strip()
        subject_match = _NSE_SUBJECT_RE.search(description)
        source_category = subject_match.group("subject").strip() if subject_match else None
        body = _NSE_SUBJECT_RE.sub("", description).strip()

        published_at = _entry_published(raw_item)
        if published_at is None:
            raw_date = (raw_item.get("published") or "").strip()
            for fmt in self._PUBDATE_FORMATS:
                try:
                    published_at = datetime.strptime(raw_date, fmt).replace(tzinfo=IST).astimezone(timezone.utc)
                    break
                except ValueError:
                    continue

        title = f"{company}: {body[:180]}" if company else body[:200]
        return NormalizedArticle(
            source=self.source_name,
            url=url,
            title=title,
            content=body,
            published_at=published_at,
            source_category=source_category,
            raw=_json_safe_raw(raw_item),
        )
