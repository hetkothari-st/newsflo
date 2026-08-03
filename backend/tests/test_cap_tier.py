from datetime import date, timedelta

from app.market import cap_tier
from app.market.cap_tier import resolve_cap_tier
from app.models import Company

TODAY = date(2026, 8, 3)


def test_top_100_by_market_cap_are_large():
    companies = [(f"T{i}.NS", float(1000 - i)) for i in range(150)]  # descending cap
    tiers = cap_tier.compute_cap_tiers(companies)
    assert tiers["T0.NS"] == "LARGE"
    assert tiers["T99.NS"] == "LARGE"
    assert tiers["T100.NS"] == "MID"


def test_101_to_250_are_mid():
    companies = [(f"T{i}.NS", float(1000 - i)) for i in range(260)]
    tiers = cap_tier.compute_cap_tiers(companies)
    assert tiers["T100.NS"] == "MID"
    assert tiers["T249.NS"] == "MID"
    assert tiers["T250.NS"] == "SMALL"


def test_rest_are_small():
    companies = [(f"T{i}.NS", float(1000 - i)) for i in range(300)]
    tiers = cap_tier.compute_cap_tiers(companies)
    assert tiers["T299.NS"] == "SMALL"


def test_boundary_is_config_driven():
    from app import config
    companies = [(f"T{i}.NS", float(1000 - i)) for i in range(300)]
    tiers = cap_tier.compute_cap_tiers(companies)
    boundary_ticker = f"T{config.AMFI_LARGE_CAP_RANK_CUTOFF - 1}.NS"
    assert tiers[boundary_ticker] == "LARGE"


def test_compute_cap_tier_for_ticker_ranks_from_live_db_state(db_session):
    for i in range(105):
        db_session.add(Company(
            ticker=f"T{i}.NS", name=f"Company {i}", sector="other",
            index_tier="OTHER", market_cap=float(1000 - i),
        ))
    db_session.commit()

    assert cap_tier.compute_cap_tier_for_ticker(db_session, "T0.NS") == "LARGE"
    assert cap_tier.compute_cap_tier_for_ticker(db_session, "T104.NS") == "MID"


def test_compute_cap_tier_for_ticker_none_when_no_market_cap(db_session):
    db_session.add(Company(
        ticker="NOCAP.NS", name="No Cap Co", sector="other", index_tier="OTHER", market_cap=None,
    ))
    db_session.commit()

    assert cap_tier.compute_cap_tier_for_ticker(db_session, "NOCAP.NS") is None


def test_compute_cap_tier_for_ticker_none_when_ticker_not_found(db_session):
    assert cap_tier.compute_cap_tier_for_ticker(db_session, "NOPE.NS") is None


def test_rank_501_and_beyond_is_micro():
    companies = [(f"T{i}.NS", float(10000 - i)) for i in range(600)]
    tiers = cap_tier.compute_cap_tiers(companies)
    assert tiers["T499.NS"] == "SMALL"
    assert tiers["T500.NS"] == "MICRO"
    assert tiers["T599.NS"] == "MICRO"


def _seed(session, count=600, **kw):
    for i in range(count):
        session.add(Company(
            ticker=f"T{i}.NS", name=f"Company {i}", sector="other", index_tier="OTHER",
            market_cap=float(10000 - i), market_cap_source="BSE", market_cap_as_of=TODAY,
            **({} if i else kw),
        ))
    session.commit()


def test_derived_tier_reports_market_cap_provenance(db_session):
    _seed(db_session, count=5)
    company = db_session.query(Company).filter_by(ticker="T0.NS").one()
    resolved = resolve_cap_tier(db_session, company, today=TODAY)
    assert resolved.tier == "LARGE"
    assert resolved.source == "derived from BSE 2026-08-03"


def test_amfi_tier_takes_precedence(db_session):
    _seed(db_session, count=5, amfi_tier="MID", amfi_rank=120, amfi_as_of=TODAY)
    company = db_session.query(Company).filter_by(ticker="T0.NS").one()
    resolved = resolve_cap_tier(db_session, company, today=TODAY)
    assert resolved.tier == "MID"
    assert resolved.source == "AMFI 2026-08-03"


def test_amfi_small_with_derived_micro_rank_reports_micro(db_session):
    _seed(db_session, count=600, amfi_tier="SMALL", amfi_rank=900, amfi_as_of=TODAY)
    # T0 has the largest cap, so give the AMFI values to a rank-501+ company.
    company = db_session.query(Company).filter_by(ticker="T550.NS").one()
    company.amfi_tier = "SMALL"
    company.amfi_as_of = TODAY
    db_session.commit()
    resolved = resolve_cap_tier(db_session, company, today=TODAY)
    assert resolved.tier == "MICRO"
    assert "NSE index methodology" in resolved.source


def test_stale_market_cap_withholds_the_tier(db_session):
    _seed(db_session, count=5)
    company = db_session.query(Company).filter_by(ticker="T0.NS").one()
    company.market_cap_as_of = TODAY - timedelta(days=400)
    db_session.commit()
    assert resolve_cap_tier(db_session, company, today=TODAY) is None


def test_missing_market_cap_returns_none(db_session):
    company = Company(
        ticker="NOCAP.NS", name="No Cap Ltd", sector="other", index_tier="OTHER",
    )
    db_session.add(company)
    db_session.commit()
    assert resolve_cap_tier(db_session, company, today=TODAY) is None


def test_global_company_never_gets_a_tier(db_session):
    company = Company(
        ticker="AAPL", name="Apple", sector="it", index_tier="GLOBAL_LARGE_CAP",
        market="GLOBAL", market_cap=3000000.0, market_cap_source="yfinance",
        market_cap_as_of=TODAY,
    )
    db_session.add(company)
    db_session.commit()
    assert resolve_cap_tier(db_session, company, today=TODAY) is None


def test_global_company_does_not_shift_indian_rankings(db_session):
    # 100 Indian companies: IND99.NS is rank 100 by cap, exactly on the
    # LARGE/MID boundary (AMFI_LARGE_CAP_RANK_CUTOFF=100) and must stay
    # LARGE. A GLOBAL row with a bigger market_cap must never enter this
    # ranking pool -- if it did, it would take rank 1 and bump every
    # Indian company (including IND99.NS) down a slot into MID.
    for i in range(100):
        db_session.add(Company(
            ticker=f"IND{i}.NS", name=f"Indian Co {i}", sector="other", index_tier="OTHER",
            market_cap=float(1000 - i), market="INDIA",
        ))
    db_session.add(Company(
        ticker="GLOBALCO", name="Global Co", sector="it", index_tier="GLOBAL_LARGE_CAP",
        market="GLOBAL", market_cap=999999.0,
    ))
    db_session.commit()

    assert cap_tier.compute_cap_tier_for_ticker(db_session, "IND99.NS") == "LARGE"


def test_compute_cap_tier_for_ticker_none_for_global_ticker(db_session):
    db_session.add(Company(
        ticker="AAPL", name="Apple", sector="it", index_tier="GLOBAL_LARGE_CAP",
        market="GLOBAL", market_cap=3000000.0,
    ))
    db_session.commit()
    assert cap_tier.compute_cap_tier_for_ticker(db_session, "AAPL") is None
