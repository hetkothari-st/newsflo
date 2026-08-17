"""The fabrication guard, applied to the phase that measures the system.

Master context: "Fixtures used for tests must live under `tests/fixtures/`
and every numeric value in them must carry a `_fixture: true` marker. A test
asserting no fixture data reaches production tables must exist."

Phase 7 is the phase where a fabricated number would be most damaging and
least visible, because its outputs are numbers ABOUT US. So this file checks
the whole chain: the fixtures are marked, no production module can read them,
the eval package writes nothing anywhere, and the gate thresholds in
`config/shipping_gates.yaml` are policy rather than data.
"""
import json
from pathlib import Path

import pytest

from tests.phase7.conftest import (
    BACKEND, code_lines, imported_modules, package_sources,
)

FIXTURES = BACKEND / "tests" / "fixtures" / "phase7"
EVAL_PACKAGE = BACKEND / "eval"


def _numeral_bearing(value) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, list):
        return any(_numeral_bearing(item) for item in value)
    if isinstance(value, dict):
        return any(_numeral_bearing(item) for key, item in value.items()
                   if not str(key).startswith("_"))
    return False


def _walk(node, path="root"):
    """Every dict that carries a numeral must be marked, recursively."""
    problems = []
    if isinstance(node, dict):
        if _numeral_bearing(node) and node.get("_fixture") is not True:
            problems.append(path)
        for key, value in node.items():
            problems.extend(_walk(value, f"{path}.{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            problems.extend(_walk(value, f"{path}[{index}]"))
    return problems


@pytest.mark.parametrize("name", sorted(p.name for p in FIXTURES.glob("*.json")))
def test_every_numeral_bearing_object_is_marked_as_a_fixture(name):
    raw = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert raw.get("_fixture") is True, name
    assert _walk(raw) == [], (name, _walk(raw))


@pytest.mark.parametrize("name", sorted(p.name for p in FIXTURES.glob("*.json")))
def test_no_fixture_carries_a_real_ticker(name):
    """Every company reference in a Phase 7 fixture is FIX*. Putting invented
    economics behind a real ticker is the fabrication the master context
    forbids, and it is the one that looks most like real work."""
    text = (FIXTURES / name).read_text(encoding="utf-8")
    for token in ("RELIANCE", "TCS", "INFY", "HDFC", "IOC", "BPCL", "HPCL",
                  "ONGC", "SBIN", "ITC"):
        assert token not in text.upper(), (name, token)


def test_no_production_module_reads_a_phase_seven_fixture():
    for path in package_sources(BACKEND / "app") + package_sources(EVAL_PACKAGE):
        source = path.read_text(encoding="utf-8")
        assert "fixtures/phase7" not in source, path
        assert "tests.phase7" not in source, path


def test_the_eval_package_writes_to_no_table():
    banned = ("INSERT INTO", "UPDATE ", "DELETE FROM", "session.add",
              "sa.insert", "sa.update", "sa.delete")
    offenders = []
    for path in package_sources(EVAL_PACKAGE):
        for number, line in code_lines(path):
            for token in banned:
                if token.lower() in line.lower():
                    offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, offenders


def test_the_eval_package_never_imports_the_fixture_helpers():
    for path in package_sources(EVAL_PACKAGE):
        modules = imported_modules(path)
        assert not any(m.startswith("tests") for m in modules), path


def test_the_shipping_gate_config_holds_policy_not_data():
    """Thresholds are choices the owner makes. A company, a ticker or a
    financial figure in this file would mean a measurement had been baked
    into the gate."""
    from eval.shipping_gates import GATES_PATH

    text = Path(GATES_PATH).read_text(encoding="utf-8")
    for token in ("ticker", "isin", "crore", "company_id", "RELIANCE"):
        assert token.lower() not in text.lower(), token


def test_the_eval_package_holds_no_unnamed_threshold():
    """Every gate number lives in `config/shipping_gates.yaml`, so a
    threshold cannot drift between the file and the code.

    A fractional literal is allowed in exactly one shape: bound to a
    MODULE-LEVEL NAMED CONSTANT, where a reader can see what it means and a
    reviewer can see it change. `SUITE_PASSED = 1.0` / `SUITE_FAILED = 0.0`
    are the two points of a boolean domain, not a bar anybody chose; the bar
    for those gates is `== 1.0` in the YAML like every other one. What stays
    banned is the thing this test exists for: a bare fraction buried mid-
    expression, which is how a threshold nobody agreed to gets shipped.

    `test_the_gate_thresholds_match_the_spec_table` is the other half: every
    gate bar is pinned to the config, so a code constant cannot become one.
    """
    import re

    allowed_files = {EVAL_PACKAGE / "cost_ledger.py", EVAL_PACKAGE / "metrics.py"}
    named_constant = re.compile(r"^[A-Z][A-Z0-9_]* = [-+]?\d*\.?\d+$")
    # Deliberately `0.x` only, as it has been since this guard was written: a
    # fraction is what a threshold looks like. Widening it to every decimal
    # would flag "DATA_GAPS section 9.4" inside a refusal message and teach
    # the next person to disable the check.
    fraction = re.compile(r"(?<![\w.])0\.\d+")

    offenders = []
    for path in package_sources(EVAL_PACKAGE):
        if path in allowed_files:
            continue
        for number, line in code_lines(path):
            if named_constant.match(line.strip()):
                continue
            if fraction.search(line):
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, offenders


def test_the_named_constant_exemption_does_not_swallow_a_buried_threshold():
    """The self-test for the rule above: a bare fraction inside an expression
    must still be caught, or the exemption has quietly disabled the guard."""
    import re

    named_constant = re.compile(r"^[A-Z][A-Z0-9_]* = [-+]?\d*\.?\d+$")
    fraction = re.compile(r"(?<![\w.])0\.\d+")

    def flagged(line: str) -> bool:
        return not named_constant.match(line.strip()) and bool(fraction.search(line))

    assert flagged("    if value > 0.95:")
    assert flagged("    return ratio <= 0.10")
    assert flagged("SUITE_FAILED = 0.0  # a trailing comment defeats the shape")
    assert not flagged("SUITE_FAILED = 0.0")
    assert not flagged('        "unmeasurable (DATA_GAPS section 9.4)."')


def test_no_row_was_written_by_importing_the_eval_package(phase7_engine):
    import sqlalchemy as sa

    import eval.harness  # noqa: F401
    import eval.metrics  # noqa: F401
    import eval.monitoring  # noqa: F401
    import eval.shipping_gates  # noqa: F401

    with phase7_engine.connect() as conn:
        for table in ("eval_event", "eval_label", "company_impact", "signal",
                      "company_exposure"):
            assert conn.execute(
                sa.text(f"SELECT COUNT(*) FROM {table}")).scalar() == 0, table


def test_the_baselines_directory_carries_no_invented_baseline():
    from eval.shipping_gates import BASELINE_PATH

    directory = Path(BASELINE_PATH).parent
    assert directory.exists(), "the baselines directory should exist and be empty"
    assert sorted(p.name for p in directory.iterdir()) == ["README.md"], (
        "a baseline file appeared -- if a corpus was really scored, say so in "
        "DATA_GAPS section 11; if not, it is an invented measurement")
