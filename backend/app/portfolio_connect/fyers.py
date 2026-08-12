"""Fyers API v3: auth-code redirect -> appIdHash-validated token
exchange -> holdings."""
import hashlib

import httpx

from app.config import settings
from app.portfolio_connect.base import BrokerHolding, Connector, ConnectorError, clean_symbol

AUTH_URL = "https://api-t1.fyers.in/api/v3/generate-authcode"
TOKEN_URL = "https://api-t1.fyers.in/api/v3/validate-authcode"
HOLDINGS_URL = "https://api-t1.fyers.in/api/v3/holdings"


class FyersConnector(Connector):
    slug = "fyers"
    flow = "redirect"

    def configured(self) -> bool:
        return bool(settings.fyers_app_id and settings.fyers_app_secret)

    def login_url(self) -> str:
        redirect = f"{settings.connect_redirect_url}?broker=fyers"
        return (
            f"{AUTH_URL}?client_id={settings.fyers_app_id}&redirect_uri={redirect}"
            f"&response_type=code&state=newsflo"
        )

    def fetch(self, params: dict) -> list[BrokerHolding]:
        auth_code = str(params.get("auth_code") or params.get("code") or "")
        if not auth_code:
            raise ConnectorError("Fyers redirect did not carry an auth code.")
        app_id_hash = hashlib.sha256(
            f"{settings.fyers_app_id}:{settings.fyers_app_secret}".encode()
        ).hexdigest()
        try:
            token_response = httpx.post(
                TOKEN_URL,
                json={"grant_type": "authorization_code", "appIdHash": app_id_hash, "code": auth_code},
                timeout=20,
            )
            token_response.raise_for_status()
            access_token = token_response.json()["access_token"]
            holdings_response = httpx.get(
                HOLDINGS_URL,
                headers={"Authorization": f"{settings.fyers_app_id}:{access_token}"},
                timeout=20,
            )
            holdings_response.raise_for_status()
            rows = holdings_response.json().get("holdings", [])
        except httpx.HTTPError as exc:
            raise ConnectorError(f"Fyers exchange failed: {exc}") from exc
        return [
            BrokerHolding(
                isin=(row.get("isin") or "").strip().upper(),
                symbol=clean_symbol(row.get("symbol")),
                quantity=float(row.get("quantity") or 0),
            )
            for row in rows
        ]
