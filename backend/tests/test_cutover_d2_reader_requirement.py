"""CUTOVER REQUIREMENT 7 -- `DATA_GAPS/cutover-checklist.md` §7.

THIS IS A TRIPWIRE, NOT A CONDITIONAL SKIP. Read that before changing it.

THE REQUIREMENT. When the V5 canonical path serves, it must either

  A. re-run discovery for every render -- so every `mechanism_id` is
     re-derived from `traverse`, which returns only `review_status =
     'APPROVED'` rows with a non-null `reviewed_by`; or
  B. re-validate each persisted `mechanism_id` against `mechanism_edge`
     before rendering.

A third shape -- rendering sections straight from stored `company_impact`
rows -- is FORBIDDEN, and is what this file exists to prevent.

WHY. `gates.py:363` tests `bool(draft.mechanism_id)`: presence of a non-null
string. It reads neither `review_status` nor `reviewed_by`, and does not check
that the id resolves to a row at all (defect D2, DEFECTS-001). D10's fix
closed the WRITER side -- nothing unapproved is walkable, so no V5 discovery
site can mint an unresolvable id. But an id is WRITTEN ONCE AND READ LATER:

  * `app/core/impact_writer.py` persists `mechanism_id` onto `company_impact`
  * `app/output/sections.py` keys `section_key` off `impact.mechanism_id`
  * `edge_review.reject_edge` can set REJECTED at any time, and
    `traverse._SELECT` filters `effective_from`/`effective_to` against `as_of`

so an edge that was approved and in-window when a candidate was built can be
rejected, or lapse, afterwards. Under the forbidden shape that stored id keeps
publishing and nothing re-checks it -- D2's failure mode arriving WITH the
cutover instead of closing at it, on the V5 path, carrying V5's authority.

HOW IT BEHAVES. While V5 is dark the test asserts that V5 is dark: green, and
load-bearing rather than vacuous. The moment a V5 canonical module is wired
into the serving path it goes RED, and the only ways to green it are A or B.
It cannot be satisfied by the third shape.

Deleting or xfail-ing this test is the same act as choosing the third shape,
and should be reviewed as such.
"""
import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "app"

# The V5 canonical modules. Any of these reached from the serving path means
# V5 is being served (docs/v5/00_MASTER_CONTEXT.md's canonical path).
V5_CANONICAL = (
    "app.discovery",
    "app.core.gates",
    "app.core.reducer",
    "app.output.sections",
    "app.graph.traverse",
)

# What "the serving path" is: the modules that turn a request or a pipeline
# run into rendered output.
SERVING_PATH = ("pipeline.py", "main.py")
SERVING_DIRS = ("routers",)

# Satisfying evidence for shape A / shape B. Either the serving path calls
# discovery itself, or it calls something whose NAME says it re-validates.
SHAPE_A = re.compile(r"\bdiscover\s*\(")
SHAPE_B = re.compile(r"\brevalidate_mechanism_ids?\b|\bmechanism_ids?_still_usable\b")


def _serving_sources() -> dict[Path, str]:
    out = {}
    for name in SERVING_PATH:
        path = APP / name
        if path.exists():
            out[path] = path.read_text(encoding="utf-8")
    for directory in SERVING_DIRS:
        for path in sorted((APP / directory).glob("*.py")):
            out[path] = path.read_text(encoding="utf-8")
    return out


def _imported_modules(source: str) -> set[str]:
    """Every module name imported by `source`, as dotted paths.

    Parsed with `ast` rather than matched as text. A substring search misses
    `from app.output import sections` -- which does not contain the string
    "app.output.sections" -- and that miss makes this whole file a test that
    cannot fail. Measured: with a text search, wiring `from app.output import
    sections` into pipeline.py left the tripwire GREEN.

    `ast.walk` also reaches imports nested inside functions, which is how most
    of this codebase imports across layers.
    """
    modules: set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:                                   # pragma: no cover
        return modules
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def _v5_references() -> dict[str, list[str]]:
    """{module: [where it is referenced]} across the serving path."""
    found: dict[str, list[str]] = {}
    for path, source in _serving_sources().items():
        imported = _imported_modules(source)
        for module in V5_CANONICAL:
            if any(name == module or name.startswith(f"{module}.")
                   for name in imported):
                found.setdefault(module, []).append(path.name)
    return found


