"""THE node-id transform lives in exactly two modules, and nowhere else.

`normalize.py` owns the transform; `knowledge.py` owns the raw/persisted
alias resolution built FROM it. Everything else must call those.

This is a SOURCE-LEVEL scan, the same shape as the phase6/phase7 fixture-
isolation tests, because the defect it guards is invisible at runtime: four
independent alias maps, three partial reimplementations of the transform and
two raw-keyed lookup tables had grown around one canonical writer, and every
one of them failed SILENTLY -- wrong or empty answer, no error, no log. A
runtime assertion cannot catch the fifth copy; only refusing to let it be
written can.

Three ban patterns, each precise enough to name the offender:

  1. an ALIAS MAP -- a dict keyed by `normalize_node_id(...)` -- outside
     `knowledge.py`;
  2. a REIMPLEMENTED TRANSFORM -- `.lower().replace(" ", "_")` applied to a
     single id-shaped value. A multi-placeholder f-string is exempt and is
     not a false negative: joining two values with a space and snaking the
     result builds a SEARCH HAYSTACK, and an id never contains a space, so
     that expression cannot be an id reconstruction;
  3. a PRIVATE ID NORMALIZER -- an UNQUALIFIED `_norm` / `_canonical`
     helper (or one that names the node/mechanism domain outright) whose
     body performs a case/space/strip transform.

     Name AND body must both match, and the name must be unqualified.
     A helper that names its own domain -- `_normalize_sector`,
     `_normalize_title`, `_normalize_geography` -- is declaring which
     vocabulary it belongs to, and those are real, separate domains
     (sector slugs, article titles, ticker refs). The exact defect this
     catches is the OPPOSITE: `_norm` and `_canonical`, bare, over strings
     that turned out to be node ids. `app.core.reducer._canonical`
     (a `json.dumps` canonicalizer -- a different meaning of the word)
     survives on the body test, and `eval.store.canonical_company_ref`
     (the TICKER domain, deliberately separate) is neither private nor
     unqualified.

`test_the_guard_fires_on_a_synthetic_violation` proves each detector still
detects; without it a scan that silently stopped matching would read exactly
like a clean tree.
"""
import ast
import re
from pathlib import Path

import pytest

from tests.phase6.conftest import BACKEND, code_lines

#: Everything that may hold an id today. `benchmark_impact_graph.py` sits at
#: the backend root rather than under a package, and it is one of the named
#: offenders, so it is swept explicitly.
SCAN_ROOTS = ("app", "eval", "scripts", "tools", "benchmarks")
EXTRA_FILES = ("benchmark_impact_graph.py",)

#: The two modules that ARE the single source.
EXEMPT = {
    BACKEND / "app" / "analysis" / "impact_graph" / "normalize.py",
    BACKEND / "app" / "analysis" / "impact_graph" / "knowledge.py",
}

# A dict literal keyed by the transform. The first alternative catches the
# multi-line form, where the `:` sits on a later line than the `{`.
#
# THE NEGATIVE LOOKAHEAD IS LOAD-BEARING. Without it this also matches an
# f-string PLACEHOLDER -- `f"{k} -> {normalize_node_id(k)}"` -- which is a
# print, not an alias map. Measured 2026-08-17: it fired on
# `scripts/probes/mechanism_family_closure.py:118`, a probe that prints the
# transform's output, and `scripts` is in SCAN_ROOTS by design so the false
# positive was reachable by any new script. A dict key is `...):` ; a
# placeholder is `...)}` -- that difference is the whole discriminator.
_ALIAS_MAP = re.compile(
    r"\{\s*normalize_node_id\s*\((?![^)]*\)\s*\})"
    r"|normalize_node_id\s*\([^)]*\)\s*:")
_SNAKE = re.compile(r"\.lower\(\)\s*\.replace\(\s*[\"'] [\"']\s*,\s*[\"']_[\"']\s*\)")
#: an f-string carrying TWO OR MORE placeholders -- a haystack, not an id
_HAYSTACK = re.compile(r"f[\"'][^\"']*\{[^\"']*\{")
#: unqualified: the helper does not say WHICH vocabulary it normalizes
_BARE_NORMALIZER = re.compile(r"^_(norm|normalise|normalize|canon|canonical|"
                              r"canonicalise|canonicalize)$")
#: or it names the node-id domain outright, which only these two modules may
_NODE_NORMALIZER = re.compile(r"^_(normali[sz]e|canonical|canonicali[sz]e)_"
                              r"(node|mechanism|parent|child|edge)")
_STRING_TRANSFORM = re.compile(r"\.(lower|upper|strip|replace)\(")


def _sources() -> list[Path]:
    paths: list[Path] = []
    for root in SCAN_ROOTS:
        base = BACKEND / root
        if base.is_dir():
            paths.extend(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)
    paths.extend(BACKEND / name for name in EXTRA_FILES)
    return sorted(p for p in paths if p.exists() and p not in EXEMPT)


