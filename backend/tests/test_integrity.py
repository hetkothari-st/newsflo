from app.companies.integrity import (
    delete_demo_companies, is_demo_company,
)
from app.models import Company
from app.analysis.schemas import CompanyMention
from app.companies.resolution import resolve_companies


def test_known_demo_ticker_is_flagged():
    assert is_demo_company("SOMETEXTILE.NS") is True


def test_real_ticker_is_not_flagged():
    assert is_demo_company("RELIANCE.NS") is False


def test_delete_demo_companies_removes_only_demo_rows(db_session):
    db_session.add(Company(ticker="SOMETEXTILE.NS", name="Demo Textiles Ltd", sector="textiles", index_tier="OTHER"))
    db_session.add(Company(ticker="RELIANCE.NS", name="Reliance Industries Ltd.", sector="oil_gas", index_tier="NIFTY50"))
    db_session.commit()

    deleted = delete_demo_companies(db_session)

    assert deleted == ["SOMETEXTILE.NS"]
    remaining = {c.ticker for c in db_session.query(Company).all()}
    assert remaining == {"RELIANCE.NS"}


def test_delete_demo_companies_is_idempotent(db_session):
    db_session.add(Company(ticker="RELIANCE.NS", name="Reliance Industries Ltd.", sector="oil_gas", index_tier="NIFTY50"))
    db_session.commit()

    assert delete_demo_companies(db_session) == []


def test_resolution_never_returns_a_demo_company_by_ticker(db_session):
    db_session.add(Company(ticker="SOMETEXTILE.NS", name="Demo Textiles Ltd", sector="textiles", index_tier="OTHER"))
    db_session.commit()

    resolved = resolve_companies(db_session, [CompanyMention(
        name="Demo Textiles Ltd", ticker="SOMETEXTILE.NS", is_direct=True,
        direction="bullish", magnitude_low=1.0, magnitude_high=2.0,
        rationale="r", time_horizon="Short-Term",
    )])

    assert resolved == []


def test_sector_fanout_never_returns_a_demo_company(db_session):
    db_session.add(Company(ticker="SOMETEXTILE.NS", name="Demo Textiles Ltd", sector="textiles", index_tier="OTHER"))
    db_session.commit()

    resolved = resolve_companies(db_session, [CompanyMention(
        name="textiles sector", is_direct=False, sector="textiles",
        direction="bullish", magnitude_low=1.0, magnitude_high=2.0,
        rationale="r", time_horizon="Short-Term",
    )])

    assert resolved == []
