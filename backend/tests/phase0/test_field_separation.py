"""TASK 0.7 tests -- four separate fields, never merged.

docs/v5/01_PHASE_0_canonical_truth.md TESTS/test_field_separation.py:
  * lint: no source file contains a template/f-string joining a directness
    literal with a tier literal
  * CompanyImpact serializer emits four distinct fields

Master context invariant 4: `directness`, `graph_distance`,
`discovery_source` and `publication_tier` are four separate fields -- never
concatenated, never merged, never inferred from one another.

SCOPE (controller adaptation): the lint runs REPO-WIDE but is a ratchet --
`BASELINE` freezes the pre-existing occurrences so NEW code cannot add one.
The existing V4 serving path is deliberately not rewritten in Phase 0 (the
adaptation keeps `alert_companies` byte-untouched); the ratchet is what
stops the collapse from being reintroduced on the V5 surface.
"""
import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / "backend"

SCAN_ROOTS = (
    BACKEND / "app",
    BACKEND / "tools",
    BACKEND / "scripts",
    REPO / "frontend" / "src",
)

# Canonical values of the two vocabularies. A single string literal holding
# one of each is the "DIRECT EXPOSURE · RIPPLE" collapse in the making.
DIRECTNESS_VALUES = ("DIRECT", "INDIRECT", "REMOTE")
TIER_VALUES = ("PRIMARY", "SECONDARY_RIPPLE", "MACRO_CONTEXT",
               "primary", "secondary_ripple", "macro_context")

# Identifier fragments that name each vocabulary, for the interpolation
# check (an f-string or template literal splicing one of each together).
DIRECTNESS_NAMES = ("directness", "causal_directness")
TIER_NAMES = ("tier", "display_tier", "publication_tier")

# Pre-existing occurrences, frozen. This tuple may SHRINK, never grow.
#
# frontend/src/v4/FeedV4.tsx renders `{directnessWord(row.causal_directness)}
# · {tierWord(row.publication_tier)}` -- the one place in the repo where the
# two vocabularies meet in a single line of output. It is BASELINED, not
# deleted, because:
#   * the two values come from two SEPARATE backend fields
#     (`causal_directness`, `publication_tier`); nothing is merged, inferred
#     or stored joined -- invariant 4 is about the FIELDS, and it holds,
#   * three frontend tests pin that rendering (spec §28 Task 9), and the
#     controller adaptation is explicit that the existing serving path stays
#     byte-untouched in Phase 0,
#   * the V5 surface (`company_impact` + its serializer) keeps the four
#     fields apart, which is what the ratchet exists to protect going
#     forward.
# Recorded as a deviation in the Phase 0 report.
BASELINE: tuple[str, ...] = (
    "frontend/src/v4/FeedV4.tsx:373",
)


def _literal_joins_both(value: str) -> bool:
    has_directness = any(re.search(rf"\b{v}\b", value) for v in DIRECTNESS_VALUES)
    has_tier = any(re.search(rf"\b{v}\b", value) for v in TIER_VALUES)
    return has_directness and has_tier


def _rel(path: Path) -> str:
    try:
        return path.relative_to(REPO).as_posix()
    except ValueError:      # a tmp_path file in the self-test
        return path.as_posix()


def _python_violations(path: Path) -> list[str]:
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
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node in docstrings:
                continue
            if _literal_joins_both(node.value):
                found.append(f"{_rel(path)}:{node.lineno}: literal joins both "
                             f"vocabularies: {node.value[:70]!r}")
        elif isinstance(node, ast.JoinedStr):
            names = {n.id.lower() for n in ast.walk(node) if isinstance(n, ast.Name)}
            names |= {n.attr.lower() for n in ast.walk(node) if isinstance(n, ast.Attribute)}
            if (any(d in names for d in DIRECTNESS_NAMES)
                    and any(t in names for t in TIER_NAMES)):
                found.append(f"{_rel(path)}:{node.lineno}: f-string interpolates "
                             "a directness and a tier into one string")
    return found


_TS_STRING = re.compile(r"""(['"`])(?:\\.|(?!\1).)*\1""", re.DOTALL)
_TS_LINE_COMMENT = re.compile(r"//[^\n]*")
_TS_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
# `{directnessWord(row.causal_directness)} · {tierWord(row.publication_tier)}`
# and any other same-expression join of the two vocabularies.
_TS_JOIN = re.compile(
    r"(directness.{0,120}?[·–—+,\-].{0,120}?tier"
    r"|tier.{0,120}?[·–—+,\-].{0,120}?directness)",
    re.IGNORECASE)


def _strip_ts_comments(source: str) -> str:
    """Blank out comments, keeping line numbers intact. A prose comment that
    quotes the collapsed label is documentation, not a rendered string."""
    def blank(match):
        return re.sub(r"[^\n]", " ", match.group(0))
    return _TS_LINE_COMMENT.sub(blank, _TS_BLOCK_COMMENT.sub(blank, source))


def _ts_violations(path: Path) -> list[str]:
    source = _strip_ts_comments(path.read_text(encoding="utf-8"))
    found = []
    for match in _TS_STRING.finditer(source):
        value = match.group(0)
        line = source.count("\n", 0, match.start()) + 1
        if _literal_joins_both(value):
            found.append(f"{_rel(path)}:{line}: literal joins both vocabularies")
        elif value.startswith("`") and "${" in value:
            lowered = value.lower()
            if (any(d in lowered for d in DIRECTNESS_NAMES)
                    and any(t in lowered for t in TIER_NAMES)):
                found.append(f"{_rel(path)}:{line}: template literal "
                             "interpolates a directness and a tier")
    for index, text_line in enumerate(source.splitlines(), start=1):
        if _TS_JOIN.search(text_line):
            found.append(f"{_rel(path)}:{index}: expression joins a directness "
                         "and a tier into one rendered string")
    return found


