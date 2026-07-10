from fastapi.testclient import TestClient

from app.main import app
from app.models import Company
from app.routers.articles import get_db


def _client_and_token(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    resp = client.post("/api/auth/register", json={"email": "wl@example.com", "password": "pw12345"})
    return client, resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _seed_company(db_session, ticker, name):
    company = Company(ticker=ticker, name=name, sector="it", index_tier="GLOBAL_LARGE_CAP", market_cap=None)
    db_session.add(company)
    db_session.commit()
    return company


def test_get_watchlist_empty_by_default(db_session):
    client, token = _client_and_token(db_session)

    body = client.get("/api/watchlist", headers=_auth(token)).json()

    assert body == {"categories": [], "companies": []}
    app.dependency_overrides.clear()


def test_put_then_get_reflects_saved_selection(db_session):
    client, token = _client_and_token(db_session)
    company = _seed_company(db_session, "AAPL", "Apple")

    put = client.put(
        "/api/watchlist",
        json={"categories": ["oil_energy"], "company_ids": [company.id]},
        headers=_auth(token),
    )
    assert put.status_code == 200
    assert put.json()["categories"] == ["oil_energy"]
    assert put.json()["companies"] == [{"company_id": company.id, "ticker": "AAPL", "name": "Apple"}]

    get = client.get("/api/watchlist", headers=_auth(token)).json()
    assert get["categories"] == ["oil_energy"]
    assert [c["company_id"] for c in get["companies"]] == [company.id]

    app.dependency_overrides.clear()


def test_put_replaces_previous_selection(db_session):
    client, token = _client_and_token(db_session)
    apple = _seed_company(db_session, "AAPL", "Apple")
    msft = _seed_company(db_session, "MSFT", "Microsoft")

    client.put(
        "/api/watchlist",
        json={"categories": ["oil_energy"], "company_ids": [apple.id]},
        headers=_auth(token),
    )
    # Second PUT with a DIFFERENT set must fully replace the first.
    client.put(
        "/api/watchlist",
        json={"categories": ["banking"], "company_ids": [msft.id]},
        headers=_auth(token),
    )

    get = client.get("/api/watchlist", headers=_auth(token)).json()
    assert get["categories"] == ["banking"]
    assert [c["company_id"] for c in get["companies"]] == [msft.id]

    app.dependency_overrides.clear()


def test_watchlist_requires_auth(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    assert client.get("/api/watchlist").status_code in (401, 403)
    assert client.put("/api/watchlist", json={"categories": [], "company_ids": []}).status_code in (401, 403)

    app.dependency_overrides.clear()
