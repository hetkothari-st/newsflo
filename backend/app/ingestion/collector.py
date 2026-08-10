"""The one generic runner every ingestion source goes through.

A provider (app/ingestion/providers/) only fetches and normalizes. This
module owns everything stateful, exactly once for all sources:

* idempotency -- three tiers, checked per item:
    1. (provider, provider_article_id) when the provider has native ids
    2. url_hash (canonicalized URL, tracking params stripped)
    3. url exact match (the existing unique constraint, final backstop)
* Article insertion (status="NEW" -- the seam the whole downstream
  pipeline consumes, see app/pipeline.py)
* checkpoint persistence (IngestionSource.cursor)
* health accounting (last_success_at, counts, latency EMA)
* circuit breaker -- consecutive fetch failures open a cooldown window
  (cooldown-continue, never a permanent disable: same contract as the
  supply-links drain breaker in app/scheduler.py)

run_source never raises: the scheduler job wrapping it is the same
8-line never-crash shape as every other job in app/scheduler.py.
"""
import json
import logging
from datetime import timedelta, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.ingestion.providers.base import Checkpoint, Provider
from app.ingestion.providers.registry import PROVIDER_REGISTRY
from app.ingestion.urltools import canonical_url_hash
from app.models import Article, IngestionSource, utcnow

logger = logging.getLogger(__name__)

# Consecutive fetch failures before the breaker opens. Same threshold the
# supply-links drain breaker has run in production since 2026-08
# (config.SUPPLY_LLM_FAILURE_BREAKER) -- transient blips don't trip it,
# a genuinely down source does.
BREAKER_TRIP_THRESHOLD = 5
# Cooldown grows with the failure streak, capped so a source that comes
# back is noticed within the hour: 2, 4, 8, ... 60 minutes.
BREAKER_MAX_COOLDOWN_MINUTES = 60
# Raw payloads are for debugging/reprocessing, not archival -- cap protects
# the articles table from a provider that returns megabyte items.
RAW_PAYLOAD_MAX_CHARS = 20_000
# Weight of the newest observation in the latency EMA.
_EMA_ALPHA = 0.3


