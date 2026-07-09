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


def test_article_url_is_unique(db_session):
    db_session.add(Article(source="moneycontrol", url="https://example.com/a", title="Headline 1"))
    db_session.commit()

    db_session.add(Article(source="moneycontrol", url="https://example.com/a", title="Duplicate"))
    with pytest.raises(Exception):
        db_session.commit()
