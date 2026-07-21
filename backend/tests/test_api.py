from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import event

from app.main import app
from app.models import Alert, AlertCompany, Article, CascadeGap, Company, ImpactEdge, utcnow
from app.routers.alerts import ALERTS_LIMIT, _build_graph
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
        confidence_score=85, time_horizon="Short-Term",
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
    assert body[0]["companies"][0]["confidence_score"] == 85
    assert body[0]["companies"][0]["time_horizon"] == "Short-Term"
    # Anonymous request (no Authorization header) -> in_my_holdings is present and False.
    assert body[0]["companies"][0]["in_my_holdings"] is False
    assert body[0]["article"]["title"] == "Test headline"
    assert body[0]["article"]["image_url"] == "https://example.com/x.jpg"
    # Only one alert exists for this company -- no prior history.
    assert body[0]["companies"][0]["past_mentions"] == []

    app.dependency_overrides.clear()


def test_list_alerts_excludes_alerts_from_previous_days(db_session):
    # The feed shows only today's (IST) news -- older news moved to the
    # calendar (GET /api/calendar/day) once that feature shipped, so the
    # main list must no longer mix in alerts from prior days.
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    yesterday_article = Article(source="test", url="https://example.com/yesterday", title="Yesterday headline", status="ANALYZED")
    db_session.add(yesterday_article)
    db_session.commit()
    db_session.add(Alert(article_id=yesterday_article.id, category="oil_energy", created_at=utcnow() - timedelta(days=1)))
    db_session.commit()

    today_article = Article(source="test", url="https://example.com/today", title="Today headline", status="ANALYZED")
    db_session.add(today_article)
    db_session.commit()
    db_session.add(Alert(article_id=today_article.id, category="oil_energy", created_at=utcnow()))
    db_session.commit()

    response = client.get("/api/alerts")

    assert response.status_code == 200
    titles = {a["article"]["title"] for a in response.json()}
    assert titles == {"Today headline"}

    app.dependency_overrides.clear()


