from app.analysis.schemas import CompanyMention
from app.companies.resolution import resolve_companies
from app.models import Company


def _make_company(session, ticker, name, sector, market_cap, index_tier="NIFTY50"):
    company = Company(ticker=ticker, name=name, sector=sector, index_tier=index_tier, market_cap=market_cap)
    session.add(company)
    session.commit()
    return company


def test_resolve_direct_mention(db_session):
    company = _make_company(db_session, "RELIANCE.NS", "Reliance Industries", "oil_gas", 1_800_000.0, index_tier="NIFTY50")
    mention = CompanyMention(
        name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
        direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin",
    )

    resolved = resolve_companies(db_session, [mention])

    assert len(resolved) == 1
    assert resolved[0]["company_id"] == company.id
    assert resolved[0]["basis"] == "direct_mention"


def test_resolve_sector_inference_picks_top_5_by_index_tier(db_session):
    # 3 top-tier companies plus 5 lower-tier companies: more than 5 total in
    # the sector, so the resolver must prefer the higher-tier companies.
    nifty50_tickers = [f"OILN50_{i}.NS" for i in range(3)]
    other_tickers = [f"OILOTHER_{i}.NS" for i in range(5)]
    for ticker in nifty50_tickers:
        _make_company(db_session, ticker, ticker, "oil_gas", market_cap=None, index_tier="NIFTY50")
    for ticker in other_tickers:
        _make_company(db_session, ticker, ticker, "oil_gas", market_cap=None, index_tier="OTHER")

    mention = CompanyMention(
        name="oil sector", ticker=None, is_direct=False, sector="oil_gas",
        direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="crude spike",
    )

    resolved = resolve_companies(db_session, [mention])

    assert len(resolved) == 5
    assert all(r["basis"] == "sector_inference" for r in resolved)

    resolved_tickers = {
        db_session.get(Company, r["company_id"]).ticker for r in resolved
    }
    # All 3 NIFTY50 companies must be included in preference to OTHER tier.
    assert set(nifty50_tickers).issubset(resolved_tickers)
    assert len(resolved_tickers & set(other_tickers)) == 2


def test_resolve_direct_mention_with_unknown_ticker_is_skipped(db_session):
    mention = CompanyMention(
        name="Unknown Corp", ticker="UNKNOWN.NS", is_direct=True, sector=None,
        direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="n/a",
    )

    resolved = resolve_companies(db_session, [mention])

    assert resolved == []


def test_resolve_direct_mention_falls_back_to_name_when_ticker_missing(db_session):
    # The model is confident of the company but not the exact ticker -- the
    # resolver must still use the specific name rather than discarding the
    # mention or falling back to unrelated sector-wide picks.
    company = _make_company(db_session, "SBIN.NS", "State Bank of India", "banking", None)
    mention = CompanyMention(
        name="State Bank of India", ticker=None, is_direct=True, sector="banking",
        direction="bearish", magnitude_low=-2.0, magnitude_high=-1.0, rationale="higher funding costs",
    )

    resolved = resolve_companies(db_session, [mention])

    assert len(resolved) == 1
    assert resolved[0]["company_id"] == company.id
    assert resolved[0]["basis"] == "direct_mention"


def test_resolve_direct_mention_name_fallback_skips_ambiguous_matches(db_session):
    # Two companies both contain "Bank" -- an ambiguous substring match must
    # be skipped entirely (omit rather than mismatch), not guessed at.
    _make_company(db_session, "HDFCBANK.NS", "HDFC Bank", "banking", None)
    _make_company(db_session, "ICICIBANK.NS", "ICICI Bank", "banking", None)
    mention = CompanyMention(
        name="Bank", ticker=None, is_direct=True, sector="banking",
        direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="vague",
    )

    resolved = resolve_companies(db_session, [mention])

    assert resolved == []


def test_resolve_direct_mention_name_fallback_is_case_insensitive(db_session):
    company = _make_company(db_session, "TCS.NS", "Tata Consultancy Services", "it", None)
    mention = CompanyMention(
        name="tata consultancy services", ticker=None, is_direct=True, sector="it",
        direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="strong order book",
    )

    resolved = resolve_companies(db_session, [mention])

    assert len(resolved) == 1
    assert resolved[0]["company_id"] == company.id


def test_resolve_dedupes_repeated_sector_inference_across_mentions(db_session):
    # Observed in production: the model named 4 specific companies in one
    # article but marked all 4 is_direct=false with the same sector -- each
    # independently expanding to the same top-5 sector companies produced 20
    # duplicate rows for a single article. Same sector mentioned twice must
    # resolve the sector's companies only once.
    for i in range(3):
        _make_company(db_session, f"OIL_{i}.NS", f"Oil Co {i}", "oil_gas", None, index_tier="NIFTY50")
    mentions = [
        CompanyMention(
            name="Indian Oil Corporation", ticker="IOC.NS", is_direct=False, sector="oil_gas",
            direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="easing crude prices",
        ),
        CompanyMention(
            name="Bharat Petroleum", ticker="BPCL.NS", is_direct=False, sector="oil_gas",
            direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="easing crude prices",
        ),
    ]

    resolved = resolve_companies(db_session, mentions)

    assert len(resolved) == 3
    assert len({r["company_id"] for r in resolved}) == 3


def test_resolve_dedupes_direct_mention_already_covered_by_sector_inference(db_session):
    # A company resolved via an earlier sector-wide expansion must not be
    # appended again if a later direct mention in the same article names it.
    company = _make_company(db_session, "OIL_0.NS", "Oil Co 0", "oil_gas", None, index_tier="NIFTY50")
    mentions = [
        CompanyMention(
            name="oil sector", ticker=None, is_direct=False, sector="oil_gas",
            direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="crude spike",
        ),
        CompanyMention(
            name="Oil Co 0", ticker="OIL_0.NS", is_direct=True, sector="oil_gas",
            direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="named directly",
        ),
    ]

    resolved = resolve_companies(db_session, mentions)

    assert len([r for r in resolved if r["company_id"] == company.id]) == 1
