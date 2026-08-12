"""Broker connector registry for live portfolio import.

Each connector implements the same tiny contract (configured / login_url
/ fetch) and normalizes broker payloads to BrokerHolding rows; the
router matches those to Companies and upserts holdings. Every connector
is key-gated by env settings (empty means off -- the UI then falls back
to the provider-agnostic CSV import), except Dhan, whose retail API is
token-paste by design and needs no app keys.
"""
from app.portfolio_connect.base import BrokerHolding, Connector
from app.portfolio_connect.angelone import AngelOneConnector
from app.portfolio_connect.breeze import BreezeConnector
from app.portfolio_connect.dhan import DhanConnector
from app.portfolio_connect.fyers import FyersConnector
from app.portfolio_connect.kite import KiteConnector
from app.portfolio_connect.upstox import UpstoxConnector

CONNECTORS: dict[str, Connector] = {
    connector.slug: connector
    for connector in (
        KiteConnector(),
        UpstoxConnector(),
        FyersConnector(),
        AngelOneConnector(),
        BreezeConnector(),
        DhanConnector(),
    )
}

__all__ = ["BrokerHolding", "Connector", "CONNECTORS"]
