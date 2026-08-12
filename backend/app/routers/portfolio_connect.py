"""Broker connect flows for the Portfolio section.

Connectors live in app.portfolio_connect -- one module per broker, all
key-gated (empty settings = that broker falls back to CSV import). This
router is broker-agnostic: status map, per-provider login URL, and a
per-provider import that receives whatever callback params (or pasted
token) the client observed, exchanges them connector-side, matches
holdings to Companies (ISIN first), and upserts. No broker token is
ever stored -- each import is a one-shot pull.

The /kite/* paths predate the registry and stay as aliases; they are
registered BEFORE the /{provider}/ routes because Starlette matches in
registration order, and 'kite' also aliases to the 'zerodha' slug.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.holdings.import_parse import _match_company
from app.models import User
from app.portfolio_connect import CONNECTORS
from app.portfolio_connect.base import ConnectorError
from app.routers.articles import get_db
from app.routers.holdings import _upsert_holding

router = APIRouter(prefix="/api/portfolio/connect", tags=["portfolio-connect"])

_SLUG_ALIASES = {"kite": "zerodha"}


@router.get("/status")
def connect_status():
    providers = {slug: connector.configured() for slug, connector in CONNECTORS.items()}
    flows = {slug: connector.flow for slug, connector in CONNECTORS.items()}
    return {
        "providers": providers,
        "flows": flows,
        # Back-compat key (pre-registry clients).
        "kite_configured": providers["zerodha"],
    }


def _connector(provider: str):
    slug = _SLUG_ALIASES.get(provider, provider)
    connector = CONNECTORS.get(slug)
    if connector is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider {provider!r}")
    if not connector.configured():
        raise HTTPException(
            status_code=503,
            detail=f"{provider} live connect is not configured on this server. Use the CSV import instead.",
        )
    return connector


class ProviderImportRequest(BaseModel):
    params: dict


def _run_import(provider: str, params: dict, db: Session, user: User) -> dict:
    connector = _connector(provider)
    try:
        broker_rows = connector.fetch(params)
    except ConnectorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    imported: list[dict] = []
    skipped: list[dict] = []
    for row in broker_rows:
        label = row.symbol or row.isin
        if row.quantity <= 0:
            skipped.append({"row": label, "reason": "zero quantity"})
            continue
        company = _match_company(db, row.isin, row.symbol)
        if company is None:
            skipped.append({"row": label, "reason": "no matching company"})
            continue
        _upsert_holding(db, user.id, company.id, row.quantity)
        imported.append({"ticker": company.ticker, "name": company.name, "quantity": row.quantity})
    return {"imported": imported, "skipped": skipped}


# ---- Pre-registry /kite aliases: MUST precede the /{provider} routes ----


class KiteImportRequest(BaseModel):
    request_token: str


@router.get("/kite/login-url")
def kite_login_url(current_user: User = Depends(get_current_user)):
    return {"url": _connector("zerodha").login_url()}


@router.post("/kite/import")
def kite_import(
    payload: KiteImportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _run_import("zerodha", {"request_token": payload.request_token}, db, current_user)


# ---- Generic provider routes ----


@router.get("/{provider}/login-url")
def provider_login_url(provider: str, current_user: User = Depends(get_current_user)):
    connector = _connector(provider)
    try:
        return {"url": connector.login_url()}
    except ConnectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{provider}/import")
def provider_import(
    provider: str,
    payload: ProviderImportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _run_import(provider, payload.params, db, current_user)