def test_get_alert_by_id_still_works_for_an_alert_from_a_previous_day(db_session):
    # The per-alert detail endpoint is NOT date-restricted -- the calendar's
    # day view links into an old alert's full detail/charts by id, which
    # must keep working even though that alert no longer appears in the
    # (today-only) list endpoint.
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    article = Article(source="test", url="https://example.com/old-detail", title="Old headline", status="ANALYZED")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_energy", created_at=utcnow() - timedelta(days=3))
    db_session.add(alert)
    db_session.commit()

    list_response = client.get("/api/alerts")
    assert list_response.json() == []

    detail_response = client.get(f"/api/alerts/{alert.id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["article"]["title"] == "Old headline"

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
    older_alert = Alert(article_id=older_article.id, category="corporate_event", created_at=utcnow() - timedelta(days=1))
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
    newer_alert = Alert(article_id=newer_article.id, category="oil_energy", created_at=utcnow())
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
    # The list now only shows today's alert -- the older (yesterday's) one
    # is excluded from the list itself, but still surfaces as history via
    # past_mentions, which isn't date-windowed.
    assert list(body.keys()) == ["Newer Reliance story"]
    newer_mentions = body["Newer Reliance story"]["companies"][0]["past_mentions"]
    assert len(newer_mentions) == 1
    assert newer_mentions[0]["article_title"] == "Older Reliance story"
    assert newer_mentions[0]["direction"] == "bearish"

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


def test_list_alerts_includes_company_logo_url(db_session, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "brandfetch_client_id", "test-client-id")

    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    article = Article(
        source="test", url="https://example.com/logo", title="Logo test headline",
        status="ANALYZED", category="oil_energy",
    )
    db_session.add(article)
    db_session.commit()

    company = Company(
        ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas",
        index_tier="NIFTY50", market_cap=1.0, isin="INE002A01018",
    )
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
    assert response.json()[0]["companies"][0]["logo_url"] == (
        "https://cdn.brandfetch.io/isin/INE002A01018?c=test-client-id"
    )

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
    # Relative to now (not a fixed past date) -- the feed now only lists
    # today's (IST) alerts, so a fixed historical anchor would make every
    # seeded alert here invisible to GET /api/alerts.
    alert = Alert(
        article_id=article.id, category="oil_energy",
        created_at=utcnow() + timedelta(minutes=index),
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


def test_list_alerts_survives_nan_financial_fields(db_session):
    # Reproduces a production 500: a division-by-zero bug in
    # app.outcomes.price_fetcher (since fixed) persisted NaN into
    # AlertCompany.return_1m/return_3m/price_at_analysis. NaN is valid
    # Python but not valid JSON -- Starlette's JSONResponse raised
    # ValueError and took down the whole /api/alerts endpoint on the first
    # row that had one. Old rows with NaN already in the DB must still
    # serialize cleanly (as null) rather than 500ing again.
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    article = Article(source="test", url="https://example.com/nan", title="Nan headline", status="ANALYZED")
    db_session.add(article)
    db_session.commit()
    company = Company(ticker="NANCO.NS", name="Nan Co", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="x", basis="direct_mention",
        price_at_analysis=float("nan"), return_1m=float("nan"), return_3m=float("inf"),
    ))
    db_session.commit()

    response = client.get("/api/alerts")

    assert response.status_code == 200
    company_payload = response.json()[0]["companies"][0]
    assert company_payload["price_at_analysis"] is None
    assert company_payload["return_1m"] is None
    assert company_payload["return_3m"] is None

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
    single_body = single_response.json()
    list_item = list_response.json()[0]
    # GET /api/alerts/{id} additively includes a "graph" key that the list
    # endpoint intentionally omits (see test_list_alerts_response_has_no_graph_key)
    # -- every other field must still match exactly.
    assert "graph" in single_body
    assert "graph" not in list_item
    single_body_without_graph = {k: v for k, v in single_body.items() if k != "graph"}
    assert single_body_without_graph == list_item

    app.dependency_overrides.clear()


def test_get_alert_by_id_404s_for_missing_alert(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    response = client.get("/api/alerts/999999")

    assert response.status_code == 404

    app.dependency_overrides.clear()


def test_list_alerts_includes_reasoning_engine_fields(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    article = Article(source="test", url="https://example.com/reasoning-fields", title="Test headline", status="ANALYZED", category="oil_energy")
    db_session.add(article)
    db_session.commit()

    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    alert = Alert(article_id=article.id, category="oil_energy", event_type="crude_oil")
    db_session.add(alert)
    db_session.commit()

    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin",
        basis="direct_mention", confidence="llm_estimate",
        confidence_score=72, confidence_band="HIGH",
        confidence_contributors_json='["c"]',
        confidence_penalties_json='[]',
        reasons_json='["Refining margins widen."]',
        evidence_refs_json='["RULE_CRUDE_OIL_UP"]',
        risks_json='["Margin reversal."]',
        assumptions_json='["Crude stays elevated."]',
        unknowns_json='["Duration of the spike."]',
        alternative_hypothesis="Already priced in.",
    ))
    db_session.commit()

    response = client.get("/api/alerts")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["event_type"] == "crude_oil"
    company_payload = body[0]["companies"][0]
    assert company_payload["confidence_band"] == "HIGH"
    assert company_payload["confidence_contributors"] == ["c"]
    assert company_payload["confidence_penalties"] == []
    assert company_payload["reasons"] == ["Refining margins widen."]
    assert company_payload["evidence_refs"] == ["RULE_CRUDE_OIL_UP"]
    assert company_payload["risks"] == ["Margin reversal."]
    assert company_payload["assumptions"] == ["Crude stays elevated."]
    assert company_payload["unknowns"] == ["Duration of the spike."]
    assert company_payload["alternative_hypothesis"] == "Already priced in."

    app.dependency_overrides.clear()


def test_list_alerts_defaults_reasoning_engine_fields_for_legacy_rows(db_session):
    # Rows persisted before this feature shipped have NULL in every new
    # column -- the API must degrade to empty lists/None, never 500.
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    article = Article(source="test", url="https://example.com/legacy-reasoning", title="Legacy", status="ANALYZED", category="oil_energy")
    db_session.add(article)
    db_session.commit()
    company = Company(ticker="LEGACY.NS", name="Legacy Co", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="legacy row",
        basis="direct_mention", confidence="llm_estimate",
    ))
    db_session.commit()

    response = client.get("/api/alerts")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["event_type"] is None
    company_payload = body[0]["companies"][0]
    assert company_payload["reasons"] == []
    assert company_payload["evidence_refs"] == []
    assert company_payload["confidence_band"] is None
    assert company_payload["alternative_hypothesis"] is None
    assert company_payload["sub_sector"] is None

    app.dependency_overrides.clear()


