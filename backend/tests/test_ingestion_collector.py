"""The center of gravity for the multi-source ingestion layer: a fake
provider drives the generic runner (app/ingestion/collector.py) through
insertion, all three idempotency tiers, checkpointing, health accounting,
and the circuit breaker's cooldown-continue contract."""
from datetime import timedelta

import pytest

from app.ingestion import collector
from app.ingestion.providers.base import Checkpoint, NormalizedArticle
from app.models import Article, IngestionSource, utcnow


class FakeProvider:
    slug = "fake"
    display_name = "Fake Source"
    default_poll_interval_minutes = 5
    max_items_per_poll = 10

    def __init__(self, items=None, configured=True, fetch_error=None, cursor_out=None):
        self.items = items or []
        self.configured = configured
        self.fetch_error = fetch_error
        self.cursor_out = cursor_out
        self.fetch_calls = 0

    def is_configured(self):
        return self.configured

    def fetch(self, checkpoint):
        self.fetch_calls += 1
        if self.fetch_error:
            raise self.fetch_error
        return list(self.items)

    def normalize(self, raw_item):
        if raw_item.get("boom"):
            raise ValueError("malformed item")
        if raw_item.get("drop"):
            return None
        return NormalizedArticle(
            source=raw_item.get("source", "fake-pub"),
            url=raw_item["url"],
            title=raw_item.get("title", "t"),
            content=raw_item.get("content", ""),
            published_at=raw_item.get("published_at"),
            provider_article_id=raw_item.get("pid"),
            source_category=raw_item.get("category"),
            raw=raw_item,
        )

    def next_checkpoint(self, raw_items, previous):
        return Checkpoint(cursor=self.cursor_out) if self.cursor_out else previous


