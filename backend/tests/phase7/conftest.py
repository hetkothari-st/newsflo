"""Phase 7 shared fixtures -- the evaluation harness's own test bed.

THIS PHASE MEASURES THE SYSTEM, so it is the phase where a fabricated number
does the most damage: a metric is a sentence about how good we are, and a
plausible one reads exactly like a true one. Three disciplines follow from
that and every one of them is a test in this package:

1. **The corpus stays EMPTY.** Nothing here writes a label, an event or an
   adjudication into a real database. Every corpus-shaped test either runs
   against a THROWAWAY in-memory eval schema seeded from a `_fixture`-marked
   JSON, or skips with a named reason (`NEWSFLO_EVAL_CORPUS_DB` unset).
2. **A rate with no denominator is None, never 0.0 and never 1.0.** A harness
   that reports 100% precision over zero events is worse than a harness that
   reports nothing, and the empty-corpus refusal itself is tested here.
3. **Zero LLM calls, zero network.** The two V5 stages that would call a model
   (the falsifier's checklist and the firewall's stage-2 judge) take INJECTED
   clients; this package only ever hands them scripted objects, and the
   `CallLedger` that counts calls is the same object the cost-cascade gate
   reads.

NOTHING HERE READS A CLOCK. Every timestamp in play is one a test supplied.
"""
import ast
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app import models  # noqa: F401 -- registers every table on Base

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
FIXTURE_DIR = BACKEND / "tests" / "fixtures" / "phase7"

# One frozen instant for the whole package.
FIXTURE_NOW = datetime(2228, 4, 4, 4, 44, tzinfo=timezone.utc)
FIXTURE_TODAY = date(2228, 4, 4)

#: Set this to a SQLAlchemy URL holding a LABELED Gate Zero corpus to make the
#: corpus-dependent tests run for real. Unset (the deployed state) they SKIP
#: with a named reason -- they never pass vacuously over zero events.
CORPUS_DB_ENV = "NEWSFLO_EVAL_CORPUS_DB"

SKIP_REASON = (
    f"no labeled corpus: {CORPUS_DB_ENV} is unset. The Gate Zero corpus ships "
    f"EMPTY (DATA_GAPS.md sections 1 and 11) and this assertion is about a "
    f"corpus, so it is SKIPPED rather than evaluated over zero events."
)


def corpus_url() -> str | None:
    return os.environ.get(CORPUS_DB_ENV) or None


requires_corpus = pytest.mark.skipif(corpus_url() is None, reason=SKIP_REASON)


def load_fixture(name: str) -> dict:
    raw = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    assert raw["_fixture"] is True, f"{name} is not marked as a fixture"
    return raw


class ScriptedClient:
    """The whole LLM seam, in twelve lines (Phase 6's shape, unchanged).

    `generate(prompt) -> str`, returning the next canned response and
    recording every prompt. A client that runs out RAISES rather than
    repeating an answer -- an accidental second call must not silently reuse
    the first one, which is exactly the bug a cache-hit test could hide.
    """

    def __init__(self, *responses: str, repeat: bool = False):
        self.responses = list(responses)
        self.repeat = repeat
        self.prompts: list[str] = []
        self.calls = 0

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        self.calls += 1
        if not self.responses:
            raise AssertionError(
                "the caller called generate() more times than this test "
                "scripted responses for")
        if self.repeat and len(self.responses) == 1:
            return self.responses[0]
        return self.responses.pop(0)


@pytest.fixture()
def phase7_engine():
    """An in-memory database carrying BOTH schemas: the product tables and
    Session 0's eval corpus (which hangs off its own MetaData, so
    `create_all` does not touch it)."""
    from app.eval.schema import create_eval_tables

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False},
        poolclass=StaticPool)
    Base.metadata.create_all(engine)
    create_eval_tables(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def phase7_session(phase7_engine):
    session = sessionmaker(bind=phase7_engine)()
    try:
        yield session
    finally:
        session.close()


def seed_corpus(engine, raw: dict) -> None:
    """Load a `_fixture`-marked corpus into a THROWAWAY eval schema.

    Uses Session 0's own `app.eval.store` writers so a fixture corpus cannot
    have a shape the real importer would refuse. Nothing here touches a real
    database: the only engines passed in are `:memory:`.
    """
    from app.eval import store

    assert str(engine.url) .startswith("sqlite:///:memory:") or ":memory:" in str(engine.url), (
        "seed_corpus refuses any engine that is not in-memory -- the Gate Zero "
        "corpus must stay empty")
    with engine.begin() as conn:
        for event in raw["events"]:
            store.upsert_event(conn, event_id=event["event_id"],
                               stratum=event["stratum"],
                               article_ref=event["article_ref"],
                               notes=event.get("notes"))
            for label in event.get("labels", []):
                store.upsert_label(
                    conn, event_id=event["event_id"],
                    company_ref=label["company_ref"], labeler=label["labeler"],
                    expected_tier=label["expected_tier"],
                    expected_direction=label.get("expected_direction"),
                    expected_mechanism=label.get("expected_mechanism"),
                    expected_materiality=label.get("expected_materiality"),
                    label=label.get("label"), rationale=label.get("rationale"),
                    labeled_at=FIXTURE_NOW)
            for entry in event.get("event_labels", []):
                store.upsert_event_label(
                    conn, event_id=event["event_id"], labeler=entry["labeler"],
                    ripple_families=entry.get("ripple_families", []),
                    rationale=entry.get("rationale"), labeled_at=FIXTURE_NOW)
            for entry in event.get("adjudications", []):
                store.upsert_adjudication(
                    conn, event_id=event["event_id"],
                    company_ref=entry["company_ref"],
                    resolution=entry["resolution"],
                    resolved_by=entry.get("resolved_by"),
                    resolved_note=entry.get("resolved_note"),
                    resolved_at=FIXTURE_NOW)


def seed_companies(engine, companies) -> None:
    """Minimal `companies` rows so the harness can resolve a label's ticker
    and report per SECTOR. Fixture tickers only (`FIX...`)."""
    with engine.begin() as conn:
        for entry in companies:
            company = {k: v for k, v in entry.items() if not k.startswith("_")}
            assert str(company["ticker"]).startswith("FIX"), (
                "phase 7 fixtures use FIX* tickers only -- a real ticker in a "
                "fixture is the fabrication the master context forbids")
            conn.execute(sa.text(
                "INSERT INTO companies (id, name, ticker, sector, sub_sector, "
                "index_tier) VALUES (:id, :name, :ticker, :sector, "
                ":sub_sector, 'fixture_tier')"), company)


# ---------------------------------------------------------------------------
# source scanning (Phase 6's helpers, unchanged in behaviour)
# ---------------------------------------------------------------------------

def code_lines(path: Path) -> list[tuple[int, str]]:
    """A module's EXECUTABLE lines: comments and docstrings removed, so a
    docstring can never be what makes a scan pass."""
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
    return sorted(p for p in package.rglob("*.py") if "__pycache__" not in p.parts)


def imported_modules(path: Path) -> set[str]:
    """Every module this file imports, as an ABSOLUTE dotted name, so a lazy
    or relative import cannot hide."""
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