def test_v5_serving_reruns_discovery_or_revalidates_persisted_mechanism_ids():
    """Cutover checklist §7. See this module's docstring before editing."""
    referenced = _v5_references()

    if not referenced:
        # V5 IS DARK. This branch is not a skip: it pins the fact the whole
        # requirement currently rests on. When someone wires V5, `referenced`
        # becomes non-empty and control moves to the assertion below.
        assert referenced == {}, referenced
        return

    sources = _serving_sources()
    body = "\n".join(sources.values())
    shape_a = bool(SHAPE_A.search(body))
    shape_b = bool(SHAPE_B.search(body))

    assert shape_a or shape_b, (
        "V5 CUTOVER REQUIREMENT 7 IS NOT MET.\n\n"
        f"The serving path now references V5 canonical modules: {referenced}\n"
        "but it neither re-runs discovery nor re-validates persisted "
        "mechanism ids.\n\n"
        "A stored `company_impact.mechanism_id` names an edge whose "
        "`review_status` and effective window can have CHANGED since it was "
        "written. `gates.py` only tests that the string is non-null (defect "
        "D2), so a rejected or lapsed edge keeps publishing.\n\n"
        "Satisfy ONE of:\n"
        "  A. call `discover(...)` on the serving path, so every mechanism_id "
        "is re-derived through `traverse` (APPROVED + reviewed_by only); or\n"
        "  B. add a re-validation step named `revalidate_mechanism_ids` (or "
        "`mechanism_ids_still_usable`) and call it before rendering.\n\n"
        "Do NOT satisfy this by deleting the test. See "
        "DATA_GAPS/cutover-checklist.md section 7.")


def test_the_tripwire_watches_the_modules_it_claims_to():
    """Guards the guard.

    If a V5 module is renamed and this list is not updated, the tripwire goes
    quiet without failing -- the same silent-pass class the D10 postscript
    records. So every name in `V5_CANONICAL` must resolve to something that
    exists on disk.
    """
    for module in V5_CANONICAL:
        relative = Path(module.replace("app.", "", 1).replace(".", "/"))
        candidates = (APP / relative, APP / f"{relative}.py")
        assert any(c.exists() for c in candidates), (
            f"{module} is in V5_CANONICAL but resolves to nothing under "
            f"app/ -- the tripwire is watching a module that no longer "
            f"exists and would stay green through the cutover")


def test_the_tripwire_fires_on_every_import_form():
    """PROOF THAT THE TRIPWIRE CAN FAIL.

    A guard that cannot fire is worse than no guard: it reads as coverage.
    The first version of this file matched module names as TEXT, and wiring
    `from app.output import sections` into pipeline.py left it green -- the
    string "app.output.sections" never appears in that line. Caught by running
    the arming proof rather than by reading the code.

    So each import form a real cutover might use is asserted to be detected.
    """
    forms = {
        "from app.output import sections": "app.output.sections",
        "from app.output.sections import build_sections": "app.output.sections",
        "import app.output.sections": "app.output.sections",
        "from app.discovery.engine import discover": "app.discovery",
        "from app.discovery import engine": "app.discovery",
        "from app.graph.traverse import traverse": "app.graph.traverse",
        "from app.core import reducer": "app.core.reducer",
        "def f():\n    from app.core.gates import evaluate": "app.core.gates",
    }
    for source, expected in forms.items():
        imported = _imported_modules(source)
        assert any(name == expected or name.startswith(f"{expected}.")
                   for name in imported), (
            f"tripwire would NOT detect this wiring:\n  {source!r}\n"
            f"  parsed as {sorted(imported)}")


def test_neither_shape_is_already_satisfied_by_accident():
    """The other half of arming.

    If `discover(` or a revalidation name already appears anywhere on the
    serving path for an unrelated reason, the shape check passes before the
    cutover is even attempted and the tripwire is dead on arrival. Today
    neither does; if that changes, the pattern must be narrowed rather than
    left to pass vacuously.
    """
    body = "\n".join(_serving_sources().values())
    assert not SHAPE_A.search(body), (
        "the serving path already matches SHAPE_A, so requirement 7 would "
        "pass without anyone satisfying it -- narrow the pattern")
    assert not SHAPE_B.search(body), (
        "the serving path already matches SHAPE_B, so requirement 7 would "
        "pass without anyone satisfying it -- narrow the pattern")


def test_the_serving_path_this_watches_still_exists():
    """Same guard, other end: if `pipeline.py` or `routers/` moved, the
    tripwire would scan nothing and pass forever."""
    sources = _serving_sources()
    assert sources, "no serving-path sources found -- the tripwire scans nothing"
    names = {path.name for path in sources}
    assert "pipeline.py" in names, (
        "app/pipeline.py is gone; update SERVING_PATH or this tripwire is "
        "watching the wrong place")
