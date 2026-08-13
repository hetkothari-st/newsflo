

def test_pulse_live_scopes_to_one_ist_day(db_session):
    from datetime import datetime, timezone

    from fastapi.testclient import TestClient

    from app.main import app
    from app.models import Article
    from app.routers.articles import get_db

    # 2026-08-10 23:00 IST and 2026-08-11 01:00 IST straddle IST midnight
    # but share a UTC date -- day scoping must cut at IST, not UTC.
    db_session.add_all([
        Article(source="pulse", provider="pulse_zerodha", url="https://p/1", title="late night",
                content="c", status="NEW",
                published_at=datetime(2026, 8, 10, 17, 30, tzinfo=timezone.utc)),  # 23:00 IST Aug 10
        Article(source="pulse", provider="pulse_zerodha", url="https://p/2", title="early morning",
                content="c", status="NEW",
                published_at=datetime(2026, 8, 10, 19, 30, tzinfo=timezone.utc)),  # 01:00 IST Aug 11
    ])
    db_session.commit()

    def _get_db():
        yield db_session

    app.dependency_overrides[get_db] = _get_db
    client = TestClient(app)
    latest = client.get("/api/pulse-live").json()
    back = client.get("/api/pulse-live?date=2026-08-10").json()
    dates = client.get("/api/pulse-live/dates").json()
    app.dependency_overrides.clear()

    assert [item["title"] for item in latest] == ["early morning"]  # latest IST day only
    assert [item["title"] for item in back] == ["late night"]
    assert [(d["date"], d["count"]) for d in dates] == [("2026-08-11", 1), ("2026-08-10", 1)]


def test_pulse_live_timestamps_carry_utc_marker(db_session):
    """Stored naive-UTC; serialized WITHOUT a zone marker the browser
    parses the string as local (IST) time and the wire clock renders
    5.5h early (caught live 2026-08-13)."""
    from datetime import datetime, timezone
    from fastapi.testclient import TestClient
    from app.main import app
    from app.models import Article
    from app.routers.articles import get_db

    app.dependency_overrides[get_db] = lambda: db_session
    db_session.add(Article(
        source="pulse_zerodha", provider="pulse_zerodha", url="https://x/1",
        title="t", content="c",
        published_at=datetime(2026, 8, 13, 6, 41, 41),  # naive UTC, as stored
    ))
    db_session.commit()

    row = TestClient(app).get("/api/pulse-live?limit=5").json()[0]

    assert row["published_at"].endswith("+00:00")
    app.dependency_overrides.clear()
