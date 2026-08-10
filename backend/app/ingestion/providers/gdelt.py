"""GDELT DOC 2.0 provider -- the broad global discovery layer.

GDELT is keyless, updates on a ~15-minute cycle, and asks for >=5 seconds
between requests (verified live 2026-08-10: faster gets a throttle notice
instead of JSON). It is a breadth source, not a low-latency one: its job is
surfacing globally material events (trade restrictions, commodity
disruptions, infrastructure decisions, geopolitics) that the curated
financial feeds miss -- the relevance engine downstream decides what
matters, per the "don't over-filter at ingestion" principle.

Volume control lives in three places, because GDELT is the one source that
could flood the LLM funnel:
* scoped queries (below) rather than the raw firehose,
* maxrecords per query,
* the provider-level max_items_per_poll cap the collector enforces.

artlist mode returns no article body -- content stays empty and the
existing fetch_pending_full_text stage (app/ingestion/full_text.py) scrapes
the page like it already does for any thin article, source-agnostically.
"""
import logging
import time
from datetime import datetime, timezone

import httpx

from app.ingestion.providers.base import Checkpoint, NormalizedArticle

logger = logging.getLogger(__name__)

GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
FETCH_TIMEOUT_SECONDS = 20
MIN_REQUEST_SPACING_SECONDS = 5.0
MAX_RECORDS_PER_QUERY = 50
# 30-minute window against a 10-minute poll = deliberate 3x overlap;
# completeness beats duplicates, dedup is free downstream.
TIMESPAN = "30min"

# Two lenses, matching the product requirement: everything India-adjacent
# regardless of topic, plus globally market-moving themes regardless of
# country. Kept as code constants (product/algorithm decision, same idiom
# as RELEVANCE_PREFILTER_MARKET_SIGNALS in config.py).
GDELT_QUERIES = (
    '(india OR indian OR rupee OR RBI OR SEBI OR "Nifty" OR "Sensex") '
    '(economy OR market OR trade OR policy OR industry OR infrastructure OR tax OR tariff OR exports OR imports)',
    '(tariff OR sanctions OR "interest rate" OR "central bank" OR "federal reserve" OR OPEC '
    'OR "crude oil" OR "supply chain" OR semiconductor OR "export ban" OR "trade deal" OR "rate cut")',
)


def _parse_seendate(value: str | None) -> datetime | None:
    # GDELT's seendate: "20260810T121500Z"
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class GdeltProvider:
    slug = "gdelt"
    display_name = "GDELT"
    default_poll_interval_minutes = 10
    max_items_per_poll = 40  # the LLM-funnel cap: GDELT never floods a cycle

    def is_configured(self) -> bool:
        return True  # keyless

    def fetch(self, checkpoint: Checkpoint) -> list[dict]:
        items: list[dict] = []
        errors: list[Exception] = []
        for index, query in enumerate(GDELT_QUERIES):
            if index:
                time.sleep(MIN_REQUEST_SPACING_SECONDS)
            try:
                response = httpx.get(
                    GDELT_DOC_URL,
                    params={
                        "query": query,
                        "mode": "artlist",
                        "format": "json",
                        "maxrecords": MAX_RECORDS_PER_QUERY,
                        "timespan": TIMESPAN,
                        "sort": "datedesc",
                    },
                    timeout=FETCH_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                # GDELT answers over-rate requests with HTTP 200 + a plain-
                # text throttle notice, which lands here as the JSON
                # ValueError. One failing query doesn't block the other;
                # both failing is a real source failure for the breaker. A
                # partial failure doesn't reach the breaker, so log it here
                # or it is invisible.
                logger.warning("gdelt query %s fetch failed: %s", index, exc)
                errors.append(exc)
                continue
            articles = payload.get("articles")
            if isinstance(articles, list):
                items.extend(item for item in articles if isinstance(item, dict))
        if not items and errors and len(errors) == len(GDELT_QUERIES):
            raise errors[0]
        return items

    def normalize(self, raw_item: dict) -> NormalizedArticle | None:
        url = raw_item.get("url")
        if not url:
            return None
        if (raw_item.get("language") or "").lower() not in ("english", "en", ""):
            # The feed is English-first; the language gate downstream would
            # filter these anyway -- dropping here saves the insert.
            return None
        return NormalizedArticle(
            source=raw_item.get("domain") or "gdelt",
            url=url,
            title=raw_item.get("title", ""),
            content="",  # artlist has no body; full_text stage scrapes it
            published_at=_parse_seendate(raw_item.get("seendate")),
            image_url=raw_item.get("socialimage") or None,
            raw=raw_item,
        )

    def next_checkpoint(self, raw_items: list[dict], previous: Checkpoint) -> Checkpoint:
        return previous  # timespan window + idempotency, no cursor
