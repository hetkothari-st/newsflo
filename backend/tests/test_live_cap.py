from datetime import datetime, timedelta, timezone

from app.models import Company
from app.prices import live_cap
from app.prices.live_price import LIVE_PRICE_CACHE

NOW = datetime(2026, 8, 10, 10, 0, tzinfo=timezone.utc)


def _company(db_session, **overrides):
    fields = dict(
        ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas",
        index_tier="NIFTY50", market="INDIA", market_cap=1_000_000.0,
        instrument_token=738561, shares_outstanding=100.0,
    )
    fields.update(overrides)
    company = Company(**fields)
    db_session.add(company)
    db_session.commit()
    return company


def _clear_cache():
    LIVE_PRICE_CACHE.clear()


def test_fresh_tick_and_shares_gives_live_cap(db_session):
    _clear_cache()
    company = _company(db_session)
    LIVE_PRICE_CACHE[738561] = {"ltp": 25_000.0, "as_of": NOW - timedelta(minutes=1)}

    cap = live_cap.compute_live_cap(company, now=NOW)
    assert cap is not None
    assert cap.source == "live"
    assert cap.market_cap == 25_000.0 * 100.0


def test_stale_tick_falls_back_to_stored_cap(db_session):
    _clear_cache()
    company = _company(db_session)
    LIVE_PRICE_CACHE[738561] = {"ltp": 25_000.0, "as_of": NOW - timedelta(hours=3)}

    cap = live_cap.compute_live_cap(company, now=NOW)
    assert cap.source == "stored"
    assert cap.market_cap == 1_000_000.0


def test_missing_shares_never_fabricates_a_live_number(db_session):
    _clear_cache()
    company = _company(db_session, shares_outstanding=None)
    LIVE_PRICE_CACHE[738561] = {"ltp": 25_000.0, "as_of": NOW - timedelta(minutes=1)}

    cap = live_cap.compute_live_cap(company, now=NOW)
    assert cap.source == "stored"
    assert cap.market_cap == 1_000_000.0


def test_no_token_and_no_stored_cap_is_unrankable(db_session):
    _clear_cache()
    company = _company(db_session, market_cap=None, instrument_token=None)

    assert live_cap.compute_live_cap(company, now=NOW) is None


def test_ranking_orders_by_effective_cap_with_ticker_tiebreak(db_session):
    _clear_cache()
    _company(db_session, ticker="AAA.NS", market_cap=500.0, instrument_token=1, shares_outstanding=10.0)
    _company(db_session, ticker="BBB.NS", market_cap=900.0, instrument_token=None, shares_outstanding=None)
    _company(db_session, ticker="CCC.NS", market_cap=900.0, instrument_token=None, shares_outstanding=None)
    # AAA gets a live tick lifting it above both stored-cap rows.
    LIVE_PRICE_CACHE[1] = {"ltp": 100.0, "as_of": NOW - timedelta(minutes=1)}

    ranked = live_cap.rank_live_caps(db_session, now=NOW)
    assert [c.ticker for c in ranked] == ["AAA.NS", "BBB.NS", "CCC.NS"]
    assert ranked[0].source == "live" and ranked[0].market_cap == 1000.0
    # Equal stored caps break ties by ticker ascending, matching cap_tier.
    assert [c.source for c in ranked[1:]] == ["stored", "stored"]


def test_naive_tick_timestamp_is_treated_as_utc(db_session):
    _clear_cache()
    company = _company(db_session)
    LIVE_PRICE_CACHE[738561] = {"ltp": 25_000.0, "as_of": (NOW - timedelta(minutes=1)).replace(tzinfo=None)}

    cap = live_cap.compute_live_cap(company, now=NOW)
    assert cap.source == "live"
