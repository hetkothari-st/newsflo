"""Finnhub /v1/news provider -- migrated from the legacy flat fetcher
(app/ingestion/finnhub.py, now removed). Field mapping preserved verbatim:
headline->title, summary->content, unix datetime->published_at, and the
"image": "" -> None normalization that keeps pipeline.py's og:image
fallback triggering."""
from datetime import datetime, timezone

import httpx

from app.config import settings
from app.ingestion.providers.base import Checkpoint, NormalizedArticle

FINNHUB_NEWS_URL = "https://finnhub.io/api/v1/news"
FETCH_TIMEOUT_SECONDS = 10
CATEGORIES = ("general", "merger")


class FinnhubProvider:
    slug = "finnhub"
    display_name = "Finnhub"
    default_poll_interval_minutes = 1  # free tier is 60 calls/min; 2 calls/cycle is nowhere near it
    max_items_per_poll = 300

    def is_configured(self) -> bool:
        return bool(settings.finnhub_api_key)

    def fetch(self, checkpoint: Checkpoint) -> list[dict]:
        items: list[dict] = []
        errors: list[Exception] = []
        for category in CATEGORIES:
            try:
                response = httpx.get(
                    FINNHUB_NEWS_URL,
                    params={"category": category, "token": settings.finnhub_api_key},
                    timeout=FETCH_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                # One failing category never blocks the other -- but if BOTH
                # fail, raise so the collector records a real failure
                # against the breaker instead of logging a healthy
                # zero-item poll.
                errors.append(exc)
                continue
            if isinstance(payload, list):
                items.extend(item for item in payload if isinstance(item, dict))
        if not items and len(errors) == len(CATEGORIES):
            raise errors[0]
        return items

    def normalize(self, raw_item: dict) -> NormalizedArticle | None:
        url = raw_item.get("url")
        if not url:
            return None
        timestamp = raw_item.get("datetime")
        published_at = (
            datetime.fromtimestamp(timestamp, tz=timezone.utc)
            if isinstance(timestamp, (int, float))
            else None
        )
        return NormalizedArticle(
            source=raw_item.get("source") or "finnhub",
            url=url,
            title=raw_item.get("headline", ""),
            content=raw_item.get("summary", ""),
            published_at=published_at,
            image_url=raw_item.get("image") or None,
            provider_article_id=str(raw_item["id"]) if raw_item.get("id") else None,
            raw=raw_item,
        )

    def next_checkpoint(self, raw_items: list[dict], previous: Checkpoint) -> Checkpoint:
        return previous
