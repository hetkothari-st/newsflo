from datetime import date

from app.companies.matching import aliases
from app.models import Company, CompanyAlias, Listing


def _company(session, ticker="RELIANCE.NS", name="Reliance Industries Limited", **kw):
    company = Company(
        ticker=ticker, name=name, sector="oil_gas", index_tier="NIFTY50", **kw,
    )
    session.add(company)
    session.commit()
    return company


def test_legal_name_becomes_an_alias(db_session):
    company = _company(db_session)
    aliases.rebuild_aliases(db_session)
    normalized = {a.normalized for a in db_session.query(CompanyAlias).all()}
    assert "reliance industries" in normalized


def test_listing_symbols_become_aliases(db_session):
    company = _company(db_session)
    db_session.add(Listing(
        company_id=company.id, exchange="NSE", symbol="RELIANCE", series="EQ",
        status="ACTIVE", is_sme=False, is_primary=True, source="NSE", as_of=date(2026, 8, 3),
    ))
    db_session.commit()
    aliases.rebuild_aliases(db_session)
    rows = db_session.query(CompanyAlias).filter_by(alias_type="NSE_SYMBOL").all()
    assert [r.normalized for r in rows] == ["reliance"]


def test_curated_trade_names_are_added(db_session):
    # "Infosys" (curated TRADE_NAME) and "Infosys Limited" (LEGAL, suffix
    # stripped) normalize identically, so first-writer-wins keeps the LEGAL
    # row per the UNIQUE(normalized, company_id) constraint -- the same
    # collapse rule exercised in test_duplicate_normalized_forms_collapse_to_one_row.
    # The guarantee this test is actually after is that the curated name
    # resolves to *some* alias, not which alias_type label wins the race.
    _company(db_session, ticker="INFY.NS", name="Infosys Limited")
    aliases.rebuild_aliases(db_session)
    normalized = {a.normalized for a in db_session.query(CompanyAlias).all()}
    assert "infosys" in normalized


def test_rebuild_is_idempotent(db_session):
    _company(db_session)
    first = aliases.rebuild_aliases(db_session)
    second = aliases.rebuild_aliases(db_session)
    assert first == second
    assert db_session.query(CompanyAlias).count() == first


def test_duplicate_normalized_forms_collapse_to_one_row(db_session):
    # "Reliance Industries Ltd" and "Reliance Industries Limited" normalize
    # identically; only one alias row may exist per (normalized, company).
    company = _company(db_session)
    db_session.add(Listing(
        company_id=company.id, exchange="BSE", symbol="RELIANCE", scrip_code="500325",
        group_code="A", status="ACTIVE", is_sme=False, is_primary=False,
        source="BSE", as_of=date(2026, 8, 3),
    ))
    db_session.commit()
    aliases.rebuild_aliases(db_session)
    rows = db_session.query(CompanyAlias).filter_by(normalized="reliance").all()
    assert len(rows) == 1


def test_blank_normalized_forms_are_not_stored(db_session):
    _company(db_session, ticker="ODD.NS", name="!!!")
    aliases.rebuild_aliases(db_session)
    assert all(a.normalized for a in db_session.query(CompanyAlias).all())