@pytest.fixture()
def fake_registry(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(collector, "PROVIDER_REGISTRY", {"fake": provider})
    return provider


def _seed_row(session, **overrides):
    row = IngestionSource(
        slug="fake", display_name="Fake Source", enabled=1, poll_interval_minutes=5,
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    session.add(row)
    session.commit()
    return row


def test_run_source_inserts_articles_with_provider_metadata(db_session, fake_registry):
    _seed_row(db_session)
    fake_registry.items = [{"url": "https://ex.com/a", "pid": "1", "title": "Story A", "category": "Press Release"}]

    result = collector.run_source(db_session, "fake")

    assert result == {"fetched": 1, "inserted": 1}
    article = db_session.query(Article).one()
    assert article.status == "NEW"
    assert article.provider == "fake"
    assert article.provider_article_id == "1"
    assert article.source_category == "Press Release"
    assert article.url_hash
    assert '"url": "https://ex.com/a"' in article.raw_payload


def test_run_source_idempotent_by_provider_article_id(db_session, fake_registry):
    _seed_row(db_session)
    # Same provider id, different URL (providers sometimes re-emit an item
    # under a redirected URL) -- tier 1 must catch it.
    fake_registry.items = [{"url": "https://ex.com/a", "pid": "1"}]
    collector.run_source(db_session, "fake")
    fake_registry.items = [{"url": "https://ex.com/a-moved", "pid": "1"}]

    result = collector.run_source(db_session, "fake")

    assert result["inserted"] == 0
    assert db_session.query(Article).count() == 1


def test_run_source_idempotent_by_canonical_url_hash(db_session, fake_registry):
    _seed_row(db_session)
    fake_registry.items = [{"url": "https://ex.com/a?utm_source=feed"}]
    collector.run_source(db_session, "fake")
    # Tracking decoration changed; canonical hash identical.
    fake_registry.items = [{"url": "https://EX.com/a/?utm_campaign=x"}]

    result = collector.run_source(db_session, "fake")

    assert result["inserted"] == 0
    assert db_session.query(Article).count() == 1


def test_run_source_dedupes_within_one_batch(db_session, fake_registry):
    _seed_row(db_session)
    fake_registry.items = [{"url": "https://ex.com/a"}, {"url": "https://ex.com/a"}]

    result = collector.run_source(db_session, "fake")

    assert result["inserted"] == 1


def test_run_source_skips_disabled_source_without_fetching(db_session, fake_registry):
    _seed_row(db_session, enabled=0)

    result = collector.run_source(db_session, "fake")

    assert result == {"skipped": "disabled"}
    assert fake_registry.fetch_calls == 0


def test_run_source_skips_unconfigured_source_without_fetching(db_session, fake_registry):
    _seed_row(db_session)
    fake_registry.configured = False

    result = collector.run_source(db_session, "fake")

    assert result == {"skipped": "not_configured"}
    assert fake_registry.fetch_calls == 0


def test_run_source_records_failure_and_trips_breaker_after_threshold(db_session, fake_registry):
    row = _seed_row(db_session)
    fake_registry.fetch_error = ValueError("upstream down")

    for _ in range(collector.BREAKER_TRIP_THRESHOLD):
        collector.run_source(db_session, "fake")

    db_session.refresh(row)
    assert row.consecutive_failures == collector.BREAKER_TRIP_THRESHOLD
    assert row.breaker_open_until is not None
    assert "upstream down" in row.last_error

    # Breaker open: the next run must not fetch at all.
    calls_before = fake_registry.fetch_calls
    result = collector.run_source(db_session, "fake")
    assert result["skipped"] == "breaker_open"
    assert fake_registry.fetch_calls == calls_before


def test_run_source_breaker_cools_down_and_success_resets(db_session, fake_registry):
    # Cooldown-continue, never a permanent disable: an expired
    # breaker_open_until lets the source run again, and one success clears
    # the whole failure streak (same contract as the supply-links drain
    # breaker).
    row = _seed_row(
        db_session,
        consecutive_failures=collector.BREAKER_TRIP_THRESHOLD,
        breaker_open_until=utcnow() - timedelta(minutes=1),
    )
    fake_registry.items = [{"url": "https://ex.com/back"}]

    result = collector.run_source(db_session, "fake")

    assert result["inserted"] == 1
    db_session.refresh(row)
    assert row.consecutive_failures == 0
    assert row.breaker_open_until is None
    assert row.last_success_at is not None


def test_run_source_persists_provider_checkpoint(db_session, fake_registry):
    row = _seed_row(db_session)
    fake_registry.items = [{"url": "https://ex.com/a"}]
    fake_registry.cursor_out = "2026-08-10T12:00:00"

    collector.run_source(db_session, "fake")

    db_session.refresh(row)
    assert row.cursor == "2026-08-10T12:00:00"


def test_run_source_one_malformed_item_never_sinks_the_batch(db_session, fake_registry):
    _seed_row(db_session)
    fake_registry.items = [{"url": "https://ex.com/bad", "boom": True}, {"url": "https://ex.com/good"}]

    result = collector.run_source(db_session, "fake")

    assert result["inserted"] == 1
    assert db_session.query(Article).one().url == "https://ex.com/good"


def test_run_source_enforces_max_items_per_poll(db_session, fake_registry):
    _seed_row(db_session)
    fake_registry.items = [{"url": f"https://ex.com/{i}"} for i in range(25)]

    result = collector.run_source(db_session, "fake")

    assert result["fetched"] == fake_registry.max_items_per_poll
    assert result["inserted"] == fake_registry.max_items_per_poll


def test_run_source_caps_raw_payload_size(db_session, fake_registry):
    _seed_row(db_session)
    fake_registry.items = [{"url": "https://ex.com/big", "blob": "x" * 100_000}]

    collector.run_source(db_session, "fake")

    assert len(db_session.query(Article).one().raw_payload) <= collector.RAW_PAYLOAD_MAX_CHARS


def test_run_source_updates_latency_ema(db_session, fake_registry):
    row = _seed_row(db_session)
    fake_registry.items = [{"url": "https://ex.com/a", "published_at": utcnow() - timedelta(seconds=100)}]

    collector.run_source(db_session, "fake")

    db_session.refresh(row)
    assert row.avg_publish_to_fetch_latency_seconds == pytest.approx(100, abs=5)


def test_run_source_unknown_slug_is_a_noop(db_session, fake_registry):
    assert collector.run_source(db_session, "nope") == {"skipped": "unknown_source"}


def test_ensure_registry_rows_seeds_enabled_from_settings(db_session, fake_registry, monkeypatch):
    monkeypatch.setattr(collector.settings, "ingestion_enabled_sources", "fake,other")

    rows = collector.ensure_registry_rows(db_session)

    assert len(rows) == 1
    assert rows[0].slug == "fake"
    assert rows[0].enabled == 1
    assert rows[0].poll_interval_minutes == 5


def test_ensure_registry_rows_never_overrides_an_existing_row(db_session, fake_registry, monkeypatch):
    _seed_row(db_session, enabled=0, poll_interval_minutes=42)
    monkeypatch.setattr(collector.settings, "ingestion_enabled_sources", "fake")

    rows = collector.ensure_registry_rows(db_session)

    assert rows[0].enabled == 0  # DB row is the source of truth after first seed
    assert rows[0].poll_interval_minutes == 42
