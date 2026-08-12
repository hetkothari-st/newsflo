from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BrokerHolding:
    """One normalized holdings row from any broker. Symbol is the bare
    exchange symbol (no -EQ suffix, no NSE:/BSE: prefix); ISIN may be
    empty when the broker omits it."""
    isin: str
    symbol: str
    quantity: float


def clean_symbol(raw: str | None) -> str:
    """'NSE:RELIANCE-EQ' -> 'RELIANCE'. Broker symbol dialects differ in
    prefix/suffix decoration only; company matching wants the bare NSE/BSE
    symbol."""
    symbol = (raw or "").strip().upper()
    if ":" in symbol:
        symbol = symbol.split(":", 1)[1]
    for suffix in ("-EQ", "-BE", "-BZ"):
        if symbol.endswith(suffix):
            symbol = symbol[: -len(suffix)]
    return symbol


class Connector:
    """Contract every broker connector implements. `fetch` receives the
    redirect/callback params the client observed (or a pasted token) and
    returns normalized rows -- each connector owns its own token
    exchange. Raise ConnectorError with a user-readable message on any
    broker-side failure."""

    slug: str = ""
    # 'redirect' = user is sent to the broker and bounced back with
    # params; 'token' = user pastes a token they generated broker-side.
    flow: str = "redirect"

    def configured(self) -> bool:
        raise NotImplementedError

    def login_url(self) -> str:
        raise NotImplementedError

    def fetch(self, params: dict) -> list[BrokerHolding]:
        raise NotImplementedError


class ConnectorError(Exception):
    """User-facing broker failure ('token exchange failed', ...)."""
