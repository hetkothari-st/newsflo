"""Phase 5 shared fixtures.

Every test in this package runs against a THROWAWAY in-memory database built
with `Base.metadata.create_all` -- never the dev database, never the network,
never an LLM. Phase 5 is the phase that could most easily fabricate: an
event-study table full of plausible CARs and a calibration model with a
plausible ECE would both LOOK like the product working.

So the whole phase runs on obviously-fake inputs and ships EMPTY tables:

  * there is no price history in this repo. `SyntheticHistory` implements the
    `ReturnHistory` protocol with arithmetic a human can check on paper
    (fixtures/car_hand_computed.json, arithmetic documented in
    .superpowers/sdd/2026-08-17-v5-session0/phase5-estimator-design.md §4);
  * there is no labeled corpus. The isotonic/ECE/Brier math is proved on
    `_fixture`-marked labels and the resulting model can never be activated;
  * `transmission_empirical`, `divergence_review`, `regime_change` and
    `calibration_model` ship empty -- asserted after a full `upgrade head` by
    `test_no_fixture_data_reaches_production.py`.

NOTHING HERE READS A CLOCK. Every timestamp in play is one a test supplied.
"""
import ast
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app import models  # noqa: F401 -- registers every table on Base

BACKEND = Path(__file__).resolve().parents[2]
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

FIXTURE_NOW = datetime(2226, 3, 3, 3, 33, tzinfo=timezone.utc)
FIXTURE_TODAY = date(2226, 3, 3)
FIXTURE_EVENT_DAY = date(2226, 3, 3)

FIXTURE_EVENT_ID = "fixture:phase5-shock-1"
FIXTURE_ANALYSIS_VERSION = "v5:fixture:phase5:cafebabe"
FIXTURE_COMPANY_ID = 9501
FIXTURE_TICKER = "FIXEMP"
FIXTURE_VARIABLE = "fixture_variable"
FIXTURE_BENCHMARK = "fixture_sector_index"


def load_fixture(name: str) -> dict:
    raw = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    assert raw["_fixture"] is True
    return raw


@pytest.fixture()
def phase5_engine():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False},
        poolclass=StaticPool)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def phase5_session(phase5_engine):
    session = sessionmaker(bind=phase5_engine)()
    try:
        yield session
    finally:
        session.close()


def code_lines(path: Path) -> list[tuple[int, str]]:
    """A module's EXECUTABLE lines: comments and docstrings removed.

    The scans in this package assert what the code DOES. A docstring saying
    "this module never fetches a price" must not be what makes the test pass.
    """
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


def imported_modules(path: Path) -> set[str]:
    """Every module this file imports -- at module level or inside a function
    (a lazy import is still an import)."""
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules
