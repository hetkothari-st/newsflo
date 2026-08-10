"""Benzinga /api/v2/news provider -- low-latency US market/macro newswire.

Verified live 2026-08-10: returns rich JSON (id, title, teaser, body, url,
created, stocks[], channels[], importance_rank). Quota for this key is
undocumented -- sustained 429s trip the collector's circuit breaker, which
backs the source off automatically instead of hammering it.

The stocks[]/channels[] metadata is preserved in raw_payload only. The
downstream cascade discovers companies from the text itself
(company-independent by design) -- pre-tagged US tickers would mostly miss
the Indian universe anyway.
"""
from email.utils import parsedate_to_datetime

import httpx

from app.config import settings
from app.ingestion.providers.base import Checkpoint, NormalizedArticle

BENZINGA_NEWS_URL = "https://api.benzinga.com/api/v2/news"
FETCH_TIMEOUT_SECONDS = 15
PAGE_SIZE = 50


class BenzingaProvider:
    slug = "benzinga"
    display_name = "Benzinga"
    default_poll_interval_minutes = 5
    max_items_per_poll = 100

    def is_configured(self) -> bool:
        return bool(settings.benzinga_api_key)

    def fetch(self, checkpoint: Checkpoint) -> list[dict]:
        response = httpx.get(
            BENZINGA_NEWS_URL,
            params={
                "token": settings.benzinga_api_key,
                "pageSize": PAGE_SIZE,
                "displayOutput": "abstract",
            },
            headers={"Accept": "application/json"},
            timeout=FETCH_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError(f"Benzinga returned non-list payload: {payload!r:.200}")
        return [item for item in payload if isinstance(item, dict)]

    def normalize(self, raw_item: dict) -> NormalizedArticle | None:
        url = raw_item.get("url")
        if not url:
            return None
        created = raw_item.get("created")
        try:
            published_at = parsedate_to_datetime(created) if created else None
        except (TypeError, ValueError):
            published_at = None
        images = raw_item.get("image") or []
        image_url = None
        if isinstance(images, list):
            by_size = {img.get("size"): img.get("url") for img in images if isinstance(img, dict)}
            image_url = by_size.get("large") or by_size.get("small") or by_size.get("thumb")
        return NormalizedArticle(
            source="benzinga",
            url=url,
            title=raw_item.get("title", ""),
            content=raw_item.get("body") or raw_item.get("teaser") or "",
            published_at=published_at,
            image_url=image_url,
            provider_article_id=str(raw_item["id"]) if raw_item.get("id") else None,
            raw=raw_item,
        )

    def next_checkpoint(self, raw_items: list[dict], previous: Checkpoint) -> Checkpoint:
        return previous
