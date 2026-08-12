"""Broker connect flows for the Portfolio section.

Zerodha Kite Connect is the one Indian broker with a first-class OAuth
flow here; it activates only when KITE_API_KEY/KITE_API_SECRET are set
(empty-means-off, same convention as brandfetch_client_id). Every other
broker connects through the provider-agnostic CSV import
(/api/holdings/import) -- most Indian brokers expose no public account
API at all, so the console-export path is the honest universal one.

Kite flow: the client opens login-url in a popup/tab; Zerodha redirects
back to the app with ?request_token=...; the client posts that token
here; we exchange it (SHA-256 checksum of key+token+secret) for an
access_token and pull /portfolio/holdings once. Nothing broker-side is
stored -- the access token is used for the single import and discarded.
"""
import hashlib

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.config import settings
from app.models import User
from app.routers.articles import get_db
from app.routers.holdings import _upsert_holding
from app.holdings.import_parse import _match_company

router = APIRouter(prefix="/api/portfolio/connect", tags=["portfolio-connect"])

KITE_SESSION_URL = "https://api.kite.trade/session/token"
KITE_HOLDINGS_URL = "https://api.kite.trade/portfolio/holdings"


@router.get("/status")
def connect_status():
    return {"kite_configured": bool(settings.kite_api_key and settings.kite_api_secret)}


def _require_kite() -> None:
    if not (settings.kite_api_key and settings.kite_api_secret):
        raise HTTPException(
            status_code=503,
            detail="Zerodha live connect is not configured on this server (KITE_API_KEY/KITE_API_SECRET unset). Use the CSV import instead.",
        )


@router.get("/kite/login-url")
def kite_login_url(current_user: User = Depends(get_current_user)):
    _require_kite()
    return {"url": f"https://kite.zerodha.com/connect/login?v=3&api_key={settings.kite_api_key}"}


class KiteImportRequest(BaseModel):
    request_token: str


@router.post("/kite/import")
def kite_import(
    payload: KiteImportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_kite()
    checksum = hashlib.sha256(
        f"{settings.kite_api_key}{payload.request_token}{settings.kite_api_secret}".encode()
    ).hexdigest()
    try:
        session_response = httpx.post(
            KITE_SESSION_URL,
            data={
                "api_key": settings.kite_api_key,
                "request_token": payload.request_token,
                "checksum": checksum,
            },
            headers={"X-Kite-Version": "3"},
            timeout=20,
        )
        session_response.raise_for_status()
        access_token = session_response.json()["data"]["access_token"]
        holdings_response = httpx.get(
            KITE_HOLDINGS_URL,
            headers={
                "X-Kite-Version": "3",
                "Authorization": f"token {settings.kite_api_key}:{access_token}",
            },
            timeout=20,
        )
        holdings_response.raise_for_status()
        broker_rows = holdings_response.json().get("data", [])
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Zerodha exchange failed: {exc}") from exc

    imported: list[dict] = []
    skipped: list[dict] = []
    for row in broker_rows:
        isin = (row.get("isin") or "").strip().upper()
        symbol = (row.get("tradingsymbol") or "").strip().upper()
        quantity = float(row.get("quantity") or 0)
        if quantity <= 0:
            skipped.append({"row": symbol or isin, "reason": "zero quantity"})
            continue
        company = _match_company(db, isin, symbol)
        if company is None:
            skipped.append({"row": symbol or isin, "reason": "no matching company"})
            continue
        _upsert_holding(db, current_user.id, company.id, quantity)
        imported.append({"ticker": company.ticker, "name": company.name, "quantity": quantity})
    return {"imported": imported, "skipped": skipped}
