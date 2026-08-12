"""ICICI Direct Breeze: the user logs in at the Breeze portal with the
app's key and is bounced back with an API_Session token; that plus a
per-request SHA-256 checksum (timestamp + payload + secret) signs the
customerdetails call, whose session_token then reads demat holdings."""
import hashlib
import json
from datetime import datetime, timezone

import httpx

from app.config import settings
from app.portfolio_connect.base import BrokerHolding, Connector, ConnectorError, clean_symbol

LOGIN_URL = "https://api.icicidirect.com/apiuser/login"
CUSTOMER_URL = "https://api.icicidirect.com/breezeapi/api/v1/customerdetails"
HOLDINGS_URL = "https://api.icicidirect.com/breezeapi/api/v1/dematholdings"


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class BreezeConnector(Connector):
    slug = "icicidirect"
    flow = "redirect"

    def configured(self) -> bool:
        return bool(settings.breeze_api_key and settings.breeze_api_secret)

    def login_url(self) -> str:
        return f"{LOGIN_URL}?api_key={settings.breeze_api_key}"

    def fetch(self, params: dict) -> list[BrokerHolding]:
        api_session = str(params.get("apisession") or params.get("API_Session") or "")
        if not api_session:
            raise ConnectorError("ICICI Direct redirect did not carry an API session token.")
        try:
            customer_response = httpx.get(
                CUSTOMER_URL,
                json={"SessionToken": api_session, "AppKey": settings.breeze_api_key},
                timeout=20,
            )
            customer_response.raise_for_status()
            session_token = (customer_response.json().get("Success") or {}).get("session_token")
            if not session_token:
                raise ConnectorError("ICICI Direct did not issue a session token.")
            timestamp = _timestamp()
            payload = "{}"
            checksum = hashlib.sha256(
                (timestamp + payload + settings.breeze_api_secret).encode()
            ).hexdigest()
            holdings_response = httpx.get(
                HOLDINGS_URL,
                headers={
                    "Content-Type": "application/json",
                    "X-Checksum": f"token {checksum}",
                    "X-Timestamp": timestamp,
                    "X-AppKey": settings.breeze_api_key,
                    "X-SessionToken": session_token,
                },
                json=json.loads(payload),
                timeout=20,
            )
            holdings_response.raise_for_status()
            rows = holdings_response.json().get("Success") or []
        except httpx.HTTPError as exc:
            raise ConnectorError(f"ICICI Direct exchange failed: {exc}") from exc
        return [
            BrokerHolding(
                isin=(row.get("isin") or "").strip().upper(),
                symbol=clean_symbol(row.get("stock_code")),
                quantity=float(row.get("quantity") or 0),
            )
            for row in rows
        ]