def test_get_alert_includes_company_sub_sector(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    article = Article(source="test", url="https://example.com/sub-sector", title="Test headline", status="ANALYZED", category="banking")
    db_session.add(article)
    db_session.commit()

    company = Company(
        ticker="HDFCBANK.NS", name="HDFC Bank", sector="banking", sub_sector="private_bank",
        index_tier="NIFTY50", market_cap=1.0,
    )
    db_session.add(company)
    db_session.commit()

    alert = Alert(article_id=article.id, category="banking")
    db_session.add(alert)
    db_session.commit()

    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="rate cut",
        basis="direct_mention", confidence="llm_estimate",
    ))
    db_session.commit()

    response = client.get(f"/api/alerts/{alert.id}")

    assert response.status_code == 200
    assert response.json()["companies"][0]["sub_sector"] == "private_bank"

    app.dependency_overrides.clear()


def test_list_alerts_includes_financial_context_fields(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    article = Article(source="test", url="https://example.com/financial-fields", title="Test headline", status="ANALYZED", category="oil_energy")
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
        price_at_analysis=2500.5, return_1m=-12.0, return_3m=-20.0,
        contradiction_note="Price down 12.0% over the past month despite bullish call.",
    ))
    db_session.commit()

    response = client.get("/api/alerts")

    assert response.status_code == 200
    body = response.json()
    company_payload = body[0]["companies"][0]
    assert company_payload["price_at_analysis"] == 2500.5
    assert company_payload["return_1m"] == -12.0
    assert company_payload["return_3m"] == -20.0
    assert company_payload["contradiction_note"] == "Price down 12.0% over the past month despite bullish call."

    app.dependency_overrides.clear()


def test_list_alerts_defaults_financial_context_fields_for_legacy_rows(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    article = Article(source="test", url="https://example.com/financial-fields-legacy", title="Legacy", status="ANALYZED", category="oil_energy")
    db_session.add(article)
    db_session.commit()
    company = Company(ticker="LEGACY.NS", name="Legacy Co", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="legacy row",
        basis="direct_mention", confidence="llm_estimate",
    ))
    db_session.commit()

    response = client.get("/api/alerts")

    assert response.status_code == 200
    company_payload = response.json()[0]["companies"][0]
    assert company_payload["price_at_analysis"] is None
    assert company_payload["contradiction_note"] is None

    app.dependency_overrides.clear()


def test_get_alert_includes_impact_level_and_parent_company_id(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    article = Article(source="test", url="https://example.com/impact-level", title="Chip export ban", status="ANALYZED", category="tech")
    db_session.add(article)
    db_session.commit()

    direct = Company(ticker="NVDA.NS", name="Nvidia", sector="it", index_tier="NIFTY50", market_cap=1.0)
    supplier = Company(ticker="TSM.NS", name="TSMC", sector="it", index_tier="NIFTY50", market_cap=1.0)
    db_session.add_all([direct, supplier])
    db_session.commit()

    alert = Alert(article_id=article.id, category="tech")
    db_session.add(alert)
    db_session.commit()

    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=direct.id, direction="bearish",
        magnitude_low=2.0, magnitude_high=4.0, rationale="export ban",
        basis="direct_mention", confidence="llm_estimate", impact_level="direct",
    ))
    db_session.commit()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=supplier.id, direction="bearish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="fabs Nvidia chips",
        basis="direct_mention", confidence="llm_estimate",
        impact_level="indirect_l1", parent_company_id=direct.id,
    ))
    db_session.commit()

    response = client.get(f"/api/alerts/{alert.id}")

    assert response.status_code == 200
    companies = {c["company_id"]: c for c in response.json()["companies"]}
    assert companies[direct.id]["impact_level"] == "direct"
    assert companies[direct.id]["parent_company_id"] is None
    assert companies[supplier.id]["impact_level"] == "indirect_l1"
    assert companies[supplier.id]["parent_company_id"] == direct.id

    app.dependency_overrides.clear()


def test_list_alerts_defaults_impact_level_to_direct_for_legacy_rows(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    article = Article(source="test", url="https://example.com/impact-level-legacy", title="Legacy", status="ANALYZED", category="oil_energy")
    db_session.add(article)
    db_session.commit()
    company = Company(ticker="LEGACY2.NS", name="Legacy Co 2", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="legacy row",
        basis="direct_mention", confidence="llm_estimate",
    ))
    db_session.commit()

    response = client.get("/api/alerts")

    assert response.status_code == 200
    company_payload = response.json()[0]["companies"][0]
    assert company_payload["impact_level"] == "direct"
    assert company_payload["parent_company_id"] is None

    app.dependency_overrides.clear()


