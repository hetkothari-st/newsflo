"""The single-head guard on the alembic revision graph.

WHY THIS EXISTS. Migrations in this repo are authored by parallel sessions,
and two of them adding a revision on the same day both write
`down_revision = '00NN'`. The graph forks. Neither revision is wrong on its
own, nothing in the suite reads the graph, and the first symptom is
`alembic upgrade head` refusing with "Multiple head revisions are present"
-- a message that names no revision -- inside a container that then
restart-loops.

`tools/migrate_on_boot.check_single_head` reads the graph directly and names
the heads, and `migrate_on_boot` asserts on it before it runs anything.

This file pins both halves, in the shape the other boot-backstop self-tests
use (`tests/test_boot_trigger_assertion.py`): the real repo passes, and a
SYNTHETIC fork built in `tmp_path` is detected, named, and raised on. The
synthetic half is the load-bearing one -- a guard that has never been seen
to fire is not a guard.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tools import migrate_on_boot as boot
from tools.migrate_on_boot import (
    MultipleMigrationHeads, _assert_single_head, check_single_head,
    migration_heads,
)

BACKEND = Path(__file__).resolve().parents[1]
REAL_VERSIONS = BACKEND / "alembic" / "versions"

_REVISION_TEMPLATE = '''"""synthetic revision {rev} -- built by a test, never shipped"""
from typing import Sequence, Union

revision: str = {rev!r}
down_revision: Union[str, Sequence[str], None] = {down!r}
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
'''


def _script_dir(tmp_path: Path, name: str = "alembic") -> Path:
    """A bare alembic script directory. `ScriptDirectory` needs the directory
    and its `versions/` child to exist; computing heads reads nothing else,
    so no env.py or alembic.ini is involved."""
    versions = tmp_path / name / "versions"
    versions.mkdir(parents=True)
    return tmp_path / name


def _write_revision(versions: Path, rev: str, down: str | None) -> None:
    (versions / f"{rev}.py").write_text(
        _REVISION_TEMPLATE.format(rev=rev, down=down), encoding="utf-8")


# --- the real repo ---------------------------------------------------------

def test_the_repo_has_exactly_one_head():
    """The assertion this guard exists to make. The head's ID is not pinned
    -- every new migration changes it -- only that there is exactly one."""
    status, heads = check_single_head()

    assert status == "ok", (
        "the alembic revision graph has forked; heads: " + ", ".join(heads))
    assert len(heads) == 1


def test_the_boot_assertion_is_silent_on_the_real_repo():
    _assert_single_head()


def test_the_checker_agrees_with_alembic_itself():
    """A checker that computed heads its own way could drift from the tool
    that actually refuses to upgrade. This pins them to the same answer."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=BACKEND, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

    # `alembic heads` prints "<rev> (head)" per head, one per line.
    reported = {line.split()[0] for line in result.stdout.splitlines()
                if line.strip()}
    assert set(migration_heads()) == reported


# --- the self-test: a fork built on purpose --------------------------------

def test_a_minimal_two_head_fork_is_detected_and_both_heads_named(tmp_path):
    """Three revisions, two of them sharing one `down_revision` -- the exact
    shape of two sessions branching off the same tip."""
    script = _script_dir(tmp_path)
    _write_revision(script / "versions", "aaaa", None)
    _write_revision(script / "versions", "bbbb", "aaaa")
    _write_revision(script / "versions", "cccc", "aaaa")

    status, heads = check_single_head(script)

    assert status == "multiple_heads"
    assert heads == ("bbbb", "cccc"), (
        "the checker must name every head, not merely report a failure")


def test_the_boot_assertion_raises_on_the_synthetic_fork(tmp_path, capsys):
    script = _script_dir(tmp_path)
    _write_revision(script / "versions", "aaaa", None)
    _write_revision(script / "versions", "bbbb", "aaaa")
    _write_revision(script / "versions", "cccc", "aaaa")

    with pytest.raises(MultipleMigrationHeads) as excinfo:
        _assert_single_head(script)

    message = str(excinfo.value)
    assert "bbbb" in message and "cccc" in message
    stderr = capsys.readouterr().err
    assert "bbbb" in stderr and "cccc" in stderr


def test_a_fork_injected_into_a_copy_of_the_real_versions_dir_is_caught(tmp_path):
    """The realistic incident: the shipped graph, plus one revision authored
    against the current tip's PARENT. Copying the real directory means the
    guard is exercised against the real revision files, not only against a
    toy graph."""
    script = _script_dir(tmp_path)
    for source in REAL_VERSIONS.glob("*.py"):
        shutil.copy(source, script / "versions" / source.name)

    from alembic.script import ScriptDirectory

    (real_head,) = migration_heads()
    real_parent = ScriptDirectory(str(script)).get_revision(real_head).down_revision

    # A second child of the real head's parent: a sibling of the real head.
    _write_revision(script / "versions", "9999_rogue", real_parent)

    status, heads = check_single_head(script)

    assert status == "multiple_heads"
    assert set(heads) == {real_head, "9999_rogue"}

    # ...and the real directory is untouched by any of this.
    assert check_single_head()[0] == "ok"


def test_an_empty_versions_directory_reports_no_head(tmp_path):
    """Not the fork case, but the other way the graph can be unresolvable --
    and it must not read as 'ok' merely because there is no second head."""
    script = _script_dir(tmp_path)

    status, heads = check_single_head(script)

    assert status == "no_head"
    assert heads == ()

    with pytest.raises(MultipleMigrationHeads):
        _assert_single_head(script)


# --- the wiring ------------------------------------------------------------

def test_migrate_on_boot_refuses_to_run_against_a_forked_graph(
        tmp_path, monkeypatch):
    """The boot path must fail on the fork BEFORE it touches the database --
    otherwise the failure the operator sees is alembic's anonymous one."""
    script = _script_dir(tmp_path, "forked")
    _write_revision(script / "versions", "aaaa", None)
    _write_revision(script / "versions", "bbbb", "aaaa")
    _write_revision(script / "versions", "cccc", "aaaa")
    monkeypatch.setattr(boot, "ALEMBIC_DIR", script)

    db = tmp_path / "never_built.db"
    with pytest.raises(MultipleMigrationHeads):
        boot.migrate_on_boot(f"sqlite:///{db}")

    assert not db.exists(), (
        "the guard must fire before anything opens or builds the database")
