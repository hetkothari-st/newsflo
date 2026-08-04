from datetime import date, timedelta

from app.companies import market_caps
from app.models import Company

TODAY = date(2026, 8, 3)


def test_yfinance_cap_is_labelled(db_session, monkeypatch):
    db_session.add(Company(
        ticker="NSEONLY.NS", name="NSE Only Ltd", sector="other", index_tier="OTHER",
    ))
    db_session.commit()
    monkeypatch.setattr(market_caps, "fetch_market_cap", lambda _t: 1234.0)

    market_caps.refresh_market_caps(db_session, ["NSEONLY.NS"], today=TODAY)
    company = db_session.query(Company).one()
    assert company.market_cap == 1234.0
    assert company.market_cap_source == "yfinance"
    assert company.market_cap_as_of == TODAY


def test_yfinance_never_overwrites_a_fresh_exchange_cap(db_session, monkeypatch):
    db_session.add(Company(
        ticker="RELIANCE.NS", name="Reliance Industries Limited", sector="oil_gas",
        index_tier="NIFTY50", market_cap=1750000.0, market_cap_source="BSE",
        market_cap_as_of=TODAY,
    ))
    db_session.commit()
    monkeypatch.setattr(market_caps, "fetch_market_cap", lambda _t: 1.0)

    market_caps.refresh_market_caps(db_session, ["RELIANCE.NS"], today=TODAY)
    company = db_session.query(Company).one()
    assert company.market_cap == 1750000.0
    assert company.market_cap_source == "BSE"


def test_yfinance_does_replace_a_stale_exchange_cap(db_session, monkeypatch):
    db_session.add(Company(
        ticker="RELIANCE.NS", name="Reliance Industries Limited", sector="oil_gas",
        index_tier="NIFTY50", market_cap=1750000.0, market_cap_source="BSE",
        market_cap_as_of=TODAY - timedelta(days=400),
    ))
    db_session.commit()
    monkeypatch.setattr(market_caps, "fetch_market_cap", lambda _t: 9.0)

    market_caps.refresh_market_caps(db_session, ["RELIANCE.NS"], today=TODAY)
    company = db_session.query(Company).one()
    assert company.market_cap == 9.0
    assert company.market_cap_source == "yfinance"
