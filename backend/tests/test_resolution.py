from app.analysis.schemas import CompanyMention
from app.companies.resolution import resolve_companies
from app.models import Company


def _make_company(session, ticker, name, sector, market_cap):
    company = Company(ticker=ticker, name=name, sector=sector, index_tier="NIFTY50", market_cap=market_cap)
    session.add(company)
    session.commit()
    return company


def test_resolve_direct_mention(db_session):
    company = _make_company(db_session, "RELIANCE.NS", "Reliance Industries", "oil_gas", 1_800_000.0)
    mention = CompanyMention(
        name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
        direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin",
    )

    resolved = resolve_companies(db_session, [mention])

    assert len(resolved) == 1
    assert resolved[0]["company_id"] == company.id
    assert resolved[0]["basis"] == "direct_mention"


def test_resolve_sector_inference_picks_top_5_by_market_cap(db_session):
    for i in range(7):
        _make_company(db_session, f"OIL{i}.NS", f"Oil Co {i}", "oil_gas", market_cap=float(7 - i))
    mention = CompanyMention(
        name="oil sector", ticker=None, is_direct=False, sector="oil_gas",
        direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="crude spike",
    )

    resolved = resolve_companies(db_session, [mention])

    assert len(resolved) == 5
    assert all(r["basis"] == "sector_inference" for r in resolved)


def test_resolve_direct_mention_with_unknown_ticker_is_skipped(db_session):
    mention = CompanyMention(
        name="Unknown Corp", ticker="UNKNOWN.NS", is_direct=True, sector=None,
        direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="n/a",
    )

    resolved = resolve_companies(db_session, [mention])

    assert resolved == []
