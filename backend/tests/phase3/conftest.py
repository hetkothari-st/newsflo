"""Phase 3 shared fixtures.

Every test in this package runs against a THROWAWAY in-memory database built
with `Base.metadata.create_all` -- never the dev database, never the network,
never an LLM. Every company, exposure row, mechanism edge and price series a
test seeds is obviously fake and belongs to entities that do not exist.

THE PRECONDITION RULING (controller adaptation, R-V5-4). Phase 3's phase
file requires "a ledger with real rows for at least the top 3 priority
tags". There are none, in this repo or anywhere. So the discovery engine,
the IO bootstrap, the gap finder and the coverage harness are exercised
here EXCLUSIVELY on fixture data seeded into a test database, and no
data-dependent claim is made from it.

THE ONE PRODUCTION TABLE PHASE 3 POPULATES is `valid_exposure_tag`: the
closed vocabulary from `config/exposure_tags.yaml`, written by migration
0013 and by `models.py`'s `after_create` hook. It is CONTROLLED VOCABULARY,
not a claim about any company -- a tag name is a word this system is allowed
to use, not a fact about the world. Everything else (`mechanism_edge`,
`io_coefficient`, `coverage_gap`) ships EMPTY, asserted by
`test_no_fixture_data_reaches_production.py`.
"""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app import models  # noqa: F401 -- registers every table on Base

# One frozen instant / date for the whole package: nothing under test may
# read a clock, so every timestamp in play is one a test supplied.
FIXTURE_NOW = datetime(2227, 3, 3, 3, 33, tzinfo=timezone.utc)
FIXTURE_TODAY = date(2227, 3, 3)

# Real vocabulary tags (spec §6.1) -- these name economic exposures, not
# companies, so using the production spelling here is not fabrication.
TAG_CRUDE_DIRECT = "input:crude_direct"
TAG_PETCHEM = "input:crude_derivative_petchem"
TAG_RUBBER = "input:crude_derivative_rubber"
TAG_ATF = "input:atf"
TAG_FREIGHT = "input:freight_diesel"
TAG_PETCOKE = "input:fuel_furnace_pet_coke"
TAG_CRUDE_REALIZATION = "revenue:crude_realization"


@pytest.fixture()
def ripple_engine():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False},
        poolclass=StaticPool)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def ripple_session(ripple_engine):
    session = sessionmaker(bind=ripple_engine)()
    try:
        yield session
    finally:
        session.close()


def make_company(session, *, ticker: str, name: str, sector: str = "Fixture Sector",
                 sub_sector: str | None = None, market_cap: float | None = None,
                 isin: str | None = None):
    from app.models import Company

    company = Company(ticker=ticker, name=name, isin=isin, sector=sector,
                      sub_sector=sub_sector, index_tier="OTHER", market="INDIA",
                      market_cap=market_cap, tradeability="NORMAL")
    session.add(company)
    session.flush()
    return company


def seed_exposure(session, *, exposure_id: str, company_id: int, exposure_tag: str,
                  share_of_base: float, exposure_kind: str = "INPUT_COST",
                  base_value_inr: float = 1000.0, measurement: str = "FILED",
                  confidence: float = 0.1111, as_of_date: date = FIXTURE_TODAY,
                  freshness_days: int = 400, base_kind: str = "COGS"):
    """Insert one `company_exposure` row through the Phase 1 review capability.

    The table refuses a write from a connection that does not hold it, and
    (Phase 3) refuses a tag that is not in the closed vocabulary -- so a test
    cannot seed the ledger by accident, nor invent a tag by accident.
    """
    from app.ledger.review import review_session

    with review_session(session):
        session.execute(text(
            "INSERT INTO company_exposure (exposure_id, company_id, exposure_kind, "
            "exposure_tag, share_of_base, base_kind, base_value_inr, measurement, "
            "source_type, source_url, as_of_date, freshness_days, confidence, "
            "created_by, reviewed_by) VALUES (:exposure_id, :company_id, "
            ":exposure_kind, :exposure_tag, :share_of_base, :base_kind, "
            ":base_value_inr, :measurement, 'ANNUAL_REPORT', "
            "'https://fixture.invalid/ar', :as_of_date, :freshness_days, "
            ":confidence, 'ingest:fixture', 'human:fixture-reviewer')"), {
                "exposure_id": exposure_id, "company_id": company_id,
                "exposure_kind": exposure_kind, "exposure_tag": exposure_tag,
                "share_of_base": share_of_base, "base_kind": base_kind,
                "base_value_inr": base_value_inr, "measurement": measurement,
                "confidence": confidence, "as_of_date": as_of_date.isoformat(),
                "freshness_days": freshness_days})


