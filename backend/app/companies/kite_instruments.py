import csv

import httpx
from sqlalchemy.orm import Session

from app.models import Company

INSTRUMENTS_URL = "https://api.kite.trade/instruments"

# Kite's own suffix-free "exchange" column value -> the ".NS"/".BO" ticker
# suffix this codebase already uses (see nifty_indices_seed.py / test fixtures
# like "500325.BO"). Only cash-equity NSE/BSE rows are relevant here --
# futures/options segments (NFO-FUT, NFO-OPT, MCX-FUT, ...) never match a
# Company row.
_EXCHANGE_SUFFIX = {"NSE": ".NS", "BSE": ".BO"}


def fetch_kite_instruments() -> list[dict]:
    """Fetch Zerodha's public instrument dump (no auth required) and return
    only NSE/BSE cash-equity rows. Raises on any HTTP failure -- this is a
    one-off/periodic maintenance script's data source, not a request-path
    call, so "fail loudly" is correct here (unlike price_series.py's
    request-path degrade-to-None contract).
    """
    response = httpx.get(INSTRUMENTS_URL, timeout=30.0)
    response.raise_for_status()
    reader = csv.DictReader(response.text.splitlines())
    return [
        row for row in reader
        if row["exchange"] in _EXCHANGE_SUFFIX and row["instrument_type"] == "EQ"
    ]


def match_instrument_tokens(session: Session, rows: list[dict]) -> int:
    """Set ``Company.instrument_token`` for every company whose ticker
    matches a row's ``tradingsymbol`` + the exchange's ticker suffix (e.g.
    "RELIANCE" on NSE -> "RELIANCE.NS"). Returns the number of companies
    updated; a row with no matching ticker is silently skipped -- that
    company's instrument_token simply stays null (see live_price.py's
    "no token -> not available" degrade path).
    """
    updated = 0
    for row in rows:
        suffix = _EXCHANGE_SUFFIX.get(row["exchange"])
        if suffix is None:
            continue
        ticker = f"{row['tradingsymbol']}{suffix}"
        company = session.query(Company).filter_by(ticker=ticker).one_or_none()
        if company is None:
            continue
        company.instrument_token = int(row["instrument_token"])
        updated += 1
    session.commit()
    return updated
