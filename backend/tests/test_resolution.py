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
