from app.companies.candidates import (
    LONG_LIST_THRESHOLD, MAX_CANDIDATES_PER_PROMPT, MAX_CANDIDATES_PER_SECTOR,
    MIN_CANDIDATES_PER_SECTOR, candidate_companies, candidate_tickers, format_candidates,
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


# -- breadth: more genuine material to select from ------------------------

def test_per_sector_limit_is_sixty(db_session):
    # Raised 40 -> 60. The model can only name companies that appear in this
    # list, so a genuine supplier ranked 45th in its sector was unreachable
    # however thorough the prompt asked the model to be.
    assert MAX_CANDIDATES_PER_SECTOR == 60


def test_returns_up_to_sixty_companies_for_one_sector(db_session):
    _seed(db_session, [
        (f"C{i:03d}.NS", f"Company {i}", "infra", "OTHER", "desc") for i in range(70)
    ])

    assert len(candidate_companies(db_session, ["infra"])) == 60


# -- prompt-size guards ---------------------------------------------------

def test_a_short_list_keeps_business_desc(db_session):
    _seed(db_session, [("HPCL.NS", "Hindustan Petroleum", "oil_gas", "NIFTY50", "Refines crude oil.")])

    text = format_candidates(candidate_companies(db_session, ["oil_gas"]))

    assert "Refines crude oil." in text


def test_a_long_list_drops_business_desc_but_keeps_ticker_name_and_sub_sector(db_session):
    # Trimming the LINE, never the company: a candidate the model never sees
    # cannot be selected at all, while one listed as ticker + name +
    # sub_sector is still fully selectable and still resolves.
    _seed(db_session, [
        (f"C{i:03d}.NS", f"Company {i}", "infra", "OTHER", "A long business description here.")
        for i in range(LONG_LIST_THRESHOLD + 1)
    ])
    companies = candidate_companies(db_session, ["infra"], limit_per_sector=LONG_LIST_THRESHOLD + 1)
    for company in companies:
        company.sub_sector = "roads"

    text = format_candidates(companies)

    assert "A long business description here." not in text
    assert "C000.NS" in text
    assert "Company 0" in text
    assert "roads" in text


def test_include_desc_overrides_the_length_heuristic_both_ways(db_session):
    _seed(db_session, [
        (f"C{i:03d}.NS", f"Company {i}", "infra", "OTHER", "A description.")
        for i in range(LONG_LIST_THRESHOLD + 1)
    ])
    companies = candidate_companies(db_session, ["infra"], limit_per_sector=LONG_LIST_THRESHOLD + 1)

    assert "A description." in format_candidates(companies, include_desc=True)
    assert "A description." not in format_candidates(companies[:1], include_desc=False)


def test_many_sectors_share_one_prompt_budget_instead_of_overflowing_it(db_session):
    # The direct-company stage bundles EVERY primary sector into one call, so
    # the per-sector limit alone does not bound the prompt. 6 x 60 = 360
    # candidates measures past llama-3.3-70b-versatile's 12k tokens/minute
    # even with business_desc already dropped, and a 413 there costs the
    # article every direct company, not just a few.
    sectors = ["infra", "oil_gas", "banking", "pharma", "fmcg", "it"]
    for sector in sectors:
        _seed(db_session, [
            (f"{sector.upper()}{i:03d}.NS", f"{sector} co {i}", sector, "OTHER", "desc")
            for i in range(MAX_CANDIDATES_PER_SECTOR)
        ])

    result = candidate_companies(db_session, sectors)

    assert len(result) <= MAX_CANDIDATES_PER_PROMPT
    # Evenly shared, not first-come-first-served: every sector is represented.
    per_sector = {s: sum(1 for c in result if c.sector == s) for s in sectors}
    assert min(per_sector.values()) >= MIN_CANDIDATES_PER_SECTOR
    assert max(per_sector.values()) - min(per_sector.values()) <= 1


def test_the_prompt_budget_does_not_bind_at_a_small_sector_count(db_session):
    for sector in ["infra", "oil_gas"]:
        _seed(db_session, [
            (f"{sector.upper()}{i:03d}.NS", f"{sector} co {i}", sector, "OTHER", "desc")
            for i in range(MAX_CANDIDATES_PER_SECTOR)
        ])

    result = candidate_companies(db_session, ["infra", "oil_gas"])

    assert len(result) == 2 * MAX_CANDIDATES_PER_SECTOR


def test_an_explicit_limit_from_the_caller_is_honoured_unchanged(db_session):
    for sector in ["infra", "oil_gas", "banking", "pharma", "fmcg", "it"]:
        _seed(db_session, [
            (f"{sector.upper()}{i:03d}.NS", f"{sector} co {i}", sector, "OTHER", "desc")
            for i in range(5)
        ])

    result = candidate_companies(
        db_session, ["infra", "oil_gas", "banking", "pharma", "fmcg", "it"], limit_per_sector=5,
    )

    assert len(result) == 30
