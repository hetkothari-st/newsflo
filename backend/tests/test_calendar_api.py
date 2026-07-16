from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.models import Alert, AlertCompany, Article, Company, utcnow
from app.routers.articles import get_db

IST = timezone(timedelta(hours=5, minutes=30))


def _make_company(session, ticker="RELIANCE.NS", name="Reliance Industries"):
    company = Company(ticker=ticker, name=name, sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    session.add(company)
    session.commit()
    return company


def _make_alert(session, created_at, title="headline", company=None):
    article = Article(source="test", url=f"https://example.com/{title}", title=title, status="ANALYZED")
    session.add(article)
    session.commit()
    alert = Alert(article_id=article.id, category="oil_energy", created_at=created_at)
    session.add(alert)
    session.commit()
    if company is not None:
        session.add(AlertCompany(
            alert_id=alert.id, company_id=company.id, direction="bullish",
            magnitude_low=1.0, magnitude_high=2.0, rationale="x", basis="direct_mention",
        ))
        session.commit()
    return alert


def test_counts_groups_by_ist_calendar_day(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    # 2026-07-16T20:00 IST == 2026-07-16T14:30 UTC -- squarely inside the day.
    _make_alert(db_session, datetime(2026, 7, 16, 14, 30, tzinfo=timezone.utc), title="a")
    _make_alert(db_session, datetime(2026, 7, 16, 15, 0, tzinfo=timezone.utc), title="b")
    # 2026-07-16T23:45 UTC is already 2026-07-17 in IST (+5:30) -- must land
    # in the next day's bucket, not the UTC day's.
    _make_alert(db_session, datetime(2026, 7, 16, 23, 45, tzinfo=timezone.utc), title="c")

    client = TestClient(app)
    body = client.get("/api/calendar/counts?year=2026&month=7").json()

    assert body["2026-07-16"] == 2
    assert body["2026-07-17"] == 1

    app.dependency_overrides.clear()


def test_counts_excludes_alerts_outside_requested_month(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    _make_alert(db_session, datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc), title="june")
    _make_alert(db_session, datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc), title="august")

    client = TestClient(app)
    body = client.get("/api/calendar/counts?year=2026&month=7").json()

    assert body == {}

    app.dependency_overrides.clear()


def test_counts_empty_month_returns_empty_dict(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    assert client.get("/api/calendar/counts?year=2026&month=7").json() == {}

    app.dependency_overrides.clear()


def test_counts_rejects_invalid_month(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    res = client.get("/api/calendar/counts?year=2026&month=13")

    assert res.status_code == 400

    app.dependency_overrides.clear()


def test_day_returns_alerts_for_that_ist_date_only(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    company = _make_company(db_session)
    in_day = _make_alert(db_session, datetime(2026, 7, 16, 10, 0, tzinfo=timezone.utc), title="in day", company=company)
    _make_alert(db_session, datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc), title="prior day", company=company)
    # 2026-07-16T23:45 UTC is IST 2026-07-17 -- must be excluded from the 16th.
    _make_alert(db_session, datetime(2026, 7, 16, 23, 45, tzinfo=timezone.utc), title="next ist day", company=company)

    client = TestClient(app)
    body = client.get("/api/calendar/day?date=2026-07-16").json()

    assert [a["article"]["title"] for a in body] == ["in day"]
    assert body[0]["id"] == in_day.id

    app.dependency_overrides.clear()


def test_day_orders_newest_first(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    company = _make_company(db_session)
    _make_alert(db_session, datetime(2026, 7, 16, 4, 0, tzinfo=timezone.utc), title="earlier", company=company)
    _make_alert(db_session, datetime(2026, 7, 16, 10, 0, tzinfo=timezone.utc), title="later", company=company)

    client = TestClient(app)
    body = client.get("/api/calendar/day?date=2026-07-16").json()

    assert [a["article"]["title"] for a in body] == ["later", "earlier"]

    app.dependency_overrides.clear()


def test_day_empty_when_no_alerts(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    assert client.get("/api/calendar/day?date=2026-07-16").json() == []

    app.dependency_overrides.clear()


def test_day_rejects_malformed_date(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    res = client.get("/api/calendar/day?date=not-a-date")

    assert res.status_code == 400

    app.dependency_overrides.clear()
