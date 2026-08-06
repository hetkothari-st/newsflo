"""Supply links from rating rationales.

Spec: docs/superpowers/specs/2026-08-06-supply-links-rating-rationales-
design.md. The load-bearing tests are the refusals: no evidence quote ->
no row; no exact name match -> NULL counterparty_company_id; no stored
links -> byte-identical prompt; LLM returns nothing -> zero ripple rows.
"""
from datetime import date, datetime, timezone

from app import config
from app.models import Company, SupplyLink

AS_OF = date(2026, 8, 6)


def _company(session, ticker, name, sector="other"):
    company = Company(ticker=ticker, name=name, sector=sector, index_tier="OTHER")
    session.add(company)
    session.flush()
    return company


def test_supply_link_table_exists(db_session):
    company = _company(db_session, "RELIANCE.NS", "Reliance Industries")
    db_session.add(SupplyLink(
        company_id=company.id, relation="CUSTOMER",
        counterparty_name="Indian Oil Corporation", counterparty_company_id=None,
        evidence="derives a material share of revenue from Indian Oil Corporation",
        source_url="https://www.bseindia.com/xml-data/corpfiling/AttachLive/x.pdf",
        source_agency="CRISIL", as_of=AS_OF,
        extracted_at=datetime.now(timezone.utc),
    ))
    db_session.commit()
    got = db_session.query(SupplyLink).one()
    assert got.relation == "CUSTOMER"
    assert got.counterparty_company_id is None


def test_supply_caps_live_in_config():
    assert config.SUPPLY_LINK_MAX_PER_RELATION == 3
    assert config.SUPPLY_PROMPT_MAX_LINES == 8
    assert config.SUPPLY_PROMPT_MAX_CHARS == 700
