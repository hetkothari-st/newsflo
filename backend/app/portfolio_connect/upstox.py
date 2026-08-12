"""Upstox: standard OAuth2 authorization-code flow -> long-term holdings.
Register the app's redirect URI as settings.connect_redirect_url with
?broker=upstox appended so the callback identifies itself."""
import httpx

from app.config import settings
from app.portfolio_connect.base import BrokerHolding, Connector, ConnectorError, clean_symbol

AUTH_URL = "https://api.upstox.com/v2/login/authorization/dialog"
TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"
HOLDINGS_URL = "https://api.upstox.com/v2/portfolio/long-term-holdings"


class UpstoxConnector(Connector):
    slug = "upstox"
    flow = "redirect"

    def _redirect_uri(self) -> str:
        return f"{settings.connect_redirect_url}?broker=upstox"

    def configured(self) -> bool:
        return bool(settings.upstox_api_key and settings.upstox_api_secret)

    def login_url(self) -> str:
        return (
            f"{AUTH_URL}?response_type=code&client_id={settings.upstox_api_key}"
            f"&redirect_uri={self._redirect_uri()}"
        )

    def fetch(self, params: dict) -> list[BrokerHolding]:
        code = str(params.get("code") or "")
        if not code:
            raise ConnectorError("Upstox redirect did not carry an authorization code.")
        try:
            token_response = httpx.post(
                TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.upstox_api_key,
                    "client_secret": settings.upstox_api_secret,
                    "redirect_uri": self._redirect_uri(),
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
                timeout=20,
            )
            token_response.raise_for_status()
            access_token = token_response.json()["access_token"]
            holdings_response = httpx.get(
                HOLDINGS_URL,
                headers={"Accept": "application/json", "Authorization": f"Bearer {access_token}"},
                timeout=20,
            )
            holdings_response.raise_for_status()
            rows = holdings_response.json().get("data", [])
        except httpx.HTTPError as exc:
            raise ConnectorError(f"Upstox exchange failed: {exc}") from exc
        return [
            BrokerHolding(
                isin=(row.get("isin") or "").strip().upper(),
                symbol=clean_symbol(row.get("trading_symbol") or row.get("tradingsymbol")),
                quantity=float(row.get("quantity") or 0),
            )
            for row in rows
        ]
