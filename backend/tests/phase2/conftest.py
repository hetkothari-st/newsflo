"""Phase 2 shared fixtures.

Every test in this package runs against a THROWAWAY in-memory database built
with `Base.metadata.create_all` -- never the dev database, never the network,
never an LLM. Every exposure, modifier and curve row a test seeds is
`_fixture`-marked in the JSON it comes from and belongs to a company that
does not exist.

THE PRECONDITION RULING (controller adaptation, R-V5-4). Phase 2's phase
file requires a populated Tier 1 ledger. Ledger population is human work and
has not happened, so the sensitivity engine is exercised here EXCLUSIVELY on
obviously fake fixture data seeded into a test database, and no data-dependent
claim is made from it. `test_no_fixture_data_reaches_production.py` asserts
the production tables stay empty and that no module under `app/` can reach
these fixtures.
"""
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app import models  # noqa: F401 -- registers every table on Base

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
WORKED_EXAMPLES = FIXTURE_DIR / "worked_examples.json"

# One frozen instant / date for the whole package: nothing under test may
# read a clock, so every timestamp in play is one a test supplied.
FIXTURE_NOW = datetime(2226, 2, 22, 2, 22, tzinfo=timezone.utc)
FIXTURE_TODAY = date(2226, 2, 22)

FIXTURE_EVENT_ID = "fixture:phase2-shock-1"
FIXTURE_ANALYSIS_VERSION = "v5:fixture:phase2:deadbeef"


def load_worked_examples() -> dict:
    raw = json.loads(WORKED_EXAMPLES.read_text(encoding="utf-8"))
    assert raw["_fixture"] is True
    return raw


def cases() -> list[dict]:
    return load_worked_examples()["cases"]


def case_by_id(case_id: str) -> dict:
    for case in cases():
        if case["case_id"] == case_id:
            return case
    raise KeyError(case_id)


def exposure_from_case(case: dict):
    from app.analysis.sensitivity.channels import ExposureView

    raw = case["exposure"]
    return ExposureView(
        exposure_id=raw["exposure_id"],
        company_id=raw["company_id"],
        exposure_kind=raw["exposure_kind"],
        exposure_tag=raw["exposure_tag"],
        base_value_inr=float(raw["base_value_inr"]),
        share_of_base=float(raw["share_of_base"]),
        segment_ownership_fraction=float(raw["segment_ownership_fraction"]),
        evidence_ids=(raw["exposure_id"],),
    )


def shock_from_case(case: dict):
    from app.analysis.sensitivity.channels import Shock

    raw = case["shock"]
    return Shock(
        shock_id=raw["shock_id"],
        exposure_tag=raw["exposure_tag"],
        delta_pct=float(raw["delta_pct"]),
        horizon_days=int(raw["horizon_days"]),
        mechanism_id="fixture:mechanism:1",
    )


def params_from_case(case: dict) -> dict:
    """The case's parameters as ParamDists, banded by the DEPLOYED policy in
    config/materiality.yaml -- a test must never carry its own copy of a
    threshold the product ships."""
    from app.analysis.sensitivity.params import dist_for

    return {
        name: dist_for(name, float(raw["point"]), raw["source"])
        for name, raw in (case.get("params") or {}).items()
    }


# V5 PHASE 3 closed the exposure-tag vocabulary (config/exposure_tags.yaml)
# and enforces it with a DATABASE TRIGGER, so `company_exposure` now refuses
# a tag that names nothing real. Phase 2's fixture tags name nothing real ON
# PURPOSE, so this package REGISTERS them explicitly -- the act Task 3.1
# requires of anyone widening the vocabulary -- with a `source` that keeps
# them distinguishable from the deployed vocabulary in the table itself.
FIXTURE_TAGS = (
    "input_cost:fixture_input", "input_cost:fixture_missing",
    "realization:fixture_product", "demand:fixture_enduse",
    "fx:fixture_usd_receipts", "fx:fixture_usd_payments",
    "fx:fixture_subsidiary_ebitda", "rates:fixture_floating_debt",
    "regulatory:fixture_rule",
)


@pytest.fixture()
def sensitivity_engine():
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
        register_tags(connection, FIXTURE_TAGS, source="tests/phase2")


