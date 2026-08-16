"""Phase 4 shared fixtures.

Every test in this package runs against a THROWAWAY in-memory database built
with `Base.metadata.create_all` -- never the dev database, never the network,
never an LLM. Every modifier, state, exposure and curve a test seeds is
`_fixture`-marked in the JSON it comes from and belongs to a jurisdiction and
a company that do not exist.

THE PRECONDITION RULING (controller adaptation, binding). Phase 4's registry
needs levy rates, ceilings, capture fractions and administered formulas.
NOBODY HAS SUPPLIED ONE, and the phase file's own DO NOT forbids me from
producing them from my knowledge. So:

  * `config/policy_modifiers.yaml` carries STRUCTURE ONLY -- every parameter
    value is null and every `owner` is the placeholder `OWNER-REQUIRED`,
    which the loader REFUSES to activate. Nothing in it can ever be applied;
  * the six transfer functions are verified HERE, on the obviously fake
    parameters in `fixtures/policy_modifiers.json` (threshold 100 in no unit,
    capture fraction one half, cap 7.5, retained fraction one quarter);
  * `policy_modifier` and `policy_state` SHIP EMPTY in production, asserted
    by `test_no_fixture_data_reaches_production.py`.

FIXTURE TAGS. Phase 3 closed the exposure-tag vocabulary at the database.
Phase 4's fixture tags name nothing real ON PURPOSE, so this package
registers them in the in-memory test database only, with a `source` that
keeps them distinguishable from the deployed vocabulary -- exactly the way
tests/phase2 does it.
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
POLICY_FIXTURES = FIXTURE_DIR / "policy_modifiers.json"
OMC_FIXTURE = FIXTURE_DIR / "omc_horizons.json"
OIL_INDIA_FIXTURE = FIXTURE_DIR / "oil_india_incident.json"

# One frozen instant / date for the whole package: nothing under test may
# read a clock, so every timestamp in play is one a test supplied.
FIXTURE_NOW = datetime(2226, 2, 22, 2, 22, tzinfo=timezone.utc)
FIXTURE_TODAY = date(2226, 2, 22)

FIXTURE_EVENT_ID = "fixture:phase4-shock-1"
FIXTURE_ANALYSIS_VERSION = "v5:fixture:phase4:deadbeef"

FIXTURE_TAGS = (
    "realization:fixture_product",
    "realization:fixture_capped",
    "realization:fixture_state_dependent",
    "realization:fixture_shared",
    "realization:fixture_formula",
    "input:fixture_regional",
    "realization:fixture_crude",
    "realization:fixture_marketing_margin",
    "realization:fixture_inventory_stock",
    "realization:fixture_structural_volume",
)


def load_policy_fixtures() -> dict:
    raw = json.loads(POLICY_FIXTURES.read_text(encoding="utf-8"))
    assert raw["_fixture"] is True
    return raw


def fixture_modifier(modifier_id: str) -> dict:
    for entry in load_policy_fixtures()["modifiers"]:
        if entry["modifier_id"] == modifier_id:
            return entry
    raise KeyError(modifier_id)


def fixture_state(state_key: str) -> dict:
    for entry in load_policy_fixtures()["states"]:
        if entry["state_key"] == state_key:
            return entry
    raise KeyError(state_key)


def load_json_fixture(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["_fixture"] is True
    return raw


@pytest.fixture()
def policy_engine():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False},
        poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        for tag in FIXTURE_TAGS:
            connection.execute(text(
                "INSERT OR IGNORE INTO valid_exposure_tag (exposure_tag, source) "
                "VALUES (:tag, 'tests/phase4:fixture')"), {"tag": tag})
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def policy_session(policy_engine):
    session = sessionmaker(bind=policy_engine)()
    try:
        yield session
    finally:
        session.close()


# --- registry / state construction from the fixture JSON --------------------

def fixture_registry(*modifier_ids: str):
    """A `PolicyRegistry` over the named FIXTURE modifiers only."""
    from app.analysis.policy.registry import PolicyRegistry, modifier_from_mapping

    wanted = set(modifier_ids) or None
    entries = [modifier_from_mapping(raw)
               for raw in load_policy_fixtures()["modifiers"]
               if wanted is None or raw["modifier_id"] in wanted]
    return PolicyRegistry(tuple(entries))


def fixture_policy_state(*state_keys: str):
    """A `PolicyStateStore` over the named FIXTURE states only."""
    from app.analysis.policy.state import PolicyStateStore, state_from_mapping

    wanted = set(state_keys) or None
    entries = [state_from_mapping(raw)
               for raw in load_policy_fixtures()["states"]
               if wanted is None or raw["state_key"] in wanted]
    return PolicyStateStore(tuple(entries))


# --- channel construction ---------------------------------------------------

def make_exposure(*, exposure_id: str = "fixture-exposure-1", company_id: int = 9401,
                  exposure_kind: str = "REVENUE_REALIZATION",
                  exposure_tag: str = "realization:fixture_product",
                  base_value_inr: float = 1_000_000_000.0,
                  share_of_base: float = 1.0,
                  segment_ownership_fraction: float = 1.0):
    from app.analysis.sensitivity.channels import ExposureView

    return ExposureView(
        exposure_id=exposure_id, company_id=company_id,
        exposure_kind=exposure_kind, exposure_tag=exposure_tag,
        base_value_inr=base_value_inr, share_of_base=share_of_base,
        segment_ownership_fraction=segment_ownership_fraction,
        evidence_ids=(exposure_id,))


def make_shock(*, shock_id: str = "fixture-shock-1",
               exposure_tag: str = "realization:fixture_product",
               delta_pct: float = 0.1, horizon_days: int = 90,
               level_before: float | None = None, level_after: float | None = None,
               mechanism_id: str | None = "fixture:mechanism:1"):
    from app.analysis.sensitivity.channels import Shock

    return Shock(shock_id=shock_id, exposure_tag=exposure_tag,
                 delta_pct=delta_pct, horizon_days=horizon_days,
                 mechanism_id=mechanism_id, level_before=level_before,
                 level_after=level_after)


def make_params(**points):
    """`{name: ParamDist}` banded by the DEPLOYED policy -- a test must never
    carry its own copy of a band width the product ships."""
    from app.analysis.sensitivity.params import dist_for

    return {name: dist_for(name, float(point), source)
            for name, (point, source) in points.items()}


def realization_channel(*, elasticity: float = 1.0, capture: float = 0.0,
                        source: str = "FILED", **kwargs):
    """One REVENUE_REALIZATION channel, sized on fixture numbers."""
    from app.analysis.sensitivity.channels import compute_channel

    exposure = make_exposure(**{k: v for k, v in kwargs.items()
                                if k in ("exposure_id", "company_id", "exposure_tag",
                                         "base_value_inr", "share_of_base",
                                         "segment_ownership_fraction")})
    shock = make_shock(**{k: v for k, v in kwargs.items()
                          if k in ("shock_id", "exposure_tag", "delta_pct",
                                   "horizon_days", "level_before", "level_after")})
    params = make_params(realization_elasticity=(elasticity, source),
                         regulatory_capture_fraction=(capture, source))
    return compute_channel(exposure, shock, params, shock.horizon_days)


# --- database seeding -------------------------------------------------------

def make_company(session, *, ticker: str, name: str, sector: str = "Fixture Sector",
                 isin: str | None = None):
    from app.models import Company

    company = Company(ticker=ticker, name=name, isin=isin, sector=sector,
                      index_tier="OTHER", market="INDIA", tradeability="NORMAL")
    session.add(company)
    session.flush()
    return company


def seed_exposure(session, *, exposure_id: str, company_id: int, exposure_tag: str,
                  exposure_kind: str, base_value_inr: float, share_of_base: float,
                  measurement: str = "FILED", as_of_date: date = FIXTURE_TODAY,
                  freshness_days: int = 400, base_kind: str = "REVENUE"):
    from app.ledger.review import review_session

    session.execute(text(
        "INSERT OR IGNORE INTO valid_exposure_tag (exposure_tag, source) "
        "VALUES (:tag, 'tests/phase4:fixture')"), {"tag": exposure_tag})
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

    The scans in this package assert things about what the code DOES ("no
    module here imports a provider"). A docstring saying so must not be what
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
