"""THE FABRICATION GUARD, as tests (master context).

Phase 2 computes on numbers. That makes it the phase where invented data
would do the most damage, so the constraints are checked rather than
promised:

  * every numeral-bearing fixture object is `_fixture`-marked;
  * no production module can reach the Phase 2 fixtures;
  * the sensitivity package WRITES NOTHING -- it reads the ledger and returns
    signals;
  * the production ledger tables stay empty;
  * `config/materiality.yaml` is policy: no company, no financial figure.
"""
import ast
import json
import re
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.phase2.conftest import code_lines

BACKEND = Path(__file__).resolve().parents[2]
SENSITIVITY = BACKEND / "app" / "analysis" / "sensitivity"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

LEDGER_TABLES = ("company_exposure", "company_segment", "company_financials",
                 "pass_through_curve", "company_modifier", "exposure_proposal")


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


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.json")),
                         ids=lambda p: p.name)
def test_every_numeric_fixture_object_is_marked(path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    for obj in _objects(raw):
        if _has_numeral(obj):
            assert obj.get("_fixture") is True, (
                f"{path.name}: an object carrying a numeral is not marked "
                f"_fixture: {sorted(obj)[:6]}")


def test_no_production_module_can_reach_the_phase2_fixtures():
    """A docstring may NAME the tests that constrain a module; executable
    code may not import them or read their files."""
    for root in ("app", "tools", "scripts"):
        for path in sorted((BACKEND / root).rglob("*.py")):
            for number, line in code_lines(path):
                for forbidden in ("tests.phase2", "tests/phase2",
                                  "worked_examples"):
                    assert forbidden not in line, f"{path}:{number}"


def test_the_sensitivity_package_writes_nothing():
    """It is a READER of the ledger. The only writer of `company_exposure` is
    the review console (Phase 1), and it stays that way."""
    # SQL in this repo is written with uppercase keywords, so this matches a
    # STATEMENT rather than any identifier that happens to spell one
    # (`parameters.update(...)` is a dict, not a write).
    writes = re.compile(
        r"\b(INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|"
        r"CREATE\s+(TABLE|TRIGGER|INDEX|VIEW|TEMP)|DROP\s+|ALTER\s+TABLE)")
    for path in sorted(SENSITIVITY.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for number, line in code_lines(path):
            assert not writes.search(line), f"{path.name}:{number}"
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in (
                    "add", "add_all", "commit", "flush", "merge", "delete"):
                value = node.value
                if isinstance(value, ast.Name) and value.id in ("session", "db"):
                    raise AssertionError(f"{path.name} writes: session.{node.attr}")


def test_the_ledger_tables_stay_empty_in_a_freshly_built_database(db_session):
    """Importing and exercising the engine must not seed anything."""
    import app.analysis.sensitivity.channels  # noqa: F401
    import app.analysis.sensitivity.engine  # noqa: F401
    import app.analysis.sensitivity.monte_carlo  # noqa: F401
    import app.analysis.sensitivity.params  # noqa: F401

    for table in LEDGER_TABLES:
        count = db_session.execute(text(f"SELECT count(*) FROM {table}")).scalar()
        assert count == 0, f"{table} has {count} rows in a fresh database"


def test_the_materiality_config_is_policy_not_data():
    import yaml

    path = BACKEND / "config" / "materiality.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    text_blob = path.read_text(encoding="utf-8")
    assert ".NS" not in text_blob and ".BO" not in text_blob
    assert "crore" not in text_blob.lower()
    assert set(raw) >= {"version", "buckets", "sign_consistency", "monte_carlo",
                        "band_width"}
    # No parameter VALUE lives here. The one section that names parameters at
    # all is `param_bounds`, and every entry there is a [0, 1] domain bound --
    # never a point estimate. A pass-through or hedge NUMBER in this file
    # would be exactly the invented coefficient the master context forbids.
    for name, bounds in (raw.get("param_bounds") or {}).items():
        assert bounds == [0.0, 1.0], f"{name}: {bounds} is not a domain bound"
    numeric_sections = {"buckets", "sign_consistency", "monte_carlo",
                        "band_width", "distribution", "evidence_grade_cap",
                        # grade caps keyed by company_exposure.measurement --
                        # a policy statement about what an unfiled share may
                        # claim, carrying letters, not values.
                        "exposure_measurement_grade_cap",
                        "unknown_modifier_state", "param_bounds", "version"}
    assert set(raw) == numeric_sections, (
        f"unreviewed section in materiality.yaml: {set(raw) - numeric_sections}")


def test_the_engine_never_reads_a_clock_for_a_computation():
    """`as_of` is always supplied by the caller, so a run is reproducible."""
    for path in sorted(SENSITIVITY.glob("*.py")):
        for number, line in code_lines(path):
            assert "datetime.now(" not in line, f"{path.name}:{number}"
            assert "date.today(" not in line, f"{path.name}:{number}"
            assert "time.time(" not in line, f"{path.name}:{number}"
