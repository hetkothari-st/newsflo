"""Serialization contract of the /api/source-health endpoint. Calls the
route function directly with the test session -- auth is a Depends and the
handler never touches current_user beyond requiring it."""
from datetime import timedelta

from app.models import IngestionSource, utcnow
from app.routers.source_health import list_source_health


def test_list_source_health_serializes_rows(db_session):
    db_session.add(IngestionSource(
        slug="marketaux", display_name="Marketaux", enabled=1, poll_interval_minutes=15,
        consecutive_failures=2, last_error="HTTPStatusError: 429",
        last_error_at=utcnow(), last_fetched_count=3, last_inserted_count=1,
        avg_publish_to_fetch_latency_seconds=42.5,
    ))
    db_session.add(IngestionSource(
        slug="gdelt", display_name="GDELT", enabled=0, poll_interval_minutes=10,
        breaker_open_until=utcnow() + timedelta(minutes=10),
    ))
    db_session.commit()

    rows = list_source_health(db=db_session, current_user=None)

    by_slug = {row["slug"]: row for row in rows}
    assert by_slug["marketaux"]["enabled"] is True
    assert by_slug["marketaux"]["breaker_open"] is False
    assert by_slug["marketaux"]["consecutive_failures"] == 2
    assert by_slug["marketaux"]["last_error"] == "HTTPStatusError: 429"
    assert by_slug["marketaux"]["avg_publish_to_fetch_latency_seconds"] == 42.5
    assert by_slug["gdelt"]["enabled"] is False
    assert by_slug["gdelt"]["breaker_open"] is True
    assert by_slug["gdelt"]["breaker_open_until"] is not None
