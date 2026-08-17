"""MASTER-CONTEXT INVARIANT 13 -- no model may write `mechanism_edge`. Ever.

Same shape as `tests/test_node_id_single_source.py`: a SOURCE-LEVEL scan,
because the defect it guards is invisible at runtime. A module that writes
`mechanism_edge` from model output produces rows that look exactly like rows
a human authored -- same table, same columns, same `derivation` string -- and
nothing downstream can tell them apart. There is no assertion that can catch
it after the fact; only refusing to let the code be written can.

WHY THIS IS WORTH A GUARD. V5's mechanism vocabulary is closed by
construction and that is the whole reason V5 does not inherit V4's orphan
defect (45 of 58 stored V4 node ids resolve to no registry entry; six of them
propose price-driven channels invariant 3 exists to refuse --
`docs/v5/decisions/ADR-002-price-fundamental-decoupling-load-bearing.md`).
The immunity is CONDITIONAL on this table staying human-authored. Conditions
that are only true by habit stop being true.

TWO BAN PATTERNS, each precise enough to name the offender:

  1. a WRITE to `mechanism_edge` from a module that can reach a model --
     one that imports a provider SDK, or the repo's own router/client seam;
  2. a WRITE that sets `reviewed_by` to anything but NULL. Approval is
     `app/ledger/edge_review.approve_edge`, which records who did it; a
     loader that can approve is a loader that can approve itself.

`test_the_guard_fires_on_a_synthetic_violation` proves each detector still
detects -- without it, a scan that silently stopped matching would read
exactly like a clean tree.
"""
import re
from pathlib import Path

import pytest

from tests.phase6.conftest import BACKEND, code_lines

SCAN_ROOTS = ("app", "eval", "scripts", "tools")

#: Provider SDKs, plus this repo's own model seam. A module importing any of
#: these can reach a model, directly or one call away.
MODEL_REACHING_IMPORTS = (
    "anthropic", "google.generativeai", "google.genai", "groq", "openai",
    "app.analysis.claude_client", "app.analysis.impact_graph.router",
    "app.analysis.impact_graph.engine", "app.analysis.cascade",
)

_WRITES_EDGE = re.compile(
    r"(INSERT\s+(?:OR\s+\w+\s+)?INTO\s+mechanism_edge"
    r"|UPDATE\s+mechanism_edge\s+SET"
    r"|DELETE\s+FROM\s+mechanism_edge)", re.IGNORECASE)

#: `reviewed_by` being set to a bound parameter or a literal, rather than the
#: bare NULL a candidate loader must write.
_SETS_REVIEWER = re.compile(r"reviewed_by\s*=\s*(?!NULL)(:|\"|')", re.IGNORECASE)

#: The ONE module allowed to set a reviewer, because recording who approved
#: is its entire job.
REVIEWER_EXEMPT = {BACKEND / "app" / "ledger" / "edge_review.py"}


def _sources() -> list[Path]:
    paths: list[Path] = []
    for root in SCAN_ROOTS:
        base = BACKEND / root
        if base.is_dir():
            paths.extend(p for p in base.rglob("*.py")
                         if "__pycache__" not in p.parts)
    return sorted(paths)


def _imports_a_model_seam(path: Path) -> set[str]:
    source = path.read_text(encoding="utf-8")
    found = set()
    for number, line in code_lines(path):
        if not re.match(r"\s*(from|import)\s", line):
            continue
        for needle in MODEL_REACHING_IMPORTS:
            if re.search(r"\b" + re.escape(needle) + r"\b", line):
                found.add(needle)
    return found


def model_reaching_write_violations(path: Path) -> list[str]:
    """A module that can reach a model must not write the table."""
    writes = [number for number, line in code_lines(path)
              if _WRITES_EDGE.search(line)]
    if not writes:
        return []
    seams = _imports_a_model_seam(path)
    if not seams:
        return []
    return [f"{path.name}:{writes[0]} writes mechanism_edge and imports "
            f"{sorted(seams)} -- invariant 13: no model may write this table"]


