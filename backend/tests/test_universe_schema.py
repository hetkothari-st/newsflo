from datetime import date

from app.models import Company, CompanyAlias, Listing


def _company(**kw):
    defaults = dict(ticker="TEST.NS", name="Test Ltd", sector="other", index_tier="OTHER")
    defaults.update(kw)
    return Company(**defaults)


def test_company_defaults_to_india_and_normal_tradeability(db_session):
    company = _company()
    db_session.add(company)
    db_session.commit()
    assert company.market == "INDIA"
    assert company.tradeability == "NORMAL"


def test_company_carries_official_classification_with_provenance(db_session):
    company = _company(
        official_sector="Energy",
        official_industry="Oil, Gas & Consumable Fuels",
        official_igroup="Petroleum Products",
        official_isubgroup="Refineries & Marketing",
        classification_source="BSE",
        classification_as_of=date(2026, 8, 3),
    )
    db_session.add(company)
    db_session.commit()
    assert company.official_isubgroup == "Refineries & Marketing"
    assert company.classification_source == "BSE"


def test_dual_listed_company_has_two_listings(db_session):
    company = _company(isin="INE002A01018")
    db_session.add(company)
    db_session.commit()
    db_session.add(Listing(
        company_id=company.id, exchange="NSE", symbol="RELIANCE",
        series="EQ", status="ACTIVE", is_sme=False, is_primary=True,
        source="NSE", as_of=date(2026, 8, 3),
    ))
    db_session.add(Listing(
        company_id=company.id, exchange="BSE", symbol="RELIANCE",
        scrip_code="500325", group_code="A", status="ACTIVE", is_sme=False,
        is_primary=False, source="BSE", as_of=date(2026, 8, 3),
    ))
    db_session.commit()
    assert len(company.listings) == 2
    assert {l.exchange for l in company.listings} == {"NSE", "BSE"}


def test_alias_rows_attach_to_company(db_session):
    company = _company()
    db_session.add(company)
    db_session.commit()
    db_session.add(CompanyAlias(
        company_id=company.id, alias="Test Limited",
        alias_type="LEGAL", normalized="test",
    ))
    db_session.commit()
    assert db_session.query(CompanyAlias).one().normalized == "test"


def test_company_carries_financials_with_provenance(db_session):
    company = _company(
        eps=28.98, ceps=41.67, pe=44.95, pb=3.36, opm=14.24, npm=7.99, roe=7.48,
        con_eps=65.15, con_pe=19.99,
        financials_source="BSE", financials_as_of=date(2026, 8, 4),
    )
    db_session.add(company)
    db_session.commit()
    assert company.pe == 44.95
    assert company.con_pb is None          # BSE genuinely returns None here
    assert company.financials_source == "BSE"
