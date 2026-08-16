"""Phase 1 shared fixtures.

Every test here runs against a THROWAWAY in-memory database built with
`Base.metadata.create_all` -- the same schema production migrates to, plus
the ledger triggers and views the `after_create` hooks install (0008/0011
pattern). No test in this package touches the dev database, the network, or
any LLM.
"""
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app import models  # noqa: F401 -- registers every table on Base

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "phase1"
TESTCO_FILING = FIXTURE_DIR / "testco_filing.json"

# One frozen instant / date for the whole package: nothing under test may
# read a clock, so every timestamp in play is one a test supplied.
FIXTURE_NOW = datetime(2226, 2, 22, 2, 22, tzinfo=timezone.utc)
FIXTURE_TODAY = date(2226, 2, 22)


# V5 PHASE 3 closed the exposure-tag vocabulary (config/exposure_tags.yaml)
# and enforces it with a DATABASE TRIGGER, so `company_exposure` now refuses
# a tag that names nothing real. Phase 1's fixture tags name nothing real ON
# PURPOSE -- they belong to companies that do not exist -- so this package
# REGISTERS them explicitly, which is exactly the act Task 3.1 requires of
# anyone widening the vocabulary. They are registered with a `source` of
# "tests/phase1", so a production database's vocabulary and a tag a test
# invented remain distinguishable in the table itself
# (tests/phase3/test_no_fixture_data_reaches_production.py asserts a
# migrated database contains only the YAML rows).
FIXTURE_TAGS = (
    "input:fixture_foo", "input:fixture_bar", "input:fixture_big",
    "input:fixture_det", "input:fixture_fresh", "input:fixture_old",
    "input:fixture_malformed", "input:fixture_other", "input:fixture_x",
    "input:x",
) + tuple(f"input:fixture_{i}" for i in range(10))


@pytest.fixture()
def ledger_engine():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False},
        poolclass=StaticPool)
    Base.metadata.create_all(engine)
    _register_fixture_tags(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def _register_fixture_tags(engine) -> None:
    from app.ledger.exposure_tags import register_tags

    with engine.begin() as connection:
        register_tags(connection, FIXTURE_TAGS, source="tests/phase1")


@pytest.fixture()
def ledger_session(ledger_engine):
    session = sessionmaker(bind=ledger_engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def filing_fixture() -> dict:
    raw = json.loads(TESTCO_FILING.read_text(encoding="utf-8"))
    assert raw["_fixture"] is True
    return raw


def make_company(session, *, ticker: str, name: str, isin: str | None = None,
                 sector: str = "Fixture Sector", market_cap: float | None = None,
                 index_tier: str = "OTHER", market: str = "INDIA",
                 tradeability: str = "NORMAL"):
    """A companies row for a company that does not exist. Market caps here
    are repeated-digit placeholders, never a real figure."""
    from app.models import Company

    company = Company(ticker=ticker, name=name, isin=isin, sector=sector,
                      index_tier=index_tier, market_cap=market_cap,
                      market=market, tradeability=tradeability)
    session.add(company)
    session.flush()
    return company
