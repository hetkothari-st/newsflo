"""Phase 6 shared fixtures.

Every test in this package runs against a THROWAWAY in-memory database and a
SCRIPTED client -- never the dev database, never the network, never a real
LLM. Phase 6 adds the one stage in V5 whose job is to argue, so it is also
the phase where a fabricated argument would be hardest to see: an objection
is a sentence about a company, and a plausible one reads exactly like a true
one.

So the falsifier here NEVER constructs a client (`Falsifier(client=...)` is
the only way to build one) and every response it parses is a string a test
wrote. `_no_real_anthropic_client` in the root conftest is still in force on
top of that.

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
REPO = BACKEND.parent
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"

# One frozen instant for the whole package.
FIXTURE_NOW = datetime(2228, 4, 4, 4, 44, tzinfo=timezone.utc)
FIXTURE_TODAY = date(2228, 4, 4)

FIXTURE_EVENT_ID = "fixture:phase6-crude-shock"
FIXTURE_ANALYSIS_VERSION = "v5:fixture:phase6:deadbeef"

# The generator's identity, as a test states it. Both halves are obviously
# fake: the point of the model-discipline record is that the two identities
# are COMPARED, not that either of them is a real model name.
FIXTURE_GENERATOR_PROVIDER = "fixture-provider-a"
FIXTURE_GENERATOR_MODEL = "fixture-generator-model"
FIXTURE_GENERATOR_LINEAGE = "fixture-generator-lineage-v1"
FIXTURE_FALSIFIER_PROVIDER = "fixture-provider-b"
FIXTURE_FALSIFIER_MODEL = "fixture-falsifier-model"


def load_fixture(name: str) -> dict:
    raw = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    assert raw["_fixture"] is True
    return raw


class ScriptedClient:
    """The whole LLM seam, in twelve lines.

    `generate(prompt) -> str`, returning the next canned response. It records
    every prompt it was handed so a test can assert what the falsifier asked
    (and, in `test_falsifier.py`, that the record set really was in context).
    A client that runs out of responses RAISES rather than repeating one --
    an accidental second call must not silently reuse the first answer.
    """

    def __init__(self, *responses: str):
        self.responses = list(responses)
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError(
                "the falsifier called generate() more times than this test "
                "scripted responses for")
        return self.responses.pop(0)


@pytest.fixture()
def phase6_engine():
    from app.eval.schema import create_eval_tables

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False},
        poolclass=StaticPool)
    Base.metadata.create_all(engine)
    # The eval corpus hangs off its OWN MetaData (Session 0's ruling), so it
    # is created explicitly rather than by create_all.
    create_eval_tables(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def phase6_session(phase6_engine):
    session = sessionmaker(bind=phase6_engine)()
    try:
        yield session
    finally:
        session.close()


def code_lines(path: Path) -> list[tuple[int, str]]:
    """A module's EXECUTABLE lines: comments and docstrings removed.

    The scans in this package assert what the code DOES. A docstring saying
    "the falsifier never rebuts itself" must not be what makes the test pass.
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


def package_sources(package: Path) -> list[Path]:
    """Every module in a package INCLUDING subpackages."""
    return sorted(p for p in package.rglob("*.py")
                  if "__pycache__" not in p.parts)


def imported_modules(path: Path) -> set[str]:
    """Every module this file imports, as an ABSOLUTE dotted name.

    Same shape as Phase 5's (relative imports resolved from the file's
    location under `backend/`), so a lazy or relative import cannot hide.
    """
    source = path.read_text(encoding="utf-8")
    package = _package_of(path)
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module:
                    modules.add(node.module)
                continue
            base = _relative_base(package, node.level)
            resolved = f"{base}.{node.module}" if node.module else base
            if resolved:
                modules.add(resolved.strip("."))
    return modules


def _package_of(path: Path) -> str:
    try:
        relative = path.resolve().relative_to(BACKEND)
    except ValueError:                                # pragma: no cover
        return ""
    return ".".join(relative.parts[:-1])


def _relative_base(package: str, level: int) -> str:
    parts = package.split(".") if package else []
    trimmed = parts[:len(parts) - (level - 1)] if level > 1 else parts
    return ".".join(trimmed)
