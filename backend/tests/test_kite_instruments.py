import httpx
import pytest

from app.companies.kite_instruments import fetch_kite_instruments, match_instrument_tokens
from app.models import Company

CSV_BODY = (
    "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,"
    "tick_size,lot_size,instrument_type,segment,exchange\n"
    "738561,2885,RELIANCE,RELIANCE INDUSTRIES,0,,0,0.05,1,EQ,NSE,NSE\n"
    "5633,22,ONGC,OIL AND NATURAL GAS CORP,0,,0,0.05,1,EQ,BSE,BSE\n"
    "999999,1,SOMEFUTURE,SOME FUTURE,0,2026-08-28,0,0.05,1,FUT,NFO-FUT,NFO\n"
)


class _FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def test_fetch_kite_instruments_filters_to_equity_nse_bse(monkeypatch):
    monkeypatch.setattr(
        "app.companies.kite_instruments.httpx.get",
        lambda url, timeout=None: _FakeResponse(CSV_BODY),
    )

    rows = fetch_kite_instruments()

    assert {r["tradingsymbol"] for r in rows} == {"RELIANCE", "ONGC"}


def test_fetch_kite_instruments_raises_on_http_error(monkeypatch):
    class _FailingResponse:
        def raise_for_status(self):
            raise httpx.HTTPStatusError("boom", request=None, response=None)

    monkeypatch.setattr(
        "app.companies.kite_instruments.httpx.get",
        lambda url, timeout=None: _FailingResponse(),
    )

    with pytest.raises(httpx.HTTPStatusError):
        fetch_kite_instruments()


def test_match_instrument_tokens_sets_token_by_ticker_and_exchange_suffix(db_session):
    db_session.add(Company(
        ticker="RELIANCE.NS", name="Reliance", sector="oil_gas",
        index_tier="NIFTY50", market_cap=1.0,
    ))
    db_session.add(Company(
        ticker="ONGC.BO", name="ONGC BSE", sector="oil_gas",
        index_tier="NIFTY50", market_cap=1.0,
    ))
    db_session.commit()
    rows = [
        {"tradingsymbol": "RELIANCE", "exchange": "NSE", "instrument_token": "738561"},
        {"tradingsymbol": "ONGC", "exchange": "BSE", "instrument_token": "5633"},
        {"tradingsymbol": "NOMATCH", "exchange": "NSE", "instrument_token": "1"},
    ]

    updated = match_instrument_tokens(db_session, rows)

    assert updated == 2
    reliance = db_session.query(Company).filter_by(ticker="RELIANCE.NS").one()
    ongc = db_session.query(Company).filter_by(ticker="ONGC.BO").one()
    assert reliance.instrument_token == 738561
    assert ongc.instrument_token == 5633
