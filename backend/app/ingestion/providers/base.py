"""The provider contract every ingestion source implements.

A provider is two pure-ish behaviors behind one small interface:

* ``fetch(checkpoint)`` -- network I/O only. Returns the provider's raw
  items (list of dicts) for this poll. Never touches the database. May
  raise: the collector runner (app/ingestion/collector.py) is the single
  place that catches fetch failures and records them against the source's
  health row, so a provider that swallowed its own errors would make every
  failure invisible to the breaker.
* ``normalize(raw_item)`` -- pure mapping from one raw item to the
  canonical ``NormalizedArticle`` (or None to drop the item). No network,
  no database, no side effects.

Everything else -- dedup, inserting Article rows, checkpoint persistence,
health metrics, the circuit breaker -- lives in the collector runner and is
therefore written and tested exactly once, not once per source.

Adding a new source (e.g. NewsCatcher) = one provider module implementing
this contract + one line in app/ingestion/providers/registry.py. Nothing
downstream changes.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable

# India Standard Time, shared by every provider that parses IST wall-clock
# timestamps (NSE, BSE, IndianAPI, PIB). Deliberately NOT imported from
# app.ist_time: that module imports app.pipeline (for _as_aware_utc), which
# would drag the whole analysis/LLM import graph into every provider import.
IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class NormalizedArticle:
    """Canonical output of ``Provider.normalize``. Field meanings mirror
    the existing ``Article`` columns exactly (see app/models.py) -- the
    collector copies these through verbatim."""

    source: str                            # publisher display name (Article.source, unchanged meaning)
    url: str
    title: str
    content: str = ""
    published_at: datetime | None = None
    image_url: str | None = None
    provider_article_id: str | None = None  # provider's own id (Marketaux uuid, Benzinga id, BSE NEWSID)
    source_category: str | None = None      # structured announcement category (NSE/BSE only)
    raw: dict = field(default_factory=dict)  # full raw payload, JSON-persisted by the runner


@dataclass
class Checkpoint:
    """Opaque per-source cursor. Only the provider that wrote it interprets
    it (e.g. Marketaux stores an ISO8601 ``published_after`` timestamp).
    Sources with no native cursor (RSS, GDELT, BSE) leave it None forever
    and rely purely on the runner's idempotency checks."""

    cursor: str | None = None


@runtime_checkable
class Provider(Protocol):
    slug: str                              # registry key + Article.provider value, e.g. "marketaux"
    display_name: str
    default_poll_interval_minutes: int     # seeds IngestionSource.poll_interval_minutes on first boot
    max_items_per_poll: int                # runner-enforced hard cap per cycle (defense in depth)

    def is_configured(self) -> bool:
        """False when a required API key is missing -- the runner then skips
        the source without a request, same contract as the existing
        ``if not api_key: return 0`` in every legacy fetcher."""
        ...

    def fetch(self, checkpoint: Checkpoint) -> list[dict]:
        ...

    def normalize(self, raw_item: dict) -> NormalizedArticle | None:
        ...

    def next_checkpoint(self, raw_items: list[dict], previous: Checkpoint) -> Checkpoint:
        """The cursor to persist after a successful poll. Default for
        cursor-less sources: return ``previous`` unchanged."""
        ...
