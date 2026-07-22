from app.market import cap_tier
from app.models import Company


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
