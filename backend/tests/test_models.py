import pytest

from app.models import Article, Company


def test_create_company(db_session):
    company = Company(
        ticker="RELIANCE.NS", name="Reliance Industries",
        sector="oil_gas", index_tier="NIFTY50", market_cap=1_800_000.0,
    )
    db_session.add(company)
    db_session.commit()

    fetched = db_session.query(Company).filter_by(ticker="RELIANCE.NS").one()
    assert fetched.name == "Reliance Industries"
    assert fetched.index_tier == "NIFTY50"


def test_company_isin_column(db_session):
    company = Company(
        ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas",
        index_tier="NIFTY50", market_cap=1_800_000.0, isin="INE002A01018",
    )
    db_session.add(company)
    db_session.commit()

    fetched = db_session.query(Company).filter_by(ticker="RELIANCE.NS").one()
    assert fetched.isin == "INE002A01018"


def test_company_index_membership(db_session):
    company = Company(
        ticker="HDFCBANK.NS", name="HDFC Bank", sector="banking",
        index_tier="NIFTY50", market_cap=1_000_000.0,
    )
    db_session.add(company)
    db_session.commit()

    from app.models import CompanyIndexMembership
    db_session.add(CompanyIndexMembership(company_id=company.id, index_code="NIFTYBANK"))
    db_session.add(CompanyIndexMembership(company_id=company.id, index_code="NIFTY50"))
    db_session.commit()

    rows = db_session.query(CompanyIndexMembership).filter_by(company_id=company.id).all()
    assert {r.index_code for r in rows} == {"NIFTYBANK", "NIFTY50"}


def test_article_url_is_unique(db_session):
    db_session.add(Article(source="moneycontrol", url="https://example.com/a", title="Headline 1"))
    db_session.commit()

    db_session.add(Article(source="moneycontrol", url="https://example.com/a", title="Duplicate"))
    with pytest.raises(Exception):
        db_session.commit()


def test_user_email_alerts_enabled_defaults_true(db_session):
    from app.models import User
    user = User(email="prefs@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    # Integer column (1/0), not Boolean -- see models.py's comment on why.
    assert user.email_alerts_enabled == 1


def test_company_instrument_token_column(db_session):
    company = Company(
        ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas",
        index_tier="NIFTY50", market_cap=1_800_000.0, instrument_token=738561,
    )
    db_session.add(company)
    db_session.commit()

    fetched = db_session.query(Company).filter_by(ticker="RELIANCE.NS").one()
    assert fetched.instrument_token == 738561


def test_company_instrument_token_defaults_to_none(db_session):
    company = Company(
        ticker="TCS.NS", name="TCS", sector="it",
        index_tier="NIFTY50", market_cap=1_500_000.0,
    )
    db_session.add(company)
    db_session.commit()

    fetched = db_session.query(Company).filter_by(ticker="TCS.NS").one()
    assert fetched.instrument_token is None
