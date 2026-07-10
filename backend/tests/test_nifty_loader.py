from app.companies.nifty_loader import load_nifty_indices
from app.models import Company, CompanyIndexMembership


def test_load_nifty_indices_creates_companies_and_memberships(db_session):
    load_nifty_indices(db_session)

    reliance = db_session.query(Company).filter_by(ticker="RELIANCE.NS").one()
    assert reliance.index_tier == "NIFTY50"
    assert reliance.isin == "INE002A01018"
    assert reliance.sector == "oil_gas"

    memberships = {
        m.index_code
        for m in db_session.query(CompanyIndexMembership).filter_by(company_id=reliance.id).all()
    }
    assert "NIFTY50" in memberships
    assert "NIFTY100" in memberships
    assert "NIFTY500" in memberships
    assert "NIFTYINFRA" in memberships


def test_load_nifty_indices_tags_extra_companies_as_other(db_session):
    load_nifty_indices(db_session)

    psb = db_session.query(Company).filter_by(ticker="PSB.NS").one()
    assert psb.index_tier == "OTHER"
    memberships = {
        m.index_code
        for m in db_session.query(CompanyIndexMembership).filter_by(company_id=psb.id).all()
    }
    assert memberships == {"NIFTYPSUBANK"}


def test_load_nifty_indices_is_idempotent(db_session):
    first = load_nifty_indices(db_session)
    total_after_first = db_session.query(CompanyIndexMembership).count()

    second = load_nifty_indices(db_session)
    total_after_second = db_session.query(CompanyIndexMembership).count()

    assert first["companies"] == second["companies"]
    assert second["memberships"] == 0  # every membership already existed
    assert total_after_first == total_after_second
    assert db_session.query(Company).filter_by(ticker="RELIANCE.NS").count() == 1
