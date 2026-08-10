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


def test_backfill_shares_skips_nothing_for_bse_fresh_caps(db_session, monkeypatch):
    # BSE-fresh market_cap must NOT starve the shares backfill -- BSE never
    # publishes a share count, so the freshness gate that protects caps
    # does not apply here.
    db_session.add(Company(
        ticker="BSEFRESH.NS", name="BSE Fresh Ltd", sector="other", index_tier="OTHER",
        market="INDIA", market_cap=999.0, market_cap_source="BSE", market_cap_as_of=TODAY,
    ))
    db_session.commit()
    monkeypatch.setattr(market_caps, "fetch_shares_outstanding", lambda _t: 42.0)

    updated = market_caps.backfill_shares_outstanding(db_session, today=TODAY)
    assert updated == 1
    company = db_session.query(Company).one()
    assert company.shares_outstanding == 42.0
    assert company.shares_outstanding_as_of == TODAY


def test_backfill_shares_failed_fetch_keeps_previous_value(db_session, monkeypatch):
    stale_day = TODAY - timedelta(days=400)
    db_session.add(Company(
        ticker="KEEP.NS", name="Keep Ltd", sector="other", index_tier="OTHER",
        market="INDIA", market_cap=999.0,
        shares_outstanding=7.0, shares_outstanding_as_of=stale_day,
    ))
    db_session.commit()
    monkeypatch.setattr(market_caps, "fetch_shares_outstanding", lambda _t: None)

    updated = market_caps.backfill_shares_outstanding(db_session, today=TODAY)
    assert updated == 0
    company = db_session.query(Company).one()
    assert company.shares_outstanding == 7.0
    assert company.shares_outstanding_as_of == stale_day


def test_backfill_shares_respects_limit_and_freshness(db_session, monkeypatch):
    db_session.add(Company(
        ticker="FRESH.NS", name="Fresh Ltd", sector="other", index_tier="OTHER",
        market="INDIA", market_cap=1.0,
        shares_outstanding=5.0, shares_outstanding_as_of=TODAY,
    ))
    for i in range(3):
        db_session.add(Company(
            ticker=f"MISS{i}.NS", name=f"Missing {i}", sector="other", index_tier="OTHER",
            market="INDIA", market_cap=1.0,
        ))
    db_session.commit()
    calls: list[str] = []

    def fake_fetch(ticker):
        calls.append(ticker)
        return 10.0

    monkeypatch.setattr(market_caps, "fetch_shares_outstanding", fake_fetch)
    updated = market_caps.backfill_shares_outstanding(db_session, limit=2, today=TODAY)
    assert updated == 2
    assert len(calls) == 2
    assert "FRESH.NS" not in calls  # already fresh, not a candidate
