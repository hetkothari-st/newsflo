"""Dhan: the retail API issues a long-lived access token from the user's
own Dhan web console (My Profile -> DhanHQ Trading APIs) -- token-paste
by design, no app keys, so this connector is always available."""
import httpx

from app.config import settings  # noqa: F401  (parity with siblings; no keys needed)
from app.portfolio_connect.base import BrokerHolding, Connector, ConnectorError, clean_symbol

HOLDINGS_URL = "https://api.dhan.co/v2/holdings"


class DhanConnector(Connector):
    slug = "dhan"
    flow = "token"

    def configured(self) -> bool:
        return True

    def login_url(self) -> str:
        raise ConnectorError("Dhan uses a pasted access token, not a login redirect.")

    def fetch(self, params: dict) -> list[BrokerHolding]:
        access_token = str(params.get("access_token") or "").strip()
        if not access_token:
            raise ConnectorError("Paste the access token generated in Dhan's web console.")
        try:
            holdings_response = httpx.get(
                HOLDINGS_URL,
                headers={"access-token": access_token, "Accept": "application/json"},
                timeout=20,
            )
            holdings_response.raise_for_status()
            rows = holdings_response.json()
        except httpx.HTTPError as exc:
            raise ConnectorError(f"Dhan holdings fetch failed: {exc}") from exc
        if not isinstance(rows, list):
            rows = []
        return [
            BrokerHolding(
                isin=(row.get("isin") or "").strip().upper(),
                symbol=clean_symbol(row.get("tradingSymbol")),
                quantity=float(row.get("totalQty") or row.get("availableQty") or 0),
            )
            for row in rows
        ]