def _make_alert_with_companies(db_session, companies_spec):
    """companies_spec: list of (ticker, name, sector, direction) tuples.
    Returns the persisted Alert with .companies populated (matches this
    file's existing fixture style -- adjust to it if it differs)."""
    article = Article(source="test", url=f"https://example.com/{id(companies_spec)}", title="Test article", content="c")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_gas", event_type="repo_rate_change")
    db_session.add(alert)
    db_session.flush()
    for ticker, name, sector, direction in companies_spec:
        company = db_session.query(Company).filter_by(ticker=ticker).one_or_none()
        if company is None:
            company = Company(ticker=ticker, name=name, sector=sector, index_tier="NIFTY50", market_cap=1.0)
            db_session.add(company)
            db_session.flush()
        db_session.add(AlertCompany(
            alert_id=alert.id, company_id=company.id, direction=direction,
            magnitude_low=1.0, magnitude_high=2.0, rationale="r",
            confidence_score=70, impact_level="direct",
            basis="direct_mention",  # NOT NULL column with no default; the brief's
            # sample fixture omitted it, but this file's existing tests always set it.
        ))
    db_session.commit()
    db_session.refresh(alert)
    return alert


def test_build_graph_legacy_alert_with_no_edges_still_has_news_and_company_nodes(db_session):
    alert = _make_alert_with_companies(db_session, [("RELIANCE.NS", "Reliance Industries", "oil_gas", "bullish")])

    graph = _build_graph(alert, held_company_ids=set())

    node_ids = {n["id"] for n in graph["nodes"]}
    assert "news" in node_ids
    assert "company:" + str(alert.companies[0].company_id) in node_ids
    assert graph["gaps"] == []
    # Degrade-safely fallback: news connects straight to the company when
    # there are no real ImpactEdge rows to derive a richer path from.
    assert any(e["from"] == "news" and e["to"] == f"company:{alert.companies[0].company_id}" for e in graph["edges"])


def test_build_graph_dedupes_sector_node_reached_by_multiple_edges(db_session):
    alert = _make_alert_with_companies(db_session, [
        ("HDFCBANK.NS", "HDFC Bank", "banking", "bullish"),
        ("ICICIBANK.NS", "ICICI Bank", "banking", "bullish"),
    ])
    for ac in alert.companies:
        db_session.add(ImpactEdge(
            alert_id=alert.id,
            from_node_kind="sector", from_label="banking", from_company_id=None,
            to_node_kind="company", to_label=ac.company.ticker, to_company_id=ac.company_id,
            relation="demand", direction="bullish", note="n", source="llm_only",
        ))
    db_session.commit()
    db_session.refresh(alert)

    graph = _build_graph(alert, held_company_ids=set())

    sector_nodes = [n for n in graph["nodes"] if n["id"] == "sector:banking"]
    assert len(sector_nodes) == 1
    # 2 original edges + 1 root->news edge: "sector:banking" is a `from` in
    # both edges and never a `to` anywhere in this alert, so per the
    # root-detection logic (see test_build_graph_root_mechanism_connects_to_news)
    # it is legitimately the chain root and news connects to it once. The
    # point under test here is node dedup, not edge count.
    assert len(graph["edges"]) == 3  # both original edges present, only the node deduped


def test_build_graph_mechanism_labels_slugified_deterministically(db_session):
    alert = _make_alert_with_companies(db_session, [("HDFCBANK.NS", "HDFC Bank", "banking", "bullish")])
    db_session.add(ImpactEdge(
        alert_id=alert.id,
        from_node_kind="mechanism", from_label="Repo Rate ↓", from_company_id=None,
        to_node_kind="mechanism", to_label="Borrowing Costs ↓", to_company_id=None,
        relation="credit_cost", direction="bullish", note="n", source="rulebook_verified",
    ))
    db_session.commit()
    db_session.refresh(alert)

    graph = _build_graph(alert, held_company_ids=set())

    node_ids = {n["id"] for n in graph["nodes"]}
    assert "mech:repo_rate_down" in node_ids
    assert "mech:borrowing_costs_down" in node_ids


