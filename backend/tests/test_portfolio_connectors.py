"""Connector-registry tests: symbol normalization, per-broker payload
normalization (httpx mocked -- no network), and the generic provider
import endpoint end to end."""
import io

from fastapi.testclient import TestClient

from app.main import app
from app.models import Company
from app.portfolio_connect.base import clean_symbol
from app.routers.articles import get_db


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _client_and_token(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    resp = client.post("/api/auth/register", json={"email": "conn@example.com", "password": "pw12345"})
    return client, resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _seed(db_session):
    company = Company(
        ticker="RELIANCE.NS", name="Reliance", sector="oil_gas", index_tier="NIFTY50",
        market_cap=1.0, isin="INE002A01018",
    )
    db_session.add(company)
    db_session.commit()
    return company


def test_clean_symbol_strips_broker_dialects():
    assert clean_symbol("NSE:RELIANCE-EQ") == "RELIANCE"
    assert clean_symbol("RELIANCE-EQ") == "RELIANCE"
    assert clean_symbol("reliance") == "RELIANCE"
    assert clean_symbol(None) == ""


def test_upstox_import_end_to_end(db_session, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "upstox_api_key", "k")
    monkeypatch.setattr(settings, "upstox_api_secret", "s")
    monkeypatch.setattr(
        "app.portfolio_connect.upstox.httpx.post",
        lambda *a, **kw: _Resp({"access_token": "tok"}),
    )
    monkeypatch.setattr(
        "app.portfolio_connect.upstox.httpx.get",
        lambda *a, **kw: _Resp({"data": [
            {"isin": "INE002A01018", "trading_symbol": "RELIANCE", "quantity": 4},
        ]}),
    )
    client, token = _client_and_token(db_session)
    _seed(db_session)

    response = client.post(
        "/api/portfolio/connect/upstox/import",
        json={"params": {"code": "abc", "broker": "upstox"}},
        headers=_auth(token),
    )

    assert response.status_code == 200
    assert response.json()["imported"] == [
        {"ticker": "RELIANCE.NS", "name": "Reliance", "quantity": 4.0}
    ]
    app.dependency_overrides.clear()


def test_fyers_import_normalizes_prefixed_symbols(db_session, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "fyers_app_id", "APP-100")
    monkeypatch.setattr(settings, "fyers_app_secret", "s")
    monkeypatch.setattr(
        "app.portfolio_connect.fyers.httpx.post",
        lambda *a, **kw: _Resp({"access_token": "tok"}),
    )
    monkeypatch.setattr(
        "app.portfolio_connect.fyers.httpx.get",
        lambda *a, **kw: _Resp({"holdings": [
            {"isin": "", "symbol": "NSE:RELIANCE-EQ", "quantity": 2},
        ]}),
    )
    client, token = _client_and_token(db_session)
    _seed(db_session)

    response = client.post(
        "/api/portfolio/connect/fyers/import",
        json={"params": {"auth_code": "ac"}},
        headers=_auth(token),
    )

    assert response.json()["imported"][0]["ticker"] == "RELIANCE.NS"
    app.dependency_overrides.clear()


def test_angelone_import_uses_auth_token_directly(db_session, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "angelone_api_key", "k")
    monkeypatch.setattr(
        "app.portfolio_connect.angelone.httpx.get",
        lambda *a, **kw: _Resp({"data": {"holdings": [
            {"isin": "INE002A01018", "tradingsymbol": "RELIANCE-EQ", "quantity": 6},
        ]}}),
    )
    client, token = _client_and_token(db_session)
    _seed(db_session)

    response = client.post(
        "/api/portfolio/connect/angelone/import",
        json={"params": {"auth_token": "jwt"}},
        headers=_auth(token),
    )

    assert response.json()["imported"][0]["quantity"] == 6.0
    app.dependency_overrides.clear()


def test_dhan_token_paste_import(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.portfolio_connect.dhan.httpx.get",
        lambda *a, **kw: _Resp([
            {"isin": "INE002A01018", "tradingSymbol": "RELIANCE", "totalQty": 9},
        ]),
    )
    client, token = _client_and_token(db_session)
    _seed(db_session)

    response = client.post(
        "/api/portfolio/connect/dhan/import",
        json={"params": {"access_token": "pasted"}},
        headers=_auth(token),
    )

    assert response.json()["imported"][0]["quantity"] == 9.0
    app.dependency_overrides.clear()


def test_dhan_missing_token_is_a_clean_502(db_session):
    client, token = _client_and_token(db_session)

    response = client.post(
        "/api/portfolio/connect/dhan/import",
        json={"params": {}},
        headers=_auth(token),
    )

    assert response.status_code == 502
    assert "access token" in response.json()["detail"].lower()
    app.dependency_overrides.clear()


def test_unconfigured_provider_503s_and_unknown_404s(db_session):
    client, token = _client_and_token(db_session)

    assert client.get("/api/portfolio/connect/upstox/login-url", headers=_auth(token)).status_code == 503
    assert client.get("/api/portfolio/connect/nope/login-url", headers=_auth(token)).status_code == 404
    app.dependency_overrides.clear()


def test_kite_alias_paths_still_work(db_session, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "kite_api_key", "k")
    monkeypatch.setattr(settings, "kite_api_secret", "s")
    client, token = _client_and_token(db_session)

    response = client.get("/api/portfolio/connect/kite/login-url", headers=_auth(token))

    assert response.status_code == 200
    assert "kite.zerodha.com" in response.json()["url"]
    app.dependency_overrides.clear()
