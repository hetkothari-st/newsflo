from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import event

from app.main import app
from app.models import Alert, AlertCompany, Article, Company
from app.routers.alerts import ALERTS_LIMIT
from app.routers.articles import get_db


def test_list_alerts_returns_nested_companies(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    article = Article(
        source="test", url="https://example.com/x", title="Test headline",
        status="ANALYZED", category="oil_energy", image_url="https://example.com/x.jpg",
    )
    db_session.add(article)
    db_session.commit()

    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()

    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin",
        key_points_json='["Crude prices ease", "Refining margins widen"]',
        basis="direct_mention", confidence="llm_estimate",
    ))
    db_session.commit()

    response = client.get("/api/alerts")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["companies"][0]["ticker"] == "RELIANCE.NS"
    assert body[0]["companies"][0]["market"] == "IN"
    assert body[0]["companies"][0]["confidence"] == "llm_estimate"
    assert body[0]["companies"][0]["key_points"] == ["Crude prices ease", "Refining margins widen"]
    # Anonymous request (no Authorization header) -> in_my_holdings is present and False.
    assert body[0]["companies"][0]["in_my_holdings"] is False
    assert body[0]["article"]["title"] == "Test headline"
    assert body[0]["article"]["image_url"] == "https://example.com/x.jpg"
    # Only one alert exists for this company -- no prior history.
    assert body[0]["companies"][0]["past_mentions"] == []

    app.dependency_overrides.clear()


def test_list_alerts_includes_past_mentions_for_the_same_company(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    older_article = Article(source="test", url="https://example.com/older", title="Older Reliance story", status="ANALYZED")
    db_session.add(older_article)
    db_session.commit()
    older_alert = Alert(article_id=older_article.id, category="corporate_event", created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    db_session.add(older_alert)
    db_session.commit()
    db_session.add(AlertCompany(
        alert_id=older_alert.id, company_id=company.id, direction="bearish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="older reasoning", basis="direct_mention",
    ))
    db_session.commit()

    newer_article = Article(source="test", url="https://example.com/newer", title="Newer Reliance story", status="ANALYZED")
    db_session.add(newer_article)
    db_session.commit()
    newer_alert = Alert(article_id=newer_article.id, category="oil_energy", created_at=datetime(2026, 6, 1, tzinfo=timezone.utc))
    db_session.add(newer_alert)
    db_session.commit()
    db_session.add(AlertCompany(
        alert_id=newer_alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="newer reasoning", basis="direct_mention",
    ))
    db_session.commit()

    response = client.get("/api/alerts")

    assert response.status_code == 200
    body = {a["article"]["title"]: a for a in response.json()}
    # The newer alert's company sees the older one as history.
    newer_mentions = body["Newer Reliance story"]["companies"][0]["past_mentions"]
    assert len(newer_mentions) == 1
    assert newer_mentions[0]["article_title"] == "Older Reliance story"
    assert newer_mentions[0]["direction"] == "bearish"
    # The older alert has no history of its own.
    assert body["Older Reliance story"]["companies"][0]["past_mentions"] == []

    app.dependency_overrides.clear()


def test_list_alerts_defaults_key_points_to_empty_list_for_legacy_rows(db_session):
    # AlertCompany rows written before key_points existed have
    # key_points_json = NULL -- must not crash, must serialize to [].
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    article = Article(source="test", url="https://example.com/legacy", title="Legacy headline", status="ANALYZED", category="oil_energy")
    db_session.add(article)
    db_session.commit()
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin",
        basis="direct_mention", confidence="llm_estimate",
    ))
    db_session.commit()

    response = client.get("/api/alerts")

    assert response.status_code == 200
    assert response.json()[0]["companies"][0]["key_points"] == []

    app.dependency_overrides.clear()