def _as_aware_utc(dt):
    """SQLite (test suite) drops tzinfo on DateTime(timezone=True) columns
    when reloaded; Postgres (production) doesn't. Same normalization as
    app.pipeline._as_aware_utc, for comparing against utcnow()."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def ensure_registry_rows(session: Session) -> list[IngestionSource]:
    """Upsert one IngestionSource row per registered provider. Existing
    rows are left completely untouched (the DB is the source of truth after
    first seed); missing rows are created from the provider's code defaults,
    with `enabled` seeded from settings.ingestion_enabled_sources."""
    rows = []
    enabled_set = settings.ingestion_enabled_source_set
    for slug, provider in PROVIDER_REGISTRY.items():
        row = session.query(IngestionSource).filter_by(slug=slug).one_or_none()
        if row is None:
            # A legacy per-source env override (e.g. the
            # FINNHUB_POLL_INTERVAL_MINUTES a deployment may already set)
            # wins over the provider's code default at seed time, so
            # upgrading a deployment never silently changes its cadence.
            interval = getattr(settings, f"{slug}_poll_interval_minutes", None)
            row = IngestionSource(
                slug=slug,
                display_name=provider.display_name,
                enabled=1 if slug in enabled_set else 0,
                poll_interval_minutes=interval or provider.default_poll_interval_minutes,
            )
            session.add(row)
        rows.append(row)
    session.commit()
    return rows


def _already_seen(session: Session, slug: str, provider_article_id: str | None,
                  url_hash: str, url: str, seen_keys: set[tuple]) -> bool:
    """Three-tier idempotency. ``seen_keys`` covers same-call duplicates:
    production SessionLocal runs autoflush=False (app/db.py), so a
    session.add() earlier in this loop is invisible to a query later in the
    same loop -- the same reason finnhub.py historically kept a seen_urls
    set."""
    keys = {("id", slug, provider_article_id) if provider_article_id else None,
            ("hash", url_hash), ("url", url)}
    keys.discard(None)
    if keys & seen_keys:
        return True
    seen_keys.update(keys)

    if provider_article_id and session.query(Article).filter_by(
            provider=slug, provider_article_id=provider_article_id).first():
        return True
    if session.query(Article).filter_by(url_hash=url_hash).first():
        return True
    return session.query(Article).filter_by(url=url).first() is not None


def _record_failure(row: IngestionSource, exc: Exception) -> None:
    row.consecutive_failures += 1
    row.last_error = f"{type(exc).__name__}: {exc}"[:2000]
    row.last_error_at = utcnow()
    if row.consecutive_failures >= BREAKER_TRIP_THRESHOLD:
        over = row.consecutive_failures - BREAKER_TRIP_THRESHOLD
        cooldown = min(2 ** (over + 1), BREAKER_MAX_COOLDOWN_MINUTES)
        row.breaker_open_until = utcnow() + timedelta(minutes=cooldown)
        logger.warning(
            "ingestion breaker OPEN for %s: %s consecutive failures, cooldown %s min (%s)",
            row.slug, row.consecutive_failures, cooldown, row.last_error,
        )


def _blend_ema(previous: float | None, observation: float) -> float:
    if previous is None:
        return observation
    return (1 - _EMA_ALPHA) * previous + _EMA_ALPHA * observation


def run_source(session: Session, slug: str) -> dict:
    """Run one poll cycle for one source. Never raises. Returns a small
    summary dict for the scheduler's log line."""
    provider: Provider | None = PROVIDER_REGISTRY.get(slug)
    if provider is None:
        return {"skipped": "unknown_source"}

    row = session.query(IngestionSource).filter_by(slug=slug).one_or_none()
    if row is None:
        # Registry row missing (fresh DB, seeding hasn't run) -- seed now.
        ensure_registry_rows(session)
        row = session.query(IngestionSource).filter_by(slug=slug).one()
    if not row.enabled:
        return {"skipped": "disabled"}
    if row.breaker_open_until and _as_aware_utc(row.breaker_open_until) > utcnow():
        return {"skipped": "breaker_open", "until": row.breaker_open_until.isoformat()}
    if not provider.is_configured():
        return {"skipped": "not_configured"}

    row.last_run_at = utcnow()
    try:
        raw_items = provider.fetch(Checkpoint(cursor=row.cursor))
    except Exception as exc:
        _record_failure(row, exc)
        session.commit()
        return {"error": row.last_error}

    raw_items = list(raw_items or [])[: provider.max_items_per_poll]

    inserted = 0
    latencies: list[float] = []
    seen_keys: set[tuple] = set()
    for raw in raw_items:
        try:
            normalized = provider.normalize(raw)
        except Exception:
            # One malformed item must never sink the batch -- log loudly
            # (silent drops are forbidden) and move on.
            logger.exception("normalize failed for source=%s item=%.200r", slug, raw)
            continue
        if normalized is None or not normalized.url:
            continue
        url_hash = canonical_url_hash(normalized.url)
        if _already_seen(session, slug, normalized.provider_article_id,
                         url_hash, normalized.url, seen_keys):
            continue
        session.add(Article(
            source=normalized.source,
            url=normalized.url,
            title=normalized.title,
            content=normalized.content or "",
            published_at=normalized.published_at,
            image_url=normalized.image_url or None,
            status="NEW",
            provider=slug,
            provider_article_id=normalized.provider_article_id,
            url_hash=url_hash,
            raw_payload=json.dumps(normalized.raw, default=str)[:RAW_PAYLOAD_MAX_CHARS] if normalized.raw else None,
            source_category=normalized.source_category,
        ))
        inserted += 1
        if normalized.published_at is not None:
            delta = (utcnow() - normalized.published_at).total_seconds()
            if delta >= 0:
                latencies.append(delta)

    row.cursor = provider.next_checkpoint(raw_items, Checkpoint(cursor=row.cursor)).cursor
    row.last_success_at = utcnow()
    row.last_fetched_count = len(raw_items)
    row.last_inserted_count = inserted
    row.consecutive_failures = 0
    row.breaker_open_until = None
    if latencies:
        row.avg_publish_to_fetch_latency_seconds = _blend_ema(
            row.avg_publish_to_fetch_latency_seconds, sum(latencies) / len(latencies),
        )
    session.commit()
    return {"fetched": len(raw_items), "inserted": inserted}
