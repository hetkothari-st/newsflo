from app.companies.candidates import (
    candidate_companies, candidate_tickers, format_candidates,
)
from app.models import Company


def _seed(db_session, rows):
    for ticker, name, sector, tier, desc in rows:
        db_session.add(Company(
            ticker=ticker, name=name, sector=sector, index_tier=tier, business_desc=desc,
        ))
    db_session.commit()


def test_returns_companies_only_for_the_named_sectors(db_session):
    _seed(db_session, [
        ("HPCL.NS", "Hindustan Petroleum", "oil_gas", "NIFTY50", "Refines crude oil."),
        ("ITC.NS", "ITC Ltd.", "fmcg", "NIFTY50", "Sells cigarettes and packaged foods."),
    ])

    result = candidate_companies(db_session, ["oil_gas"])

    assert [c.ticker for c in result] == ["HPCL.NS"]


def test_orders_by_market_cap_so_prominent_names_survive_the_limit(db_session):
    # Ordering follows app.companies.resolution's fan-out branch (I4): real
    # size (market cap), not index_tier -- most of the post-universe-merge
    # rows sit in index_tier="OTHER", which would otherwise collapse the
    # ordering to alphabetical.
    _seed(db_session, [
        ("SMALL.NS", "Small Oil Ltd.", "oil_gas", "OTHER", "A small refiner."),
        ("BIG.NS", "Big Oil Ltd.", "oil_gas", "OTHER", "A large refiner."),
    ])
    db_session.query(Company).filter_by(ticker="SMALL.NS").one().market_cap = 100.0
    db_session.query(Company).filter_by(ticker="BIG.NS").one().market_cap = 900_000.0
    db_session.commit()

    result = candidate_companies(db_session, ["oil_gas"], limit_per_sector=1)

    assert [c.ticker for c in result] == ["BIG.NS"]


def test_null_market_cap_sorts_last_and_ties_break_by_ticker(db_session):
    # nullslast(): a company with no market cap at all must not outrank one
    # that has a real, positive cap, however small. Among rows tied on
    # market cap (including both-null), the ticker-ascending tiebreak keeps
    # the prompt's company order reproducible across runs.
    _seed(db_session, [
        ("ZZZ.NS", "ZZZ Ltd.", "oil_gas", "NIFTY50", "desc"),
        ("AAA.NS", "AAA Ltd.", "oil_gas", "NIFTY100", "desc"),
        ("NOCAP.NS", "No Cap Ltd.", "oil_gas", "NIFTY50", "desc"),
    ])
    db_session.query(Company).filter_by(ticker="ZZZ.NS").one().market_cap = 100.0
    db_session.query(Company).filter_by(ticker="AAA.NS").one().market_cap = 100.0
    db_session.commit()

    result = candidate_companies(db_session, ["oil_gas"])

    assert [c.ticker for c in result] == ["AAA.NS", "ZZZ.NS", "NOCAP.NS"]


def test_excludes_non_tradeable_or_non_indian_companies(db_session):
    # I1: without this filter, RESTRICTED/SME/SUSPENDED/GLOBAL rows are
    # eligible for both the prompt text and the tool schema's ticker enum --
    # confirmed live, an "auto" candidate call returned 40 candidates of
    # which 0 were Indian. Same predicate as
    # app.companies.resolution.resolve_companies' fan-out branch.
    _seed(db_session, [
        ("REAL.NS", "Real Auto Ltd.", "auto", "NIFTY50", "desc"),
        ("RESTRICTED.NS", "Restricted Auto Ltd.", "auto", "NIFTY50", "desc"),
        ("SME.NS", "SME Auto Ltd.", "auto", "OTHER", "desc"),
        ("SUSPENDED.NS", "Suspended Auto Ltd.", "auto", "OTHER", "desc"),
        ("GLOBAL", "Global Auto Inc.", "auto", "OTHER", "desc"),
    ])
    db_session.query(Company).filter_by(ticker="RESTRICTED.NS").one().tradeability = "RESTRICTED"
    db_session.query(Company).filter_by(ticker="SME.NS").one().tradeability = "SME"
    db_session.query(Company).filter_by(ticker="SUSPENDED.NS").one().tradeability = "SUSPENDED"
    db_session.query(Company).filter_by(ticker="GLOBAL").one().market = "GLOBAL"
    db_session.commit()

    result = candidate_companies(db_session, ["auto"])

    assert [c.ticker for c in result] == ["REAL.NS"]


def test_excludes_demo_companies(db_session):
    _seed(db_session, [
        ("SOMETEXTILE.NS", "Demo Textiles Ltd", "textiles", "NIFTY50", "Demo."),
    ])

    assert candidate_companies(db_session, ["textiles"]) == []


def test_deduplicates_across_repeated_sectors(db_session):
    _seed(db_session, [("HPCL.NS", "Hindustan Petroleum", "oil_gas", "NIFTY50", "Refines crude oil.")])

    result = candidate_companies(db_session, ["oil_gas", "oil_gas"])

    assert [c.ticker for c in result] == ["HPCL.NS"]


def test_format_includes_ticker_name_subsector_and_description(db_session):
    _seed(db_session, [("HPCL.NS", "Hindustan Petroleum", "oil_gas", "NIFTY50", "Refines crude oil.")])
    company = candidate_companies(db_session, ["oil_gas"])[0]
    company.sub_sector = "refining_marketing"

    text = format_candidates([company])

    assert "HPCL.NS" in text
    assert "Hindustan Petroleum" in text
    assert "refining_marketing" in text
    assert "Refines crude oil." in text


def test_format_handles_a_company_with_no_description(db_session):
    _seed(db_session, [("X.NS", "X Ltd.", "oil_gas", "NIFTYSMALLCAP250", None)])
    company = candidate_companies(db_session, ["oil_gas"])[0]

    text = format_candidates([company])

    assert "X.NS" in text
    assert "None" not in text


def test_candidate_tickers_returns_plain_strings(db_session):
    _seed(db_session, [("HPCL.NS", "Hindustan Petroleum", "oil_gas", "NIFTY50", "Refines crude oil.")])

    assert candidate_tickers(candidate_companies(db_session, ["oil_gas"])) == ["HPCL.NS"]


def test_empty_sector_list_returns_nothing(db_session):
    assert candidate_companies(db_session, []) == []
