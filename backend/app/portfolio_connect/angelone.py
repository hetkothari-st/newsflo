"""Angel One SmartAPI publisher-login flow: the redirect returns
auth_token (a JWT usable directly as the session) -- no exchange step.
Holdings via the getAllHolding endpoint."""
import httpx

from app.config import settings
from app.portfolio_connect.base import BrokerHolding, Connector, ConnectorError, clean_symbol

LOGIN_URL = "https://smartapi.angelbroking.com/publisher-login"
HOLDINGS_URL = (
    "https://apiconnect.angelbroking.com/rest/secure/angelbroking/portfolio/v1/getAllHolding"
)


class AngelOneConnector(Connector):
    slug = "angelone"
    flow = "redirect"

    def configured(self) -> bool:
        return bool(settings.angelone_api_key)

    def login_url(self) -> str:
        return f"{LOGIN_URL}?api_key={settings.angelone_api_key}"

    def fetch(self, params: dict) -> list[BrokerHolding]:
        auth_token = str(params.get("auth_token") or "")
        if not auth_token:
            raise ConnectorError("Angel One redirect did not carry an auth_token.")
        try:
            holdings_response = httpx.get(
                HOLDINGS_URL,
                headers={
                    "Authorization": f"Bearer {auth_token}",
                    "X-PrivateKey": settings.angelone_api_key,
                    "X-SourceID": "WEB",
                    "X-UserType": "USER",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=20,
            )
            holdings_response.raise_for_status()
            payload = holdings_response.json()
            rows = (payload.get("data") or {}).get("holdings", []) or []
        except httpx.HTTPError as exc:
            raise ConnectorError(f"Angel One holdings fetch failed: {exc}") from exc
        return [
            BrokerHolding(
                isin=(row.get("isin") or "").strip().upper(),
                symbol=clean_symbol(row.get("tradingsymbol")),
                quantity=float(row.get("quantity") or 0),
            )
            for row in rows
        ]
