import io

from fastapi.testclient import TestClient

from app.main import app
from app.models import Company, Holding
from app.routers.articles import get_db


def _client_and_token(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    resp = client.post("/api/auth/register", json={"email": "imp@example.com", "password": "pw12345"})
    return client, resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _seed(db_session, ticker="RELIANCE.NS", isin="INE002A01018", name="Reliance"):
    company = Company(
        ticker=ticker, name=name, sector="oil_gas", index_tier="NIFTY50",
        market_cap=1.0, isin=isin,
    )
    db_session.add(company)
    db_session.commit()
    return company


def _upload(client, token, text, filename="holdings.csv"):
    return client.post(
        "/api/holdings/import",
        files={"file": (filename, io.BytesIO(text.encode()), "text/csv")},
        headers=_auth(token),
    )


def test_import_zerodha_console_shape(db_session):
    """Zerodha console export: Symbol/ISIN/Quantity Available headers,
    matched by ISIN even when the symbol column is bare."""
    client, token = _client_and_token(db_session)
    _seed(db_session)
    csv_text = (
        "Symbol,ISIN,Sector,Quantity Available,Quantity Pledged,Average Price\n"
        "RELIANCE,INE002A01018,Energy,10,0,2400.5\n"
    )

    response = _upload(client, token, csv_text)

    assert response.status_code == 200
    body = response.json()
    assert body["imported"] == [{"ticker": "RELIANCE.NS", "name": "Reliance", "quantity": 10.0}]
    assert body["skipped"] == []
    app.dependency_overrides.clear()


def test_import_symbol_only_file_matches_ticker_variants(db_session):
    client, token = _client_and_token(db_session)
    _seed(db_session, ticker="TCS.NS", isin="INE467B01029", name="TCS")
    csv_text = "Stock Name,Qty\nTCS,7\n"

    response = _upload(client, token, csv_text)

    assert response.status_code == 200
    assert response.json()["imported"][0]["ticker"] == "TCS.NS"
    app.dependency_overrides.clear()


def test_import_skips_preamble_rows_and_reports_unknown(db_session):
    """Broker files often carry account preamble above the header; unknown
    rows are reported, never silently dropped."""
    client, token = _client_and_token(db_session)
    _seed(db_session)
    csv_text = (
        "Client ID:,AB1234\n"
        "Holdings as of:,2026-08-12\n"
        "Symbol,ISIN,Quantity\n"
        "RELIANCE,INE002A01018,4\n"
        "MYSTERY,INE000X00000,9\n"
    )

    response = _upload(client, token, csv_text)

    body = response.json()
    assert [row["ticker"] for row in body["imported"]] == ["RELIANCE.NS"]
    assert body["skipped"] == [{"row": "MYSTERY", "reason": "no matching company (ISIN/symbol unknown)"}]
    app.dependency_overrides.clear()


def test_import_no_header_reports_cleanly(db_session):
    client, token = _client_and_token(db_session)

    response = _upload(client, token, "just,some,cells\n1,2,3\n")

    body = response.json()
    assert body["imported"] == []
    assert "no recognizable header" in body["skipped"][0]["reason"]
    app.dependency_overrides.clear()


def test_import_upserts_existing_holding(db_session):
    client, token = _client_and_token(db_session)
    _seed(db_session)
    client.post("/api/holdings", json={"ticker": "RELIANCE.NS", "quantity": 2}, headers=_auth(token))

    _upload(client, token, "Symbol,ISIN,Quantity\nRELIANCE,INE002A01018,11\n")

    holdings = client.get("/api/holdings", headers=_auth(token)).json()
    assert holdings == [
        {"company_id": holdings[0]["company_id"], "ticker": "RELIANCE.NS", "name": "Reliance", "quantity": 11.0}
    ]
    app.dependency_overrides.clear()


def test_delete_holding(db_session):
    client, token = _client_and_token(db_session)
    _seed(db_session)
    client.post("/api/holdings", json={"ticker": "RELIANCE.NS", "quantity": 2}, headers=_auth(token))

    response = client.delete("/api/holdings/RELIANCE.NS", headers=_auth(token))

    assert response.status_code == 204
    assert client.get("/api/holdings", headers=_auth(token)).json() == []
    assert db_session.query(Holding).count() == 0
    app.dependency_overrides.clear()


def test_delete_holding_404s(db_session):
    client, token = _client_and_token(db_session)
    _seed(db_session)

    assert client.delete("/api/holdings/NOPE.NS", headers=_auth(token)).status_code == 404
    assert client.delete("/api/holdings/RELIANCE.NS", headers=_auth(token)).status_code == 404
    app.dependency_overrides.clear()


def test_connect_status_reports_unconfigured(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    body = client.get("/api/portfolio/connect/status").json()

    assert body == {"kite_configured": False}
    app.dependency_overrides.clear()


def test_kite_login_url_503_when_unconfigured(db_session):
    client, token = _client_and_token(db_session)

    response = client.get("/api/portfolio/connect/kite/login-url", headers=_auth(token))

    assert response.status_code == 503
    app.dependency_overrides.clear()


def test_kite_import_exchanges_and_upserts(db_session, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "kite_api_key", "k")
    monkeypatch.setattr(settings, "kite_api_secret", "s")
    client, token = _client_and_token(db_session)
    _seed(db_session)

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    monkeypatch.setattr(
        "app.routers.portfolio_connect.httpx.post",
        lambda *a, **kw: _Resp({"data": {"access_token": "tok"}}),
    )
    monkeypatch.setattr(
        "app.routers.portfolio_connect.httpx.get",
        lambda *a, **kw: _Resp({"data": [
            {"tradingsymbol": "RELIANCE", "isin": "INE002A01018", "quantity": 3},
            {"tradingsymbol": "GHOST", "isin": "INE000Z00000", "quantity": 5},
        ]}),
    )

    response = client.post(
        "/api/portfolio/connect/kite/import",
        json={"request_token": "rt"},
        headers=_auth(token),
    )

    body = response.json()
    assert body["imported"] == [{"ticker": "RELIANCE.NS", "name": "Reliance", "quantity": 3.0}]
    assert body["skipped"] == [{"row": "GHOST", "reason": "no matching company"}]
    app.dependency_overrides.clear()
