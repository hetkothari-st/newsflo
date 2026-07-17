from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Alert, AlertCompany, Article, ArticleTranslation, CalibrationSample, Company, utcnow
from app.routers.articles import get_db


def _seed(db_session):
    db_session.add_all([
        Company(ticker="RELIANCE.NS", name="Reliance", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0),
        Company(ticker="500325.BO", name="Reliance BSE", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0),
        Company(ticker="AAPL", name="Apple", sector="it", index_tier="GLOBAL_LARGE_CAP", market_cap=None),
        Company(ticker="XOM", name="ExxonMobil", sector="oil_gas", index_tier="GLOBAL_LARGE_CAP", market_cap=None),
    ])
    db_session.commit()


def test_list_companies_unfiltered_returns_all(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    _seed(db_session)
    client = TestClient(app)

    body = client.get("/api/companies").json()

    assert {c["ticker"] for c in body} == {"RELIANCE.NS", "500325.BO", "AAPL", "XOM"}
    reliance = next(c for c in body if c["ticker"] == "RELIANCE.NS")
    assert reliance["market"] == "IN"
    assert reliance["sector"] == "oil_gas"
    apple = next(c for c in body if c["ticker"] == "AAPL")
    assert apple["market"] == "GLOBAL"
    assert apple["index_tier"] == "GLOBAL_LARGE_CAP"

    app.dependency_overrides.clear()


def test_list_companies_filter_india(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    _seed(db_session)
    client = TestClient(app)

    body = client.get("/api/companies?market=IN").json()

    assert {c["ticker"] for c in body} == {"RELIANCE.NS", "500325.BO"}
    assert all(c["market"] == "IN" for c in body)

    app.dependency_overrides.clear()


def test_list_companies_filter_global(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    _seed(db_session)
    client = TestClient(app)

    body = client.get("/api/companies?market=GLOBAL").json()

    assert {c["ticker"] for c in body} == {"AAPL", "XOM"}
    assert all(c["market"] == "GLOBAL" for c in body)

    app.dependency_overrides.clear()


def test_list_companies_includes_isin_and_logo_url(db_session, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "brandfetch_client_id", "")

    app.dependency_overrides[get_db] = lambda: db_session
    db_session.add(Company(
        ticker="RELIANCE.NS", name="Reliance", sector="oil_gas",
        index_tier="NIFTY50", market_cap=1.0, isin="INE002A01018",
    ))
    db_session.commit()
    client = TestClient(app)

    body = client.get("/api/companies").json()

    row = next(c for c in body if c["ticker"] == "RELIANCE.NS")
    assert row["isin"] == "INE002A01018"
    assert row["logo_url"] is None  # no client id configured

    app.dependency_overrides.clear()


def test_list_companies_logo_url_uses_isin_when_client_id_set(db_session, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "brandfetch_client_id", "test-client-id")

    app.dependency_overrides[get_db] = lambda: db_session
    db_session.add_all([
        Company(
            ticker="RELIANCE.NS", name="Reliance", sector="oil_gas",
            index_tier="NIFTY50", market_cap=1.0, isin="INE002A01018",
        ),
        Company(ticker="AAPL", name="Apple", sector="it", index_tier="GLOBAL_LARGE_CAP", market_cap=None),
    ])
    db_session.commit()
    client = TestClient(app)

    body = client.get("/api/companies").json()

    reliance = next(c for c in body if c["ticker"] == "RELIANCE.NS")
    apple = next(c for c in body if c["ticker"] == "AAPL")
    assert reliance["logo_url"] == "https://cdn.brandfetch.io/isin/INE002A01018?c=test-client-id"
    assert apple["logo_url"] == "https://cdn.brandfetch.io/ticker/AAPL?c=test-client-id"

    app.dependency_overrides.clear()

    app.dependency_overrides.clear()


def test_branding_logo_url_importable_from_shared_module(db_session, monkeypatch):
    from app.companies.branding import logo_url
    from app.config import settings
    from app.models import Company

    monkeypatch.setattr(settings, "brandfetch_client_id", "test-client-id")
    company = Company(ticker="AAPL", name="Apple", sector="it", index_tier="GLOBAL_LARGE_CAP", market_cap=None)

    assert logo_url(company) == "https://cdn.brandfetch.io/ticker/AAPL?c=test-client-id"


def _make_alert_company(db_session, company, direction="bullish", url_suffix="a", created_at=None):
    article = Article(source="test", url=f"https://example.com/{url_suffix}", title=f"headline {url_suffix}", status="ANALYZED")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_energy", created_at=created_at or utcnow())
    db_session.add(alert)
    db_session.commit()
    ac = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction=direction,
        magnitude_low=1.0, magnitude_high=2.0, rationale="why it matters", basis="direct_mention",
    )
    db_session.add(ac)
    db_session.commit()
    return ac


def test_get_company_profile_404_for_unknown_id(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    resp = client.get("/api/companies/999/profile")

    assert resp.status_code == 404
    app.dependency_overrides.clear()


def test_get_company_profile_404_for_global_company(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    company = Company(ticker="AAPL", name="Apple", sector="it", index_tier="GLOBAL_LARGE_CAP", market_cap=None)
    db_session.add(company)
    db_session.commit()
    client = TestClient(app)

    resp = client.get(f"/api/companies/{company.id}/profile")

    assert resp.status_code == 404
    app.dependency_overrides.clear()


def test_get_company_profile_includes_latest_alert(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    company = Company(ticker="RELIANCE.NS", name="Reliance", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()
    now = utcnow()
    _make_alert_company(db_session, company, direction="bearish", url_suffix="old", created_at=now - timedelta(days=1))
    _make_alert_company(db_session, company, direction="bullish", url_suffix="new", created_at=now)
    client = TestClient(app)

    body = client.get(f"/api/companies/{company.id}/profile").json()

    assert body["ticker"] == "RELIANCE.NS"
    assert body["latest_alert"]["direction"] == "bullish"
    assert body["latest_alert"]["article"]["title"] == "headline new"
    app.dependency_overrides.clear()


def test_get_company_profile_translates_article_title(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    company = Company(ticker="RELIANCE.NS", name="Reliance", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()
    ac = _make_alert_company(db_session, company, url_suffix="translated")
    db_session.add(ArticleTranslation(article_id=ac.alert.article_id, lang="hi", title="अनुवादित शीर्षक"))
    db_session.commit()
    client = TestClient(app)

    body = client.get(f"/api/companies/{company.id}/profile?lang=hi").json()

    assert body["latest_alert"]["article"]["title"] == "अनुवादित शीर्षक"
    app.dependency_overrides.clear()


def test_get_company_profile_latest_alert_null_when_never_mentioned(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    company = Company(ticker="RELIANCE.NS", name="Reliance", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()
    client = TestClient(app)

    body = client.get(f"/api/companies/{company.id}/profile").json()

    assert body["latest_alert"] is None
    app.dependency_overrides.clear()


def test_get_company_profile_track_record_null_below_threshold(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    company = Company(ticker="RELIANCE.NS", name="Reliance", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()
    client = TestClient(app)

    body = client.get(f"/api/companies/{company.id}/profile").json()

    assert body["track_record"] is None
    app.dependency_overrides.clear()


def test_get_company_profile_track_record_present_at_threshold(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    company = Company(ticker="RELIANCE.NS", name="Reliance", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()
    for i in range(5):
        ac = _make_alert_company(db_session, company, direction="bullish", url_suffix=f"s{i}")
        db_session.add(CalibrationSample(
            alert_company_id=ac.id, category="oil_energy", company_id=company.id,
            direction="bullish", magnitude_actual=2.0, horizon_days=1,
        ))
    db_session.commit()
    client = TestClient(app)

    body = client.get(f"/api/companies/{company.id}/profile").json()

    assert body["track_record"]["1"]["sample_size"] == 5
    assert body["track_record"]["1"]["win_rate"] == 1.0
    app.dependency_overrides.clear()


def test_get_company_history_404_for_global_company(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    company = Company(ticker="AAPL", name="Apple", sector="it", index_tier="GLOBAL_LARGE_CAP", market_cap=None)
    db_session.add(company)
    db_session.commit()
    client = TestClient(app)

    resp = client.get(f"/api/companies/{company.id}/history")

    assert resp.status_code == 404
    app.dependency_overrides.clear()


def test_get_company_history_paginates(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    company = Company(ticker="RELIANCE.NS", name="Reliance", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()
    now = utcnow()
    for i in range(3):
        _make_alert_company(db_session, company, url_suffix=f"h{i}", created_at=now - timedelta(days=i))
    client = TestClient(app)

    body = client.get(f"/api/companies/{company.id}/history?limit=2").json()

    assert len(body["mentions"]) == 2
    assert body["has_more"] is True
    app.dependency_overrides.clear()


def test_get_company_history_invalid_before_returns_400(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    company = Company(ticker="RELIANCE.NS", name="Reliance", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()
    client = TestClient(app)

    resp = client.get(f"/api/companies/{company.id}/history?before=not-a-date")

    assert resp.status_code == 400
    app.dependency_overrides.clear()


def test_get_company_prices_returns_points(db_session, monkeypatch):
    from app.routers import companies as companies_router

    app.dependency_overrides[get_db] = lambda: db_session
    company = Company(ticker="RELIANCE.NS", name="Reliance", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()
    monkeypatch.setattr(
        companies_router, "fetch_price_series",
        lambda ticker, period: [{"date": "2026-01-01", "close": 100.0}],
    )
    client = TestClient(app)

    body = client.get(f"/api/companies/{company.id}/prices?period=1mo").json()

    assert body == {"period": "1mo", "points": [{"date": "2026-01-01", "close": 100.0}], "available": True}
    app.dependency_overrides.clear()


def test_get_company_prices_degrades_to_empty_on_fetch_failure(db_session, monkeypatch):
    from app.routers import companies as companies_router

    app.dependency_overrides[get_db] = lambda: db_session
    company = Company(ticker="RELIANCE.NS", name="Reliance", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()
    monkeypatch.setattr(companies_router, "fetch_price_series", lambda ticker, period: None)
    client = TestClient(app)

    resp = client.get(f"/api/companies/{company.id}/prices?period=1mo")

    assert resp.status_code == 200
    assert resp.json() == {"period": "1mo", "points": [], "available": False}
    app.dependency_overrides.clear()


def test_get_company_prices_invalid_period_returns_400(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    company = Company(ticker="RELIANCE.NS", name="Reliance", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()
    client = TestClient(app)

    resp = client.get(f"/api/companies/{company.id}/prices?period=5y")

    assert resp.status_code == 400
    app.dependency_overrides.clear()


def test_get_company_prices_works_for_global_company(db_session, monkeypatch):
    from app.routers import companies as companies_router

    app.dependency_overrides[get_db] = lambda: db_session
    company = Company(ticker="AAPL", name="Apple", sector="it", index_tier="GLOBAL_LARGE_CAP", market_cap=None)
    db_session.add(company)
    db_session.commit()
    monkeypatch.setattr(
        companies_router, "fetch_price_series",
        lambda ticker, period: [{"date": "2026-01-01", "close": 200.0}],
    )
    client = TestClient(app)

    body = client.get(f"/api/companies/{company.id}/prices?period=1mo").json()

    assert body == {"period": "1mo", "points": [{"date": "2026-01-01", "close": 200.0}], "available": True}
    app.dependency_overrides.clear()


def test_get_company_live_price_unavailable_when_no_instrument_token(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    company = Company(ticker="RELIANCE.NS", name="Reliance", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()
    client = TestClient(app)

    body = client.get(f"/api/companies/{company.id}/live-price").json()

    assert body == {"ltp": None, "change_pct": None, "as_of": None, "available": False}
    app.dependency_overrides.clear()


def test_get_company_live_price_unavailable_when_no_tick_cached_yet(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    company = Company(
        ticker="RELIANCE.NS", name="Reliance", sector="oil_gas",
        index_tier="NIFTY50", market_cap=1.0, instrument_token=738561,
    )
    db_session.add(company)
    db_session.commit()
    client = TestClient(app)

    body = client.get(f"/api/companies/{company.id}/live-price").json()

    assert body == {"ltp": None, "change_pct": None, "as_of": None, "available": False}
    app.dependency_overrides.clear()


def test_get_company_live_price_returns_cached_tick_with_change_pct(db_session, monkeypatch):
    from datetime import datetime, timezone
    from app.prices.live_price import LIVE_PRICE_CACHE
    from app.routers import companies as companies_router

    app.dependency_overrides[get_db] = lambda: db_session
    company = Company(
        ticker="RELIANCE.NS", name="Reliance", sector="oil_gas",
        index_tier="NIFTY50", market_cap=1.0, instrument_token=738561,
    )
    db_session.add(company)
    db_session.commit()
    as_of = datetime(2026, 7, 15, 9, 30, tzinfo=timezone.utc)
    LIVE_PRICE_CACHE[738561] = {"ltp": 2530.0, "as_of": as_of}
    monkeypatch.setattr(
        companies_router, "fetch_price_series",
        lambda ticker, period: [{"date": "2026-07-14", "close": 2500.0}],
    )
    client = TestClient(app)

    body = client.get(f"/api/companies/{company.id}/live-price").json()

    assert body["ltp"] == 2530.0
    assert body["available"] is True
    assert body["as_of"] == as_of.isoformat()
    assert body["change_pct"] == pytest.approx(1.2)
    LIVE_PRICE_CACHE.clear()
    app.dependency_overrides.clear()


def test_get_company_live_price_404_for_global_company(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    company = Company(ticker="AAPL", name="Apple", sector="it", index_tier="GLOBAL_LARGE_CAP", market_cap=None)
    db_session.add(company)
    db_session.commit()
    client = TestClient(app)

    resp = client.get(f"/api/companies/{company.id}/live-price")

    assert resp.status_code == 404
    app.dependency_overrides.clear()


def test_get_company_live_price_response_is_never_cached(db_session):
    # This is a polling endpoint (frontend refetches it every few seconds) --
    # without an explicit no-store directive, browsers can silently serve a
    # stale cached response on repeat fetch() calls to the same URL, making
    # the live price look frozen until a hard page reload. Regression test
    # for that exact bug.
    app.dependency_overrides[get_db] = lambda: db_session
    company = Company(ticker="RELIANCE.NS", name="Reliance", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()
    client = TestClient(app)

    resp = client.get(f"/api/companies/{company.id}/live-price")

    assert resp.headers["cache-control"] == "no-store"
    app.dependency_overrides.clear()