def alias_map_violations(path: Path) -> list[str]:
    """A dict keyed by the transform is an alias map, and there is one."""
    out = []
    for number, line in code_lines(path):
        if _ALIAS_MAP.search(line):
            out.append(f"{path.name}:{number} builds an alias map over "
                       f"normalize_node_id -- call knowledge.resolve_mechanism_id")
    return out


def snake_reimplementation_violations(path: Path) -> list[str]:
    out = []
    for number, line in code_lines(path):
        match = _SNAKE.search(line)
        if not match:
            continue
        if _HAYSTACK.search(line[:match.start()]):
            continue                      # a search haystack, not an id
        out.append(f"{path.name}:{number} reimplements the node-id transform "
                   f"-- call normalize_node_id (or normalize.snake_node_id)")
    return out


def private_normalizer_violations(path: Path) -> list[str]:
    out = []
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not (_BARE_NORMALIZER.match(node.name)
                or _NODE_NORMALIZER.match(node.name)):
            continue
        body = "\n".join(lines[node.lineno - 1:(node.end_lineno or node.lineno)])
        if _STRING_TRANSFORM.search(body):
            out.append(f"{path.name}:{node.lineno} defines a private id "
                       f"normalizer {node.name!r} -- import the canonical one")
    return out


DETECTORS = (alias_map_violations, snake_reimplementation_violations,
             private_normalizer_violations)


def test_only_knowledge_and_normalize_own_the_node_id_transform():
    violations: list[str] = []
    for path in _sources():
        for detector in DETECTORS:
            violations.extend(detector(path))
    assert not violations, (
        "the node-id transform has been reimplemented outside "
        "normalize.py/knowledge.py:\n" + "\n".join(violations))


@pytest.mark.parametrize("detector, source", [
    (alias_map_violations,
     "def f():\n    return {normalize_node_id(m): m for m in MECHANISMS}\n"),
    (alias_map_violations,
     "INDEX = dict(\n    (normalize_node_id(m), m) for m in MECHANISMS)\n"
     "OTHER = {\n    normalize_node_id(m): m\n    for m in MECHANISMS}\n"),
    (snake_reimplementation_violations,
     'def f(name):\n    return name.lower().replace(" ", "_")\n'),
    (private_normalizer_violations,
     'def _norm(name):\n    return name.strip()\n'),
    (private_normalizer_violations,
     'def _canonical(value):\n    return str(value).strip().upper()\n'),
])
def test_the_guard_fires_on_a_synthetic_violation(detector, source, tmp_path):
    """A scan that stopped matching would look exactly like a clean tree."""
    path = tmp_path / "synthetic_violation.py"
    path.write_text(source, encoding="utf-8")
    assert detector(path), f"{detector.__name__} stopped detecting"


@pytest.mark.parametrize("detector, source", [
    # a haystack join: two values, one space, then snaked for substring hints
    (snake_reimplementation_violations,
     'def f(node_id, label):\n'
     '    return f"{node_id} {label}".lower().replace(" ", "_")\n'),
    # json canonicalization -- a different meaning of the same word
    (private_normalizer_violations,
     'def _canonical(value):\n'
     '    return json.dumps(value, sort_keys=True)\n'),
    # a lookup THROUGH the canonical accessor is the point, not a violation
    (alias_map_violations,
     'def f(node_id):\n    return resolve_mechanism_id(node_id)\n'),
])
def test_the_guard_does_not_fire_on_the_legitimate_shapes(detector, source,
                                                          tmp_path):
    path = tmp_path / "legitimate.py"
    path.write_text(source, encoding="utf-8")
    assert not detector(path), f"{detector.__name__} false positive"


def test_the_alias_map_detector_is_armed_and_does_not_fire_on_f_strings():
    """Guards the guard (SESSION_PROTOCOL 7.3).

    `_ALIAS_MAP` fired on `scripts/probes/mechanism_family_closure.py:118` --
    `print(f"  {k} -> {normalize_node_id(k)}")` -- which prints the transform
    rather than building a map over it. `scripts` is in SCAN_ROOTS by design,
    so any new script that merely PRINTS a node id would have failed this
    suite, and the obvious "fix" is to weaken the detector until it stops
    complaining.

    So both directions are pinned: the four shapes that ARE alias maps must
    still match, and the shapes that merely mention the transform must not.
    A detector that stops firing is worth nothing; one that fires on a print
    trains people to disable it.
    """
    must_match = (
        "ALIASES = {normalize_node_id(k): v for k in keys}",
        "    normalize_node_id(key): label,",
        "ALIASES = {normalize_node_id(",          # multi-line dict opener
        "m = { normalize_node_id(k) : v }",
    )
    must_not_match = (
        'print(f"       {k} -> {normalize_node_id(k)}")',
        'f"{normalize_node_id(x)}"',
        "if normalize_node_id(k) not in labels:",
        "missing = sorted(k for k in M if normalize_node_id(k) not in labels)",
    )
    for line in must_match:
        assert _ALIAS_MAP.search(line), f"detector went blind to: {line!r}"
    for line in must_not_match:
        assert not _ALIAS_MAP.search(line), f"detector fires on a non-map: {line!r}"
