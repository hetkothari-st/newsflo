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


def test_orders_by_index_tier_so_prominent_names_survive_the_limit(db_session):
    _seed(db_session, [
        ("SMALL.NS", "Small Oil Ltd.", "oil_gas", "NIFTYSMALLCAP250", "A small refiner."),
        ("BIG.NS", "Big Oil Ltd.", "oil_gas", "NIFTY50", "A large refiner."),
    ])

    result = candidate_companies(db_session, ["oil_gas"], limit_per_sector=1)

    assert [c.ticker for c in result] == ["BIG.NS"]


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