@pytest.fixture()
def sensitivity_session(sensitivity_engine):
    session = sessionmaker(bind=sensitivity_engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def worked_examples() -> dict:
    return load_worked_examples()


def make_company(session, *, ticker: str, name: str, sector: str = "Fixture Sector",
                 isin: str | None = None):
    from app.models import Company

    company = Company(ticker=ticker, name=name, isin=isin, sector=sector,
                      index_tier="OTHER", market="INDIA", tradeability="NORMAL")
    session.add(company)
    session.flush()
    return company


def register_fixture_tag(session, exposure_tag: str) -> None:
    """Make a FIXTURE tag writable in THIS test database.

    Phase 3 closed the exposure-tag vocabulary at the database (migration
    0013 populates `valid_exposure_tag` from `config/exposure_tags.yaml` and
    installs triggers that RAISE on anything else). Phase 2's fixtures use
    obviously fake tags on purpose -- `input_cost:fixture_input` names no
    real economic exposure and must never appear in the deployed vocabulary.

    So they are registered here, in the in-memory test database only, with a
    `source` that says exactly what they are. That is the mechanism Phase 3's
    own model docstring describes ("a tag some other caller registered, and
    is distinguishable as such"), it touches no Phase 3 file, and
    `config/exposure_tags.yaml` stays free of fixture words.
    """
    session.execute(text(
        "INSERT OR IGNORE INTO valid_exposure_tag (exposure_tag, source) "
        "VALUES (:tag, 'tests/phase2:fixture')"), {"tag": exposure_tag})


def seed_exposure(session, *, exposure_id: str, company_id: int, exposure_tag: str,
                  exposure_kind: str, base_value_inr: float, share_of_base: float,
                  measurement: str = "FILED", as_of_date: date = FIXTURE_TODAY,
                  freshness_days: int = 400, base_kind: str = "COGS"):
    """Insert one `company_exposure` row through the Phase 1 review capability.

    The table refuses a write from a connection that does not hold it, so a
    test cannot seed the ledger by accident -- it has to say so.
    """
    from app.ledger.review import review_session

    register_fixture_tag(session, exposure_tag)

    with review_session(session):
        session.execute(text(
            "INSERT INTO company_exposure (exposure_id, company_id, exposure_kind, "
            "exposure_tag, share_of_base, base_kind, base_value_inr, measurement, "
            "source_type, source_url, as_of_date, freshness_days, confidence, "
            "created_by, reviewed_by) VALUES (:exposure_id, :company_id, "
            ":exposure_kind, :exposure_tag, :share_of_base, :base_kind, "
            ":base_value_inr, :measurement, 'ANNUAL_REPORT', "
            "'https://fixture.invalid/testco-ar', :as_of_date, :freshness_days, "
            "0.1111, 'ingest:fixture', 'human:fixture-reviewer')"), {
                "exposure_id": exposure_id, "company_id": company_id,
                "exposure_kind": exposure_kind, "exposure_tag": exposure_tag,
                "share_of_base": share_of_base, "base_kind": base_kind,
                "base_value_inr": base_value_inr, "measurement": measurement,
                "as_of_date": as_of_date.isoformat(),
                "freshness_days": freshness_days})


def seed_modifier(session, *, modifier_id: str, company_id: int, applies_to_tag: str,
                  modifier_kind: str, parameters: dict,
                  effective_from: date = date(2226, 1, 1),
                  as_of_date: date = FIXTURE_TODAY):
    session.execute(text(
        "INSERT INTO company_modifier (modifier_id, company_id, modifier_kind, "
        "applies_to_tag, parameters, effective_from, source_url, as_of_date, "
        "confidence) VALUES (:modifier_id, :company_id, :modifier_kind, "
        ":applies_to_tag, :parameters, :effective_from, "
        "'https://fixture.invalid/testco-call', :as_of_date, 0.1111)"), {
            "modifier_id": modifier_id, "company_id": company_id,
            "modifier_kind": modifier_kind, "applies_to_tag": applies_to_tag,
            "parameters": json.dumps(parameters),
            "effective_from": effective_from.isoformat(),
            "as_of_date": as_of_date.isoformat()})


def seed_curve(session, *, curve_id: str, exposure_tag: str, points: list[dict],
               basis: str = "DISCLOSED_CALL", company_id: int | None = None,
               sector_id: str | None = None, as_of_date: date = FIXTURE_TODAY,
               reviewed_by: str | None = None):
    session.execute(text(
        "INSERT INTO pass_through_curve (curve_id, company_id, sector_id, "
        "exposure_tag, points, basis, as_of_date, reviewed_by) VALUES "
        "(:curve_id, :company_id, :sector_id, :exposure_tag, :points, :basis, "
        ":as_of_date, :reviewed_by)"), {
            "curve_id": curve_id, "company_id": company_id, "sector_id": sector_id,
            "exposure_tag": exposure_tag,
            "points": json.dumps([{"lag_days": p["lag_days"],
                                   "fraction": p["fraction"]} for p in points]),
            "basis": basis, "as_of_date": as_of_date.isoformat(),
            "reviewed_by": reviewed_by})


def seed_financials(session, *, company_id: int, ebitda_inr: float,
                    fiscal_period: str = "FY26Q1"):
    session.execute(text(
        "INSERT INTO company_financials (company_id, fiscal_period, ebitda_inr, "
        "source_url, as_of_date) VALUES (:company_id, :fiscal_period, :ebitda_inr, "
        "'https://fixture.invalid/testco-ar', :as_of_date)"), {
            "company_id": company_id, "fiscal_period": fiscal_period,
            "ebitda_inr": ebitda_inr, "as_of_date": FIXTURE_TODAY.isoformat()})


def code_lines(path: Path) -> list[tuple[int, str]]:
    """A module's EXECUTABLE lines: comments and docstrings removed.

    The scans in this package assert things about what the code DOES ("this
    package never writes", "this package never names a model"). A docstring
    saying "this package never writes" must not trip them -- otherwise the
    only way to pass the test is to stop explaining the rule.
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
