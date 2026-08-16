"""Market isolation -- master context invariant 3.

docs/v5/01_PHASE_0_canonical_truth.md TESTS/test_market_isolation.py:
  * ast scan: newsflo/core/* imports nothing from newsflo/market/*
  * mutating market data for a fixture event leaves CompanyImpact
    byte-identical

Market price movement never influences fundamental direction, materiality,
evidence or tier. In this repo the market layer is `app/market/*`
(`measure.py`, `alert_measurement.py`, `intensity.py`, ...) and it writes
`price_at_analysis`, `return_1m`, `return_3m`, `excess_move_pct` onto the
V4 entry/row -- exactly the fields the signal adapter must refuse to read.
"""
import ast
import json
from pathlib import Path

from tests.phase0 import fixtures

CORE = Path(__file__).resolve().parents[2] / "app" / "core"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_no_module_under_app_core_imports_app_market():
    for path in sorted(CORE.glob("*.py")):
        offenders = {n for n in _imports(path)
                     if n == "app.market" or n.startswith("app.market.")}
        assert not offenders, f"app/core/{path.name} imports {sorted(offenders)}"


def _code_symbols(path: Path) -> set[str]:
    """Every identifier, attribute and non-docstring string literal in the
    file. Prose (docstrings, comments) is excluded on purpose: naming the
    market fields in a comment that says 'these must never be read' is the
    documentation, not the violation."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docstrings = {
        node.body[0].value
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef))
        and node.body and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    symbols = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            symbols.add(node.id)
        elif isinstance(node, ast.Attribute):
            symbols.add(node.attr)
        elif isinstance(node, ast.arg):
            symbols.add(node.arg)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node not in docstrings:
                symbols.add(node.value)
    return symbols


def test_no_module_under_app_core_reads_a_market_field():
    market_fields = ("price_at_analysis", "return_1m", "return_3m",
                     "excess_move_pct", "measurement_status")
    for path in sorted(CORE.glob("*.py")):
        symbols = _code_symbols(path)
        for field in market_fields:
            assert field not in symbols, (
                f"app/core/{path.name} reads the market field `{field}` -- "
                "price movement may never reach the fundamental record")


def test_mutating_market_data_leaves_company_impact_byte_identical():
    """The signal adapter is fed a V4 entry dict. Rewriting every market
    field on it -- including flipping the measured move to the opposite
    sign -- must not move a single byte of the canonical record."""
    from app.core.reducer import reduce_company_impact, serialize_company_impact
    from app.core.signal_adapters import signals_from_entry

    config = fixtures.reducer_config()
    entry = {
        "company_id": 9001, "ticker": "FIXCO1.NS",
        "economic_effect": "negative", "causal_distance": 1,
        "materiality_grade": "HIGH", "causal_directness": "DIRECT",
        "discovery_source_vocab": "ARTICLE_MENTION",
        "evidence_class": "COMPANY_FILING", "evidence_tier": "A",
        "gate_state": "DISPLAY_ELIGIBLE", "display_tier": "primary",
        "mechanism": "crude input cost",
        "causal_parent_type": "mechanism", "causal_parent_id": "crude_input_cost",
        "channels_json": json.dumps({
            "positive_channels": [], "negative_channels": ["input cost"],
            "net_direction": "negative"}),
        # --- market layer, must be ignored entirely ---------------------
        "price_at_analysis": 100.0, "return_1m": -0.05, "return_3m": 0.2,
        "excess_move_pct": -3.4, "measurement_status": "ok",
    }
    baseline = json.dumps(serialize_company_impact(reduce_company_impact(
        signals_from_entry(entry, event_id="fixture:market",
                           analysis_version="v3:fixture",
                           created_at=fixtures.FIXTURE_CREATED_AT), config)),
        sort_keys=True)

    moved = dict(entry, price_at_analysis=42.0, return_1m=0.9, return_3m=-0.9,
                 excess_move_pct=+9.9, measurement_status="no_data")
    after = json.dumps(serialize_company_impact(reduce_company_impact(
        signals_from_entry(moved, event_id="fixture:market",
                           analysis_version="v3:fixture",
                           created_at=fixtures.FIXTURE_CREATED_AT), config)),
        sort_keys=True)

    assert after == baseline