def self_approval_violations(path: Path) -> list[str]:
    """Only `edge_review` may name a reviewer."""
    if path in REVIEWER_EXEMPT:
        return []
    out = []
    for number, line in code_lines(path):
        if not _SETS_REVIEWER.search(line):
            continue
        if "mechanism_edge" not in path.read_text(encoding="utf-8"):
            continue
        out.append(
            f"{path.name}:{number} sets mechanism_edge.reviewed_by -- approval "
            f"is app/ledger/edge_review.approve_edge, which records who did it")
    return out


DETECTORS = (model_reaching_write_violations, self_approval_violations)


def test_no_model_reaching_module_writes_mechanism_edge():
    violations: list[str] = []
    for path in _sources():
        for detector in DETECTORS:
            violations.extend(detector(path))
    assert not violations, (
        "master-context invariant 13 violated:\n" + "\n".join(violations))


def test_the_writers_are_the_two_expected_ones_and_no_more():
    """A positive inventory, not only a ban. A third writer appearing is a
    thing to look at even when it passes both detectors."""
    writers = {path.name for path in _sources()
               if any(_WRITES_EDGE.search(line) for _, line in code_lines(path))}
    assert writers == {"load.py", "authored_edges.py", "edge_review.py"}, (
        f"the set of modules writing mechanism_edge changed: {sorted(writers)}. "
        "Expected io_bootstrap/load.py (queues IO_TABLE candidates unreviewed), "
        "graph/authored_edges.py (loads hand-authored candidates unreviewed) "
        "and ledger/edge_review.py (the human approval path).")


def test_both_candidate_loaders_refuse_to_write_a_reviewer():
    """The refusal is code, not convention -- exercised, not read."""
    from app.graph.authored_edges import AuthoredEdgeError, blockers
    from app.graph.io_bootstrap.load import IOLoadError, load_candidate_edges

    with pytest.raises(IOLoadError, match="queued UNREVIEWED"):
        load_candidate_edges(None, [{"edge_id": "x", "reviewed_by": "a-model"}])

    reasons = blockers({"edge_id": "y", "reviewed_by": "a-model"}, modelled=())
    assert any("UNREVIEWED" in r for r in reasons), reasons
    assert AuthoredEdgeError is not None


@pytest.mark.parametrize("detector, source", [
    (model_reaching_write_violations,
     "import anthropic\n"
     "def f(session):\n"
     "    session.execute('INSERT INTO mechanism_edge (edge_id) VALUES (1)')\n"),
    (model_reaching_write_violations,
     "from app.analysis.impact_graph.router import StageRouter\n"
     "def f(session):\n"
     "    session.execute('UPDATE mechanism_edge SET to_node = 1')\n"),
    (self_approval_violations,
     "def f(session):\n"
     "    session.execute('UPDATE mechanism_edge SET reviewed_by = :who')\n"),
])
def test_the_guard_fires_on_a_synthetic_violation(detector, source, tmp_path):
    path = tmp_path / "synthetic_violation.py"
    path.write_text(source, encoding="utf-8")
    assert detector(path), f"{detector.__name__} stopped detecting"


@pytest.mark.parametrize("detector, source", [
    # a loader with no model seam writing an UNREVIEWED candidate: the shape
    # that is supposed to exist
    (model_reaching_write_violations,
     "def f(session):\n"
     "    session.execute('INSERT INTO mechanism_edge (edge_id, reviewed_by) "
     "VALUES (:e, NULL)')\n"),
    # a model-reaching module that only READS the table
    (model_reaching_write_violations,
     "import anthropic\n"
     "def f(session):\n"
     "    return session.execute('SELECT * FROM mechanism_edge')\n"),
    # setting a reviewer on a DIFFERENT table
    (self_approval_violations,
     "def f(session):\n"
     "    session.execute('UPDATE company_exposure SET reviewed_by = :who')\n"),
])
def test_the_guard_does_not_fire_on_the_legitimate_shapes(detector, source,
                                                          tmp_path):
    path = tmp_path / "legitimate.py"
    path.write_text(source, encoding="utf-8")
    assert not detector(path), f"{detector.__name__} false positive"
