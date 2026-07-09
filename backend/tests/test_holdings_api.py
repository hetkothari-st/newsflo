from fastapi.testclient import TestClient

from app.main import app
from app.models import Company
from app.routers.articles import get_db


def _client_and_token(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    resp = client.post("/api/auth/register", json={"email": "hold@example.com", "password": "pw12345"})
    return client, resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _seed_company(db_session, ticker="RELIANCE.NS"):
    company = Company(ticker=ticker, name="Reliance", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()
    return company


def test_add_holding_requires_auth(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    response = client.post("/api/holdings", json={"ticker": "RELIANCE.NS", "quantity": 5})

    assert response.status_code in (401, 403)  # no bearer token -> rejected
    app.dependency_overrides.clear()


def test_add_holding_manual_entry(db_session):
    client, token = _client_and_token(db_session)
    _seed_company(db_session)

    response = client.post("/api/holdings", json={"ticker": "RELIANCE.NS", "quantity": 12}, headers=_auth(token))

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "RELIANCE.NS"
    assert body["quantity"] == 12.0

    app.dependency_overrides.clear()


def test_add_holding_unknown_ticker_404(db_session):
    client, token = _client_and_token(db_session)

    response = client.post("/api/holdings", json={"ticker": "NOPE.NS", "quantity": 1}, headers=_auth(token))

    assert response.status_code == 404
    app.dependency_overrides.clear()


def test_add_holding_upserts(db_session):
    client, token = _client_and_token(db_session)
    _seed_company(db_session)
    client.post("/api/holdings", json={"ticker": "RELIANCE.NS", "quantity": 5}, headers=_auth(token))
    client.post("/api/holdings", json={"ticker": "RELIANCE.NS", "quantity": 8}, headers=_auth(token))

    listed = client.get("/api/holdings", headers=_auth(token)).json()

    assert len(listed) == 1
    assert listed[0]["quantity"] == 8.0

    app.dependency_overrides.clear()


def test_upload_holdings_csv(db_session):
    client, token = _client_and_token(db_session)
    _seed_company(db_session)
    _seed_company(db_session, ticker="TCS.NS")

    csv_content = b"Ticker,Quantity\nRELIANCE.NS,10\nTCS.NS,4\n"
    response = client.post(
        "/api/holdings/csv",
        files={"file": ("holdings.csv", csv_content, "text/csv")},
        headers=_auth(token),
    )

    assert response.status_code == 200
    assert response.json()["loaded"] == 2

    app.dependency_overrides.clear()


def test_list_holdings_returns_company_info(db_session):
    client, token = _client_and_token(db_session)
    _seed_company(db_session)
    client.post("/api/holdings", json={"ticker": "RELIANCE.NS", "quantity": 3}, headers=_auth(token))

    response = client.get("/api/holdings", headers=_auth(token))

    assert response.status_code == 200
    body = response.json()
    assert body[0]["ticker"] == "RELIANCE.NS"
    assert body[0]["name"] == "Reliance"
    assert body[0]["quantity"] == 3.0

    app.dependency_overrides.clear()
