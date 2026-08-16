"""THE FABRICATION GUARD, as tests (master context).

Phase 3 is the phase whose whole job is FINDING more companies. That makes
it the phase where an invented mechanism edge or an invented coefficient
would do the most damage, because it would look like recall. So the
constraints are checked rather than promised:

  * every numeral-bearing fixture object is `_fixture`-marked;
  * no production module can reach the Phase 3 fixtures;
  * `mechanism_edge`, `io_coefficient` and `coverage_gap` ship EMPTY;
  * `valid_exposure_tag` is the ONE documented exception, and it contains
    exactly the YAML vocabulary and nothing else;
  * `config/exposure_tags.yaml` and `config/discovery.yaml` are policy: no
    company, no coefficient, no financial figure;
  * no Phase 3 module opens a socket or constructs an LLM client.
"""
import ast
import json
from pathlib import Path

import pytest
import yaml
from sqlalchemy import text

from tests.phase3.conftest import code_lines

BACKEND = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
COVERAGE_FIXTURES = BACKEND / "tests" / "coverage" / "fixtures"

PHASE3_PACKAGES = (
    BACKEND / "app" / "discovery",
    BACKEND / "app" / "graph",
    BACKEND / "app" / "graph" / "io_bootstrap",
    BACKEND / "app" / "analysis" / "empirical",
)

BANNED_NETWORK_MODULES = (
    "yfinance", "requests", "httpx", "urllib", "urllib3", "socket", "aiohttp",
    "ftplib", "telnetlib", "smtplib",
)
PROVIDER_MODULES = ("anthropic", "google", "groq", "openai")


def _phase3_modules():
    for package in PHASE3_PACKAGES:
        yield from sorted(package.glob("*.py"))
    yield BACKEND / "app" / "ledger" / "exposure_tags.py"
    yield BACKEND / "app" / "ledger" / "edge_review.py"


def _objects(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _objects(value)
    elif isinstance(node, list):
        for value in node:
            yield from _objects(value)


def _has_numeral(obj: dict) -> bool:
    return any(isinstance(v, (int, float)) and not isinstance(v, bool)
               for v in obj.values())


@pytest.mark.parametrize(
    "path",
    sorted(FIXTURES.glob("*.json")) + sorted(COVERAGE_FIXTURES.glob("*.json")),
    ids=lambda p: p.name)
def test_every_numeric_fixture_object_is_marked(path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    for obj in _objects(raw):
        if _has_numeral(obj):
            assert obj.get("_fixture") is True, (
                f"{path.name}: an object carrying a numeral is not marked "
                f"_fixture: {sorted(obj)[:6]}")


@pytest.mark.parametrize("path", sorted(COVERAGE_FIXTURES.glob("*.yaml")),
                         ids=lambda p: p.name)
def test_every_numeric_coverage_fixture_object_is_marked(path):
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    for obj in _objects(raw):
        if _has_numeral(obj):
            assert obj.get("_fixture") is True, (
                f"{path.name}: an object carrying a numeral is not marked "
                f"_fixture: {sorted(obj)[:6]}")


def test_no_production_module_can_reach_the_phase3_fixtures():
    for path in _phase3_modules():
        for number, line in code_lines(path):
            for needle in ("tests.phase3", "tests/phase3", "tests.coverage",
                           "tests/coverage", "leontief_toy",
                           "expected_ripple_map", "synthetic_universe"):
                assert needle not in line, f"{path.name}:{number} reaches {needle}"


def test_the_ripple_tables_ship_empty(ripple_session):
    for table in ("mechanism_edge", "io_coefficient", "coverage_gap"):
        assert ripple_session.execute(
            text(f"SELECT count(*) FROM {table}")).scalar() == 0


def test_the_vocabulary_table_holds_the_vocabulary_and_nothing_else(ripple_session):
    from app.ledger.exposure_tags import load_vocabulary

    rows = list(ripple_session.execute(text(
        "SELECT exposure_tag, source FROM valid_exposure_tag")))
    assert {row[0] for row in rows} == set(load_vocabulary().tags)
    assert {row[1] for row in rows} == {"config/exposure_tags.yaml"}


def test_no_phase3_module_imports_anything_that_opens_a_socket():
    for path in _phase3_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                root = name.split(".")[0]
                assert root not in BANNED_NETWORK_MODULES, (
                    f"{path.name} imports {name}")


def test_no_phase3_module_imports_an_llm_provider():
    for path in _phase3_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert name.split(".")[0] not in PROVIDER_MODULES, (
                    f"{path.name} imports the provider module {name}: "
                    "discovery is a query, not a recollection")


def test_no_phase3_module_names_a_model():
    for path in _phase3_modules():
        for number, line in code_lines(path):
            lowered = line.lower()
            for needle in ("claude-", "gpt-4", "gemini-", "llama-"):
                assert needle not in lowered, f"{path.name}:{number} names a model"


def test_discovery_config_is_policy_not_data():
    raw = yaml.safe_load(
        (BACKEND / "config" / "discovery.yaml").read_text(encoding="utf-8"))
    assert set(raw) <= {"version", "distance_thresholds",
                        "max_candidates_per_event", "peer_closure_min_members",
                        "peer_closure_threshold", "max_depth",
                        "modelled_shock_variables"}
    for variable in raw["modelled_shock_variables"]:
        assert isinstance(variable, str) and variable.isupper()


def test_the_discovery_package_writes_nothing(ripple_session):
    """Discovery READS the ledger and the graph. It writes no row anywhere --
    a candidate is a value, not a record."""
    import re

    write = re.compile(r"\b(INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM)\b",
                       re.IGNORECASE)
    for path in sorted((BACKEND / "app" / "discovery").glob("*.py")):
        for number, line in code_lines(path):
            assert not write.search(line), f"{path.name}:{number} writes"
