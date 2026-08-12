"""Zerodha Kite Connect: request_token redirect -> SHA-256 checksummed
session exchange -> one-shot holdings pull. The access token is used for
the single import and discarded."""
import hashlib

import httpx

from app.config import settings
from app.portfolio_connect.base import BrokerHolding, Connector, ConnectorError, clean_symbol

SESSION_URL = "https://api.kite.trade/session/token"
HOLDINGS_URL = "https://api.kite.trade/portfolio/holdings"


class KiteConnector(Connector):
    slug = "zerodha"
    flow = "redirect"

    def configured(self) -> bool:
        return bool(settings.kite_api_key and settings.kite_api_secret)

    def login_url(self) -> str:
        return f"https://kite.zerodha.com/connect/login?v=3&api_key={settings.kite_api_key}"

    def fetch(self, params: dict) -> list[BrokerHolding]:
        request_token = str(params.get("request_token") or "")
        if not request_token:
            raise ConnectorError("Zerodha redirect did not carry a request_token.")
        checksum = hashlib.sha256(
            f"{settings.kite_api_key}{request_token}{settings.kite_api_secret}".encode()
        ).hexdigest()
        try:
            session_response = httpx.post(
                SESSION_URL,
                data={
                    "api_key": settings.kite_api_key,
                    "request_token": request_token,
                    "checksum": checksum,
                },
                headers={"X-Kite-Version": "3"},
                timeout=20,
            )
            session_response.raise_for_status()
            access_token = session_response.json()["data"]["access_token"]
            holdings_response = httpx.get(
                HOLDINGS_URL,
                headers={
                    "X-Kite-Version": "3",
                    "Authorization": f"token {settings.kite_api_key}:{access_token}",
                },
                timeout=20,
            )
            holdings_response.raise_for_status()
            rows = holdings_response.json().get("data", [])
        except httpx.HTTPError as exc:
            raise ConnectorError(f"Zerodha exchange failed: {exc}") from exc
        return [
            BrokerHolding(
                isin=(row.get("isin") or "").strip().upper(),
                symbol=clean_symbol(row.get("tradingsymbol")),
                quantity=float(row.get("quantity") or 0),
            )
            for row in rows
        ]
