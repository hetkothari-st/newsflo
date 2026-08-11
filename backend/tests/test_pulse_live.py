

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
