from fastapi.testclient import TestClient

from app.main import app
from app.models import Company
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
