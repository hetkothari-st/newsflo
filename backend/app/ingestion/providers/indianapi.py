"""IndianAPI /news provider -- migrated from the legacy flat fetcher
(app/ingestion/indianapi.py, now removed). Direct pre-aggregated Indian
financial news (Economic Times, LiveMint, Financial Express).

The key is capped at 500 requests/month -- the 90-minute default cadence
(16/day, ~480/month) fits the whole month, unlike the historical 1-minute
cadence that burned the budget in ~8 hours (see the old config.py comment).
"""
from datetime import datetime, timezone

import httpx

from app.config import settings
from app.ingestion.providers.base import IST, Checkpoint, NormalizedArticle

INDIANAPI_NEWS_URL = "https://stock.indianapi.in/news"
FETCH_TIMEOUT_SECONDS = 10


# IndianAPI's pub_date has no timezone offset (e.g. "2026-07-17T10:43:00") --
# every source it aggregates is an Indian publication, so that's always IST
# wall-clock time, not naive UTC.
def _parse_pub_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    aware = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=IST)
    return aware.astimezone(timezone.utc)


class IndianApiProvider:
    slug = "indianapi"
    display_name = "IndianAPI"
    default_poll_interval_minutes = 90  # 500 req/month cap -> ~16/day fits with headroom
    max_items_per_poll = 100

    def is_configured(self) -> bool:
        return bool(settings.indianapi_api_key)

    def fetch(self, checkpoint: Checkpoint) -> list[dict]:
        response = httpx.get(
            INDIANAPI_NEWS_URL,
            headers={"x-api-key": settings.indianapi_api_key},
            timeout=FETCH_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError(f"IndianAPI returned non-list payload: {payload!r:.200}")
        return [item for item in payload if isinstance(item, dict)]

    def normalize(self, raw_item: dict) -> NormalizedArticle | None:
        url = raw_item.get("url")
        if not url:
            return None
        return NormalizedArticle(
            source=raw_item.get("source") or "indianapi",
            url=url,
            title=raw_item.get("title", ""),
            content=raw_item.get("summary", ""),
            published_at=_parse_pub_date(raw_item.get("pub_date")),
            image_url=raw_item.get("image_url"),
            raw=raw_item,
        )

    def next_checkpoint(self, raw_items: list[dict], previous: Checkpoint) -> Checkpoint:
        return previous