def _scan() -> list[str]:
    violations = []
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.suffix == ".py":
                violations.extend(_python_violations(path))
            elif path.suffix in (".ts", ".tsx"):
                if path.name.endswith(".test.ts") or path.name.endswith(".test.tsx"):
                    continue
                violations.extend(_ts_violations(path))
    return violations


def _location(violation: str) -> str:
    """'path:line' out of 'path:line: message'. Compared EXACTLY (fix round
    1, finding: a `startswith` baseline of '…FeedV4.tsx:373' would also have
    exempted lines 3730-3739 of that file)."""
    path, line, _ = violation.split(":", 2)
    return f"{path}:{line}"


def test_no_source_file_concatenates_a_directness_with_a_tier():
    baseline = set(BASELINE)
    unexpected = [v for v in _scan() if _location(v) not in baseline]
    assert not unexpected, (
        "new directness/tier concatenation introduced:\n  " +
        "\n  ".join(unexpected))


def test_the_baseline_is_matched_exactly_not_by_prefix():
    """A prefix match would silently exempt every line whose number STARTS
    with a baselined one (373 exempting 3730-3739)."""
    assert _location("frontend/src/v4/FeedV4.tsx:373: msg") == \
           "frontend/src/v4/FeedV4.tsx:373"
    assert _location("frontend/src/v4/FeedV4.tsx:3730: msg") not in set(BASELINE)


def test_the_lint_actually_catches_a_violation(tmp_path):
    """A ratchet nobody has proven fires is not a ratchet."""
    bad = tmp_path / "bad.py"
    bad.write_text('LABEL = "DIRECT exposure -- SECONDARY_RIPPLE"\n', encoding="utf-8")
    assert _python_violations(bad)

    worse = tmp_path / "worse.py"
    worse.write_text(
        "def f(directness, publication_tier):\n"
        "    return f'{directness} - {publication_tier}'\n", encoding="utf-8")
    assert _python_violations(worse)


def test_company_impact_serializer_emits_four_distinct_fields():
    from app.core.reducer import reduce_company_impact, serialize_company_impact
    from tests.phase0 import fixtures

    impact = reduce_company_impact(
        fixtures.signals(fixtures.PRIMARY_COMPANY_ID), fixtures.reducer_config())
    payload = serialize_company_impact(impact)

    for field in ("directness", "graph_distance", "discovery_source",
                  "publication_tier"):
        assert field in payload, f"{field} missing from the serializer output"

    assert payload["directness"] in DIRECTNESS_VALUES
    assert isinstance(payload["graph_distance"], int)
    assert payload["discovery_source"] in (
        "MENTION", "MECHANISM", "SUPPLY_CHAIN", "PEER_CLOSURE")
    assert payload["publication_tier"] in (
        "PRIMARY", "SECONDARY_RIPPLE", "REJECTED")

    # No SINGLE emitted value may carry two vocabularies at once -- that is
    # what "never concatenated" means at the serializer boundary.
    for field in ("directness", "discovery_source", "publication_tier"):
        assert not _literal_joins_both(str(payload[field])), field

    # ...and the four are four separate keys, not one nested blob.
    assert payload["directness"] != payload["publication_tier"]


def test_company_impact_table_has_the_four_columns_plus_needs_reanalysis():
    from sqlalchemy import create_engine, inspect

    from app import models  # noqa: F401
    from app.db import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    columns = {c["name"] for c in inspect(engine).get_columns("company_impact")}
    assert {"directness", "graph_distance", "discovery_source",
            "publication_tier", "needs_reanalysis"} <= columns


def test_the_backfill_script_exists_and_documents_its_mapping():
    script = BACKEND / "scripts" / "backfill_company_impact.py"
    assert script.exists()
    source = script.read_text(encoding="utf-8")
    # The documented V4 -> V5 mapping, and the do-not-guess rule.
    for needle in ("causal_directness", "causal_distance", "discovery_source",
                   "display_tier", "needs_reanalysis"):
        assert needle in source
    assert "__main__" in source, (
        "the backfill must not run on import -- it is committed, not executed")


@pytest.mark.parametrize("v4_value,expected", [
    ("ARTICLE_MENTION", "MENTION"),
    ("MECHANISM_MAPPING", "MECHANISM"),
    ("EXPOSURE_RULE", None),
    ("RIPPLE_DISCOVERY", None),
    ("", None),
    (None, None),
])
def test_unmappable_discovery_sources_become_null_not_a_guess(v4_value, expected):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "backfill_company_impact",
        BACKEND / "scripts" / "backfill_company_impact.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.map_discovery_source(v4_value) == expected


def test_no_production_module_imports_the_fixtures():
    """The Phase 0 fixture file carries invented numbers. Nothing under
    app/ may read it."""
    for path in sorted((BACKEND / "app").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        assert "tests.phase0" not in source
        assert "crude_shock_event" not in source


def test_every_numeral_bearing_fixture_object_is_marked():
    """Master context: 'every numeric value in [fixtures] must carry a
    "_fixture": true marker.'"""
    from tests.phase0.fixtures import load_raw

    def check(node, path="$"):
        if isinstance(node, dict):
            has_number = any(isinstance(v, (int, float)) and not isinstance(v, bool)
                             for v in node.values())
            if has_number:
                assert node.get("_fixture") is True, f"unmarked numerals at {path}"
            for key, value in node.items():
                check(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                check(value, f"{path}[{index}]")

    check(load_raw())
