from types import SimpleNamespace

import pytest

import app.pipeline as pipeline_module
from app.analysis.schemas import AnalysisOutput, CompanyMention
from app.ingestion.poller import fetch_new_articles
from app.models import CalibrationSample, Company, EmailNotification
from app.pipeline import process_new_articles


def test_full_pipeline_from_rss_entry_to_alert(db_session, monkeypatch):
    db_session.add(Company(
        ticker="RELIANCE.NS", name="Reliance Industries",
        sector="oil_gas", index_tier="NIFTY50", market_cap=1_800_000.0,
    ))
    db_session.commit()

    feed_entries = [{
        "link": "https://example.com/breaking-oil-news",
        "title": "US strikes Iran oil export sites",
        "summary": "Crude oil markets react sharply to the strikes.",
    }]

    def fake_parse(url):
        return SimpleNamespace(entries=feed_entries)

    monkeypatch.setattr("app.ingestion.poller.feedparser.parse", fake_parse)

    inserted = fetch_new_articles(db_session, [{"source": "test_feed", "url": "http://feed.test/rss"}])
    assert inserted == 1

    fake_output = AnalysisOutput(
        category="oil_energy",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)

    created = process_new_articles(db_session, claude_client=object())
    assert created == 1

    from app.main import app as fastapi_app
    from app.routers.articles import get_db
    from fastapi.testclient import TestClient

    fastapi_app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(fastapi_app)

    response = client.get("/api/alerts")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["article"]["title"] == "US strikes Iran oil export sites"
    assert body[0]["companies"][0]["ticker"] == "RELIANCE.NS"
    # No calibration samples exist for this pair, so it stays LLM-only.
    assert body[0]["companies"][0]["confidence"] == "llm_estimate"
    # No authenticated user on this request -> in_my_holdings is False.
    assert body[0]["companies"][0]["in_my_holdings"] is False

    fastapi_app.dependency_overrides.clear()


def test_full_pipeline_shows_calibrated_confidence_with_enough_samples(db_session, monkeypatch):
    company = Company(
        ticker="RELIANCE.NS", name="Reliance Industries",
        sector="oil_gas", index_tier="NIFTY50", market_cap=1_800_000.0,
    )
    db_session.add(company)
    db_session.commit()

    # Pre-seed 5 historical outcomes of [1, 2, 3, 4, 5] for (oil_energy, this company)
    # -> mean = 3.0, pstdev = sqrt(2) ~= 1.41421356 -> calibrated range applies.
    for i, actual in enumerate([1.0, 2.0, 3.0, 4.0, 5.0]):
        db_session.add(CalibrationSample(
            alert_company_id=i + 1, category="oil_energy", company_id=company.id,
            direction="bullish", magnitude_actual=actual, horizon_days=1,
        ))
    db_session.commit()

    feed_entries = [{
        "link": "https://example.com/breaking-oil-news-2",
        "title": "US strikes Iran oil export sites",
        "summary": "Crude oil markets react sharply to the strikes.",
    }]

    def fake_parse(url):
        return SimpleNamespace(entries=feed_entries)

    monkeypatch.setattr("app.ingestion.poller.feedparser.parse", fake_parse)

    inserted = fetch_new_articles(db_session, [{"source": "test_feed", "url": "http://feed.test/rss"}])
    assert inserted == 1

    fake_output = AnalysisOutput(
        category="oil_energy",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)

    created = process_new_articles(db_session, claude_client=object())
    assert created == 1

    from app.main import app as fastapi_app
    from app.routers.articles import get_db
    from fastapi.testclient import TestClient

    fastapi_app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(fastapi_app)

    response = client.get("/api/alerts")
    assert response.status_code == 200
    company_payload = response.json()[0]["companies"][0]
    assert company_payload["confidence"] == "calibrated"
    assert company_payload["magnitude_low"] == pytest.approx(3.0 - 2 ** 0.5)
    assert company_payload["magnitude_high"] == pytest.approx(3.0 + 2 ** 0.5)

    fastapi_app.dependency_overrides.clear()


def test_full_pipeline_notifies_holder_end_to_end(db_session, monkeypatch):
    from app.main import app as fastapi_app
    from app.routers.articles import get_db
    from fastapi.testclient import TestClient

    fastapi_app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(fastapi_app)

    # Seed the company the analysis will resolve to.
    db_session.add(Company(
        ticker="RELIANCE.NS", name="Reliance Industries",
        sector="oil_gas", index_tier="NIFTY50", market_cap=1_800_000.0,
    ))
    db_session.commit()

    # Register a real user and add a holding through the real HTTP endpoints.
    token = client.post(
        "/api/auth/register", json={"email": "e2e@example.com", "password": "pw12345"},
    ).json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}
    add_resp = client.post("/api/holdings", json={"ticker": "RELIANCE.NS", "quantity": 15}, headers=auth)
    assert add_resp.status_code == 200

    # Ingest one RSS article.
    feed_entries = [{
        "link": "https://example.com/breaking-oil-news-e2e",
        "title": "US strikes Iran oil export sites",
        "summary": "Crude oil markets react sharply to the strikes.",
    }]
    monkeypatch.setattr(
        "app.ingestion.poller.feedparser.parse",
        lambda url: SimpleNamespace(entries=feed_entries),
    )
    inserted = fetch_new_articles(db_session, [{"source": "test_feed", "url": "http://feed.test/rss"}])
    assert inserted == 1

    # Run the pipeline with a mocked Claude analysis resolving to the held company.
    fake_output = AnalysisOutput(
        category="oil_energy",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)

    created = process_new_articles(db_session, claude_client=object())
    assert created == 1

    # (a) The alerts API shows in_my_holdings True for this user's held company.
    response = client.get("/api/alerts", headers=auth)
    assert response.status_code == 200
    assert response.json()[0]["companies"][0]["in_my_holdings"] is True

    # (b) Exactly one EmailNotification row exists, marked sent (console backend).
    notifications = db_session.query(EmailNotification).all()
    assert len(notifications) == 1
    assert notifications[0].status == "sent"

    fastapi_app.dependency_overrides.clear()
