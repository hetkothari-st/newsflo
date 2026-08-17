"""THE FABRICATION GUARD, as tests (master context).

Phase 5 is the phase whose output LOOKS most like proof. A transmission
matrix full of CARs and a calibration model with a reported ECE are exactly
the artifacts that would make a hollow system look validated. So:

  * `transmission_empirical`, `divergence_review`, `regime_change` and
    `calibration_model` ship EMPTY, asserted after a real `upgrade head`;
  * every numeral-bearing fixture object is `_fixture`-marked;
  * no production module can reach the Phase 5 fixtures;
  * the deployed config files carry POLICY (thresholds somebody chose) and
    no company fact, no CAR, no fitted parameter.
"""
import json
from pathlib import Path

import pytest
import yaml
from sqlalchemy import text

from tests.phase5.conftest import BACKEND, code_lines

FIXTURES = Path(__file__).resolve().parent / "fixtures"
EMPIRICAL = BACKEND / "app" / "analysis" / "empirical"
CALIBRATION = BACKEND / "app" / "analysis" / "calibration"
SURPRISE = BACKEND / "app" / "analysis" / "surprise"
NEW_TABLES = ("transmission_empirical", "divergence_review", "regime_change",
              "calibration_model")


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


def test_no_production_module_can_reach_the_phase5_fixtures():
    for package in (EMPIRICAL, CALIBRATION, SURPRISE, BACKEND / "app" / "core"):
        for path in sorted(package.glob("*.py")):
            for number, line in code_lines(path):
                for needle in ("tests.phase5", "tests/phase5",
                               "car_hand_computed"):
                    assert needle not in line, f"{path.name}:{number} reaches {needle}"


def test_the_phase5_tables_ship_empty(phase5_session):
    for table in NEW_TABLES:
        assert phase5_session.execute(
            text(f"SELECT count(*) FROM {table}")).scalar() == 0


def test_a_migrated_database_ships_the_phase5_tables_empty(tmp_path):
    """After a full `upgrade head`, not merely after `create_all`."""
    import os
    import sqlite3
    import subprocess
    import sys

    db = tmp_path / "phase5.db"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND,
        env=dict(os.environ, DATABASE_URL=f"sqlite:///{db}"),
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

    connection = sqlite3.connect(db)
    try:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert set(NEW_TABLES) <= tables
        for table in NEW_TABLES:
            assert connection.execute(
                f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    finally:
        connection.close()


@pytest.mark.parametrize("name", ["empirical.yaml", "calibration.yaml",
                                  "surprise.yaml"])
def test_the_deployed_config_carries_policy_and_no_company_fact(name):
    import re

    raw = yaml.safe_load((BACKEND / "config" / name).read_text(encoding="utf-8"))
    flattened = json.dumps(raw).lower()
    for needle in ("isin", "ticker", "company_id", "median_car"):
        assert needle not in flattened, f"{name} carries {needle}"
    # Word-boundary, because "consensus" contains "nse" and a naive substring
    # check would have made this test a liar in one direction and useless in
    # the other.
    for needle in ("nse", "bse"):
        assert not re.search(rf"\b{needle}\b", flattened), f"{name} carries {needle}"
    assert "version" in raw


def test_the_calibration_config_ships_disabled():
    raw = yaml.safe_load(
        (BACKEND / "config" / "calibration.yaml").read_text(encoding="utf-8"))
    assert raw["enabled"] is False


def test_no_empirical_module_hardcodes_a_transmission_statistic():
    """The estimator computes; it does not remember. Any numeric literal in
    the study modules must be structural (an index, a window, 0 or 1) --
    every threshold comes from config/empirical.yaml."""
    import ast

    for name in ("event_study.py", "check.py"):
        path = EMPIRICAL / name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, float):
                assert node.value in (0.0, 0.5, 1.0, 2.0, 100.0), (
                    f"{name}:{node.lineno} hardcodes {node.value}; thresholds "
                    "belong in config/empirical.yaml")
