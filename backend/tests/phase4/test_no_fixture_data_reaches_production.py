"""THE FABRICATION GUARD, as tests (master context).

Phase 4 is the phase whose whole job is to encode POLICY PARAMETERS -- levy
rates, thresholds, administered ceilings, subsidy splits. Those are precisely
the numbers a language model can produce fluently and wrongly, and a wrong
one would be invisible: it would just make the output look sophisticated.

So the constraints are checked rather than promised:

  * `policy_modifier` and `policy_state` ship EMPTY;
  * the DEPLOYED registry carries no parameter value at all;
  * an entry whose owner is the placeholder can never be materialised;
  * every numeral-bearing fixture object is `_fixture`-marked;
  * no production module can reach the Phase 4 fixtures.
"""
import ast
import json
from pathlib import Path

import pytest
import yaml
from sqlalchemy import text

from tests.phase4.conftest import FIXTURE_TODAY, code_lines

BACKEND = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
POLICY = BACKEND / "app" / "analysis" / "policy"
DEPLOYED_REGISTRY = BACKEND / "config" / "policy_modifiers.yaml"


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


def test_no_production_module_can_reach_the_phase4_fixtures():
    for path in sorted(POLICY.glob("*.py")) + [
            BACKEND / "app" / "analysis" / "sensitivity" / "horizons.py",
            BACKEND / "app" / "analysis" / "sensitivity" / "engine.py",
            BACKEND / "app" / "analysis" / "sensitivity" / "channels.py",
            BACKEND / "app" / "core" / "reducer.py",
            BACKEND / "app" / "core" / "impact_writer.py"]:
        for number, line in code_lines(path):
            for needle in ("tests.phase4", "tests/phase4", "omc_horizons",
                           "oil_india_incident", "policy_modifiers.json"):
                assert needle not in line, f"{path.name}:{number} reaches {needle}"


def test_the_policy_tables_ship_empty(policy_session):
    for table in ("policy_modifier", "policy_state"):
        assert policy_session.execute(
            text(f"SELECT count(*) FROM {table}")).scalar() == 0


def test_a_migrated_database_ships_the_policy_tables_empty(tmp_path):
    """After a full `upgrade head`, not merely after `create_all`.

    Run in a SUBPROCESS with DATABASE_URL set, the same way
    `tests/test_migrations.py` does it -- an in-process alembic run inherits
    this session's already-imported app modules and their `after_create`
    hooks, and would be testing something else.
    """
    import os
    import sqlite3
    import subprocess
    import sys

    db = tmp_path / "policy.db"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND,
        env=dict(os.environ, DATABASE_URL=f"sqlite:///{db}"),
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

    connection = sqlite3.connect(db)
    try:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"policy_modifier", "policy_state"} <= tables
        for table in ("policy_modifier", "policy_state"):
            assert connection.execute(
                f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    finally:
        connection.close()


def test_the_deployed_registry_carries_no_numeral_outside_structure():
    """A version string, a review interval nobody has chosen (null) and a
    structural date are allowed. A rate, a threshold, a ceiling, a fraction
    or a share is not."""
    raw = yaml.safe_load(DEPLOYED_REGISTRY.read_text(encoding="utf-8"))
    for entry in raw["modifiers"]:
        for name, value in entry["parameters"].items():
            assert name == "_required" or value is None, (
                f"{entry['id']}.{name} carries a value")
        assert entry["review_interval_days"] is None
        assert entry["last_reviewed_at"] is None


def test_materialisation_refuses_every_scaffold_entry(policy_session):
    from app.analysis.policy.registry import load_registry, materialise

    written = materialise(policy_session, load_registry())
    assert written == 0
    assert policy_session.execute(
        text("SELECT count(*) FROM policy_modifier")).scalar() == 0


def test_materialisation_writes_an_owner_signed_entry(policy_session):
    """The refusal is a rule about COMPLETENESS, not a broken loader."""
    from app.analysis.policy.registry import (
        PolicyRegistry, materialise, modifier_from_mapping,
    )

    entry = modifier_from_mapping({
        "modifier_id": "FIXTURE_SIGNED", "applies_to_tag": "realization:fixture_product",
        "jurisdiction": "FIXTURELAND", "modifier_type": "SUBSIDY_SHARE",
        "parameters": {"retained_fraction": 0.25},
        "effective_from": "2200-01-01", "effective_to": None,
        "source_url": "https://fixture.invalid/signed",
        "owner": "human:fixture-owner", "review_interval_days": 30,
        "last_reviewed_at": "2226-02-22"})
    assert materialise(policy_session, PolicyRegistry((entry,))) == 1
    assert policy_session.execute(
        text("SELECT owner FROM policy_modifier")).scalar() == "human:fixture-owner"


def test_the_engine_over_an_empty_policy_table_abstains_from_modifying(policy_session):
    """Truncate everything and the pipeline degrades correctly: no modifier is
    applied, and nothing is invented to replace one."""
    from app.analysis.policy.registry import registry_from_db

    registry = registry_from_db(policy_session)
    assert registry.entries == ()
    assert registry.active_for("revenue:crude_realization", FIXTURE_TODAY) == ()


@pytest.mark.parametrize("name", ["transfer.py", "transforms.py"])
def test_the_transfer_layer_hardcodes_no_parameter_value(name):
    """A "reasonable default" for a capture fraction is the exact failure the
    master context names.

    SCOPE. The two modules that COMPUTE with parameters are scanned; a levy
    rate could only ever hide in one of them. `registry.py` and `state.py`
    carry structural integers (a path depth, a cache size) and are covered by
    the no-value assertions on the deployed YAML above instead.
    """
    allowed = {0, 1, 0.0, 1.0}
    tree = ast.parse((POLICY / name).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(
                node.value, (int, float)) and not isinstance(node.value, bool):
            assert node.value in allowed, (
                f"{name}:{node.lineno} carries the literal {node.value!r}; a "
                "policy parameter must come from the registry, never from the "
                "code")


def test_the_registry_names_an_owner_for_every_missing_parameter():
    """DoD: "`DATA_GAPS.md` lists every modifier awaiting real parameter
    values and names its owner"."""
    from app.analysis.policy.registry import load_registry

    gaps = (BACKEND.parent / "DATA_GAPS.md").read_text(encoding="utf-8")
    for entry in load_registry().awaiting_parameters():
        assert entry.modifier_id in gaps, (
            f"{entry.modifier_id} awaits parameters and is not in DATA_GAPS.md")