def test_build_graph_root_mechanism_connects_to_news(db_session):
    alert = _make_alert_with_companies(db_session, [("HDFCBANK.NS", "HDFC Bank", "banking", "bullish")])
    db_session.add(ImpactEdge(
        alert_id=alert.id,
        from_node_kind="mechanism", from_label="Repo Rate ↓", from_company_id=None,
        to_node_kind="sector", to_label="banking", to_company_id=None,
        relation="credit_cost", direction="bullish", note="n", source="rulebook_verified",
    ))
    db_session.add(ImpactEdge(
        alert_id=alert.id,
        from_node_kind="sector", from_label="banking", from_company_id=None,
        to_node_kind="company", to_label="HDFCBANK.NS", to_company_id=alert.companies[0].company_id,
        relation="demand", direction="bullish", note="n2", source="llm_only",
    ))
    db_session.commit()
    db_session.refresh(alert)

    graph = _build_graph(alert, held_company_ids=set())

    # "Repo Rate ↓" is never a `to` anywhere in this alert -- it's the root,
    # and must be the thing news connects to (not "banking", which IS a
    # `to` of the first edge and therefore not a root).
    news_edges = [e for e in graph["edges"] if e["from"] == "news"]
    assert len(news_edges) == 1
    assert news_edges[0]["to"] == "mech:repo_rate_down"
    assert news_edges[0]["direction"] == "bullish"  # inherited from the root's own outbound edge


def test_build_graph_includes_gaps(db_session):
    alert = _make_alert_with_companies(db_session, [("RELIANCE.NS", "Reliance Industries", "oil_gas", "bullish")])
    db_session.add(CascadeGap(
        alert_id=alert.id, sector="consumer_durables", impact_level="indirect_l1",
        parent_ticker=None, attempts=2, last_error="rate limited",
    ))
    db_session.commit()
    db_session.refresh(alert)

    graph = _build_graph(alert, held_company_ids=set())

    assert graph["gaps"] == [{"sector": "consumer_durables", "impact_level": "indirect_l1", "reason": "rate limited"}]


def test_build_graph_company_node_carries_in_my_holdings(db_session):
    alert = _make_alert_with_companies(db_session, [("RELIANCE.NS", "Reliance Industries", "oil_gas", "bullish")])
    company_id = alert.companies[0].company_id

    graph = _build_graph(alert, held_company_ids={company_id})

    company_node = next(n for n in graph["nodes"] if n["id"] == f"company:{company_id}")
    assert company_node["in_my_holdings"] is True
    assert company_node["ticker"] == "RELIANCE.NS"
    assert company_node["direction"] == "bullish"


def test_build_graph_drops_edge_referencing_a_company_not_in_this_alert(db_session, caplog):
    alert = _make_alert_with_companies(db_session, [("RELIANCE.NS", "Reliance Industries", "oil_gas", "bullish")])
    # from_company_id points at a real company row, but one that is NOT
    # among this alert's own companies -- must be dropped, not crash.
    other_company = Company(ticker="TCS.NS", name="TCS", sector="it", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(other_company)
    db_session.commit()
    db_session.add(ImpactEdge(
        alert_id=alert.id,
        from_node_kind="company", from_label="TCS.NS", from_company_id=other_company.id,
        to_node_kind="sector", to_label="it", to_company_id=None,
        relation="competitor", direction="bearish", note="n", source="llm_only",
    ))
    db_session.commit()
    db_session.refresh(alert)

    graph = _build_graph(alert, held_company_ids=set())

    assert not any(e["from"] == f"company:{other_company.id}" for e in graph["edges"])
    node_ids = {n["id"] for n in graph["nodes"]}
    assert f"company:{other_company.id}" not in node_ids


def test_get_alert_response_includes_graph(db_session):
    # Adapted to this file's established pattern -- there is no `client`
    # fixture in this file; every route-level test wires its own
    # TestClient via app.dependency_overrides[get_db] (see
    # test_get_alert_by_id_still_works_for_an_alert_from_a_previous_day above).
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    alert = _make_alert_with_companies(db_session, [("RELIANCE.NS", "Reliance Industries", "oil_gas", "bullish")])

    response = client.get(f"/api/alerts/{alert.id}")

    assert response.status_code == 200
    body = response.json()
    assert "graph" in body
    assert "nodes" in body["graph"]
    assert "edges" in body["graph"]
    assert "gaps" in body["graph"]
    assert any(n["id"] == "news" for n in body["graph"]["nodes"])
    # companies[] is completely unaffected by this change.
    assert body["companies"][0]["ticker"] == "RELIANCE.NS"

    app.dependency_overrides.clear()


def test_list_alerts_response_has_no_graph_key(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    _make_alert_with_companies(db_session, [("RELIANCE.NS", "Reliance Industries", "oil_gas", "bullish")])

    response = client.get("/api/alerts")

    assert response.status_code == 200
    body = response.json()
    assert len(body) >= 1
    assert "graph" not in body[0]

    app.dependency_overrides.clear()