def seed_edge(session, *, edge_id: str, from_node: str, to_node: str,
              exposure_tag: str, relationship_type: str = "INPUT_COST",
              distance: int = 1, derivation: str = "AUTHORED",
              reviewed_by: str | None = "human:fixture-reviewer",
              review_status: str = "APPROVED",
              confidence: float = 0.5, io_total_coeff: float | None = None,
              effective_from: date | None = None, effective_to: date | None = None):
    """Seed one `mechanism_edge`.

    `review_status` DEFAULTS TO APPROVED and is stated explicitly rather than
    inferred from `reviewed_by`. Inferring it would re-encode the exact
    conflation defect D2 names -- that a non-null reviewer name IS approval --
    inside the fixture layer, where it would then be invisible. A test that
    wants an unapproved row passes `review_status="PENDING"` and says so.

    Note that the default pair (APPROVED + a reviewer name) is what makes an
    edge walkable, so existing fixtures that expect traversal keep working
    without change. Callers passing `reviewed_by=None` get an APPROVED row
    with no signature, which `traverse.usable` still refuses -- correctly.
    """
    session.execute(text(
        "INSERT INTO mechanism_edge (edge_id, from_node, to_node, exposure_tag, "
        "relationship_type, distance, io_total_coeff, derivation, reviewed_by, "
        "review_status, confidence, effective_from, effective_to, source_url, "
        "created_at) VALUES "
        "(:edge_id, :from_node, :to_node, :exposure_tag, :relationship_type, "
        ":distance, :io_total_coeff, :derivation, :reviewed_by, :review_status, "
        ":confidence, :effective_from, :effective_to, "
        "'https://fixture.invalid/edge', :created_at)"), {
            "edge_id": edge_id, "from_node": from_node, "to_node": to_node,
            "exposure_tag": exposure_tag, "relationship_type": relationship_type,
            "distance": distance, "io_total_coeff": io_total_coeff,
            "derivation": derivation, "reviewed_by": reviewed_by,
            "review_status": review_status,
            "confidence": confidence,
            "effective_from": effective_from.isoformat() if effective_from else None,
            "effective_to": effective_to.isoformat() if effective_to else None,
            "created_at": FIXTURE_NOW.isoformat()})


def seed_supply_link(session, *, company_id: int, counterparty_company_id: int,
                     relation: str = "SUPPLIER", counterparty_name: str = "FIXTURE CO"):
    session.execute(text(
        "INSERT INTO supply_links (company_id, relation, counterparty_name, "
        "counterparty_company_id, evidence, source_url, source_agency, as_of, "
        "extracted_at) VALUES (:company_id, :relation, :counterparty_name, "
        ":counterparty_company_id, 'fixture evidence quote', "
        "'https://fixture.invalid/rationale', 'FIXTURE RATINGS', :as_of, "
        ":extracted_at)"), {
            "company_id": company_id, "relation": relation,
            "counterparty_name": counterparty_name,
            "counterparty_company_id": counterparty_company_id,
            "as_of": FIXTURE_TODAY.isoformat(),
            "extracted_at": FIXTURE_NOW.isoformat()})


def code_lines(path):
    """A module's EXECUTABLE lines: comments and docstrings removed.

    The scans in this package assert things about what the code DOES ("this
    package never opens a socket"). A docstring saying so must not be what
    makes the test pass.
    """
    import ast

    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    skip: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None) or []
        if body and isinstance(body[0], ast.Expr) and isinstance(
                body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            first = body[0].value
            skip.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    out = []
    for number, line in enumerate(source.splitlines(), 1):
        if number in skip or line.strip().startswith("#") or not line.strip():
            continue
        out.append((number, line))
    return out
