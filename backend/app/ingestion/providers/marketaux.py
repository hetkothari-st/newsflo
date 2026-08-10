"""Marketaux /v1/news/all provider -- broad global financial news.

Free-tier reality (verified live 2026-08-10): 3 articles per request, 100
requests per day. The 15-minute default cadence = 96 req/day, just inside
the budget. This is a breadth-of-coverage source on the free tier, not a
firehose -- a paid plan raises `limit` and the cadence can then tighten
(both are one registry-row edit away, no code change).

Checkpointing: published_after = (latest seen published_at - overlap).
The overlap deliberately re-fetches a window that was already seen --
completeness beats avoiding duplicates (the collector's idempotency tiers
make re-seen items free), and a story that lands in Marketaux's index
slightly out of order would otherwise be skipped forever.
"""
from datetime import datetime, timedelta, timezone

import httpx

from app.config import settings
from app.ingestion.providers.base import Checkpoint, NormalizedArticle

MARKETAUX_NEWS_URL = "https://api.marketaux.com/v1/news/all"
FETCH_TIMEOUT_SECONDS = 15
# Free-tier per-request article cap. On a paid plan raise to the plan's max.
PAGE_LIMIT = 3
CHECKPOINT_OVERLAP = timedelta(minutes=2)


def _parse_published(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class MarketauxProvider:
    slug = "marketaux"
    display_name = "Marketaux"
    default_poll_interval_minutes = 15  # 96 req/day on the free tier's 100/day cap
    max_items_per_poll = 100

    def is_configured(self) -> bool:
        return bool(settings.marketaux_api_key)

    def fetch(self, checkpoint: Checkpoint) -> list[dict]:
        params = {
            "api_token": settings.marketaux_api_key,
            "language": "en",
            "limit": PAGE_LIMIT,
            "sort": "published_on",
            # ASCENDING, deliberately: each poll takes the OLDEST unseen
            # articles and the cursor advances to the batch max, i.e.
            # forward pagination. Descending here loses data permanently --
            # a desc page returns only the newest PAGE_LIMIT items and the
            # max-based cursor then jumps past every unfetched older item
            # in the window. Ascending merely falls behind real time when
            # volume exceeds the page budget, and catches up.
            "sort_order": "asc",
        }
        if checkpoint.cursor:
            params["published_after"] = checkpoint.cursor
        response = httpx.get(MARKETAUX_NEWS_URL, params=params, timeout=FETCH_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data")
        if not isinstance(data, list):
            raise ValueError(f"Marketaux returned no data list: {payload!r:.200}")
        return [item for item in data if isinstance(item, dict)]

    def normalize(self, raw_item: dict) -> NormalizedArticle | None:
        url = raw_item.get("url")
        if not url:
            return None
        return NormalizedArticle(
            source=raw_item.get("source") or "marketaux",
            url=url,
            # description over snippet: snippet is a truncation of the body,
            # description is the article's own standfirst.
            content=raw_item.get("description") or raw_item.get("snippet") or "",
            title=raw_item.get("title", ""),
            published_at=_parse_published(raw_item.get("published_at")),
            image_url=raw_item.get("image_url") or None,
            provider_article_id=raw_item.get("uuid"),
            raw=raw_item,
        )

    def next_checkpoint(self, raw_items: list[dict], previous: Checkpoint) -> Checkpoint:
        published = [
            parsed for parsed in (_parse_published(item.get("published_at")) for item in raw_items)
            if parsed is not None
        ]
        if not published:
            return previous  # empty poll advances nothing -- never fabricate a cursor from wall clock
        cursor_time = max(published) - CHECKPOINT_OVERLAP
        # Marketaux's published_after expects "YYYY-MM-DDTHH:MM:SS".
        return Checkpoint(cursor=cursor_time.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"))
