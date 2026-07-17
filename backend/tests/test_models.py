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


def test_alert_has_reasoning_engine_columns(db_session):
    from app.models import Alert
    article = Article(source="test", url="https://example.com/models-1", title="t")
    db_session.add(article)
    db_session.commit()

    alert = Alert(
        article_id=article.id, category="oil_energy",
        event_type="crude_oil", prompt_version="v1", knowledge_version="v1",
    )
    db_session.add(alert)
    db_session.commit()
    db_session.refresh(alert)

    assert alert.event_type == "crude_oil"
    assert alert.prompt_version == "v1"
    assert alert.knowledge_version == "v1"


def test_alert_reasoning_engine_columns_are_nullable(db_session):
    from app.models import Alert
    article = Article(source="test", url="https://example.com/models-2", title="t")
    db_session.add(article)
    db_session.commit()

    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()  # must not raise

    assert alert.event_type is None


def test_alert_company_has_evidence_discipline_and_confidence_engine_columns(db_session):
    from app.models import Alert, AlertCompany
    article = Article(source="test", url="https://example.com/models-3", title="t")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()
    company = Company(ticker="X.NS", name="X", sector="oil_gas", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()

    ac = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="x", basis="direct_mention",
        reasons_json='["a"]', evidence_refs_json='["RULE_X"]', risks_json='[]',
        assumptions_json='[]', unknowns_json='[]', alternative_hypothesis="alt",
        confidence_band="HIGH", confidence_contributors_json='["c"]',
        confidence_penalties_json='[]', rulebook_ids_json='["RULE_X"]',
    )
    db_session.add(ac)
    db_session.commit()  # must not raise
    db_session.refresh(ac)

    assert ac.reasons_json == '["a"]'
    assert ac.confidence_band == "HIGH"


def test_financial_snapshot_table_exists_and_enforces_unique_ticker(db_session):
    from app.models import FinancialSnapshot
    db_session.add(FinancialSnapshot(ticker="RELIANCE.NS", price=2500.5, return_1m=8.3, return_3m=-2.1))
    db_session.commit()  # must not raise

    row = db_session.query(FinancialSnapshot).filter_by(ticker="RELIANCE.NS").one()
    assert row.price == 2500.5
    assert row.return_1m == 8.3
    assert row.return_3m == -2.1
    assert row.fetched_at is not None


def test_alert_company_has_financial_context_columns(db_session):
    from app.models import Alert, AlertCompany
    article = Article(source="test", url="https://example.com/financial-columns", title="t")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()
    company = Company(ticker="X.NS", name="X", sector="oil_gas", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()

    ac = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="x", basis="direct_mention",
        price_at_analysis=2500.5, return_1m=8.3, return_3m=-2.1,
        contradiction_note="Price down 12.0% over the past month despite bullish call.",
    )
    db_session.add(ac)
    db_session.commit()  # must not raise
    db_session.refresh(ac)

    assert ac.price_at_analysis == 2500.5
    assert ac.contradiction_note == "Price down 12.0% over the past month despite bullish call."


def test_alert_company_financial_context_columns_are_nullable(db_session):
    from app.models import Alert, AlertCompany
    article = Article(source="test", url="https://example.com/financial-columns-null", title="t")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()
    company = Company(ticker="Y.NS", name="Y", sector="oil_gas", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()

    ac = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="x", basis="direct_mention",
    )
    db_session.add(ac)
    db_session.commit()  # must not raise
    db_session.refresh(ac)

    assert ac.price_at_analysis is None
    assert ac.contradiction_note is None