def test_list_alerts_flags_in_my_holdings_for_authenticated_holder(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    article = Article(source="test", url="https://example.com/z", title="Oil headline", status="ANALYZED", category="oil_energy")
    db_session.add_all([company, article])
    db_session.commit()

    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=2.0, magnitude_high=4.0, rationale="margin",
        basis="direct_mention", confidence="llm_estimate",
    ))
    db_session.commit()

    token = client.post(
        "/api/auth/register", json={"email": "alertholder@example.com", "password": "pw12345"},
    ).json()["access_token"]
    client.post(
        "/api/holdings", json={"ticker": "RELIANCE.NS", "quantity": 5},
        headers={"Authorization": f"Bearer {token}"},
    )

    response = client.get("/api/alerts", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()[0]["companies"][0]["in_my_holdings"] is True

    app.dependency_overrides.clear()


def test_list_alerts_includes_company_sector(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    article = Article(
        source="test", url="https://example.com/sector", title="Sector test headline",
        status="ANALYZED", category="oil_energy",
    )
    db_session.add(article)
    db_session.commit()

    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()

    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin",
        basis="direct_mention", confidence="llm_estimate",
    ))
    db_session.commit()

    response = client.get("/api/alerts")

    assert response.status_code == 200
    assert response.json()[0]["companies"][0]["sector"] == "oil_gas"

    app.dependency_overrides.clear()


def _seed_alert_with_company(db_session, index: int) -> None:
    company = Company(
        ticker=f"CO{index}.NS", name=f"Company {index}", sector="oil_gas",
        index_tier="NIFTY50", market_cap=1.0,
    )
    article = Article(
        source="test", url=f"https://example.com/n-plus-one/{index}", title=f"Headline {index}",
        status="ANALYZED", category="oil_energy",
    )
    db_session.add_all([company, article])
    db_session.commit()
    alert = Alert(
        article_id=article.id, category="oil_energy",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index),
    )
    db_session.add(alert)
    db_session.commit()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="x", basis="direct_mention",
    ))
    db_session.commit()


def test_list_alerts_query_count_does_not_scale_with_alert_count(db_session):
    # The regression this guards against: routers/alerts.py used to call
    # get_past_mentions once per (alert, company) pair and lazy-load each
    # alert's .companies/.article/.company relationship one row at a time,
    # so query count grew linearly with the number of alerts returned --
    # fast on same-process SQLite, but 569 queries measured locally for 248
    # real alerts, which pays real network round-trip latency per query
    # against a separate Postgres service in production.
    for i in range(15):
        _seed_alert_with_company(db_session, i)

    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    query_count = 0

    def _count(*args, **kwargs):
        nonlocal query_count
        query_count += 1

    event.listen(db_session.get_bind(), "before_cursor_execute", _count)
    try:
        response = client.get("/api/alerts")
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", _count)

    assert response.status_code == 200
    assert len(response.json()) == 15
    # A small, roughly-constant number of bulk queries regardless of alert
    # count -- not the 30+ a one-query-per-alert-per-company pattern would
    # produce for 15 alerts (main query + companies + article + company +
    # 4 bulk lookups, generously bounded well under 15).
    assert query_count < 15

    app.dependency_overrides.clear()


def test_list_alerts_limits_to_the_most_recent_alerts(db_session):
    for i in range(ALERTS_LIMIT + 5):
        _seed_alert_with_company(db_session, i)

    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    response = client.get("/api/alerts")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == ALERTS_LIMIT
    # The 5 oldest (lowest index -> earliest created_at) alerts are dropped;
    # the most recent ALERTS_LIMIT survive.
    titles = {a["article"]["title"] for a in body}
    assert "Headline 0" not in titles
    assert "Headline 4" not in titles
    assert f"Headline {ALERTS_LIMIT + 4}" in titles

    app.dependency_overrides.clear()


def test_list_articles_returns_all(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    db_session.add(Article(source="test", url="https://example.com/y", title="Another headline"))
    db_session.commit()

    response = client.get("/api/articles")

    assert response.status_code == 200
    assert response.json()[0]["title"] == "Another headline"
    assert response.json()[0]["image_url"] is None

    app.dependency_overrides.clear()


def test_get_alert_by_id_returns_same_shape_as_list_alerts(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    article = Article(
        source="test", url="https://example.com/single", title="Single alert headline",
        status="ANALYZED", category="oil_energy", image_url="https://example.com/single.jpg",
    )
    db_session.add(article)
    db_session.commit()

    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()

    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin",
        key_points_json='["Crude prices ease", "Refining margins widen"]',
        basis="direct_mention", confidence="llm_estimate",
    ))
    db_session.commit()

    list_response = client.get("/api/alerts")
    single_response = client.get(f"/api/alerts/{alert.id}")

    assert single_response.status_code == 200
    assert single_response.json() == list_response.json()[0]

    app.dependency_overrides.clear()


def test_get_alert_by_id_404s_for_missing_alert(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    response = client.get("/api/alerts/999999")

    assert response.status_code == 404

    app.dependency_overrides.clear()
