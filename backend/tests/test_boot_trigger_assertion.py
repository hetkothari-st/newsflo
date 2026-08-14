"""The boot-time presence check for the §26 gated-row trigger backstop.

WHY THIS EXISTS (final review wave, item 1). The two
`alert_companies_gated_consistency*` triggers are the database-level
guarantee that a gated AlertCompany row can never hold a contradictory
economic_effect/direction pair or lose its rationale. SQLite drops every
trigger attached to a table it drops, and Alembic implements a SQLite
`batch_alter_table` as CREATE-new / copy / DROP-old / RENAME without
copying triggers -- so any future migration that batch-alters
`alert_companies` silently deletes the whole backstop.

Nothing detected that. `tools/migrate_on_boot.check_gated_row_triggers`
now does, and this pins it: a healthy migrated DB passes, a DB with a
trigger removed is detected AND the missing trigger is named, and the boot
path raises rather than coming up with an unguarded table.
"""
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from tools.migrate_on_boot import (
    GATED_ROW_TRIGGERS, GatedRowTriggersMissing, _assert_gated_row_triggers,
    check_gated_row_triggers, migrate_on_boot,
)

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def migrated_db(tmp_path_factory):
    """One real `alembic upgrade head` SQLite database, built once and
    copied per test -- the alembic subprocess is the slow part."""
    db = tmp_path_factory.mktemp("boot_triggers") / "migrated.db"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND, env=dict(os.environ, DATABASE_URL=f"sqlite:///{db}"),
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return db


def _copy(db: Path, tmp_path: Path) -> Path:
    target = tmp_path / "copy.db"
    shutil.copy(db, target)
    return target


def _drop_trigger(db: Path, name: str) -> None:
    connection = sqlite3.connect(db)
    try:
        connection.execute(f"DROP TRIGGER {name}")
        connection.commit()
    finally:
        connection.close()


def test_the_checked_names_are_the_names_models_actually_installs():
    """A rename in app/models.py must not leave this check silently
    watching for triggers nobody creates any more (it would then pass on
    every DB, forever, which is the exact failure mode being prevented)."""
    from app.models import GATED_ROW_TRIGGER_DDL

    ddl = "\n".join(GATED_ROW_TRIGGER_DDL)
    for name in GATED_ROW_TRIGGERS:
        assert f"CREATE TRIGGER IF NOT EXISTS {name}\n" in ddl


def test_a_healthy_migrated_db_passes(migrated_db):
    assert check_gated_row_triggers(f"sqlite:///{migrated_db}") == ("ok", ())
    # ...and the boot assertion is silent on it.
    _assert_gated_row_triggers(f"sqlite:///{migrated_db}", "sqlite")


@pytest.mark.parametrize("dropped", GATED_ROW_TRIGGERS)
def test_a_dropped_trigger_is_detected_and_named(migrated_db, tmp_path, dropped):
    db = _copy(migrated_db, tmp_path)
    _drop_trigger(db, dropped)

    status, missing = check_gated_row_triggers(f"sqlite:///{db}")

    assert status == "missing"
    assert missing == (dropped,), (
        "the check must name the trigger that is actually gone, not just "
        "report a failure")


def test_both_triggers_gone_are_both_reported(migrated_db, tmp_path):
    db = _copy(migrated_db, tmp_path)
    for name in GATED_ROW_TRIGGERS:
        _drop_trigger(db, name)

    status, missing = check_gated_row_triggers(f"sqlite:///{db}")

    assert status == "missing"
    assert set(missing) == set(GATED_ROW_TRIGGERS)


def test_the_boot_assertion_raises_and_names_the_missing_trigger(
        migrated_db, tmp_path, capsys):
    db = _copy(migrated_db, tmp_path)
    _drop_trigger(db, GATED_ROW_TRIGGERS[0])

    with pytest.raises(GatedRowTriggersMissing) as excinfo:
        _assert_gated_row_triggers(f"sqlite:///{db}", "sqlite")

    assert GATED_ROW_TRIGGERS[0] in str(excinfo.value)
    assert GATED_ROW_TRIGGERS[0] in capsys.readouterr().err


def test_migrate_on_boot_fails_on_a_db_whose_backstop_was_lost(
        migrated_db, tmp_path):
    """The end-to-end shape of the real incident: the schema migrates
    cleanly to head (nothing else is wrong) and the boot STILL fails,
    because a rebuild took the triggers with it and no migration put them
    back."""
    db = _copy(migrated_db, tmp_path)
    _drop_trigger(db, GATED_ROW_TRIGGERS[1])

    with pytest.raises(GatedRowTriggersMissing):
        migrate_on_boot(f"sqlite:///{db}")

    # And it passes on the untouched database -- the failure above is the
    # missing trigger, not the migration.
    healthy_dir = tmp_path / "ok"
    healthy_dir.mkdir()
    assert migrate_on_boot(f"sqlite:///{_copy(migrated_db, healthy_dir)}") == "managed"


def test_a_non_sqlite_url_is_skipped_not_failed():
    """Postgres has no CREATE TRIGGER IF NOT EXISTS and the port is a
    ledgered, deliberate absence (app/models.py's emit_gated_row_triggers
    no-ops off SQLite). Skipping must never look like a missing backstop --
    and must not open a connection to assert that."""
    assert check_gated_row_triggers(
        "postgresql://user:pw@nonexistent.invalid:5432/db") == ("skipped_dialect", ())


def test_a_db_without_alert_companies_is_skipped(tmp_path):
    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()

    assert check_gated_row_triggers(f"sqlite:///{empty}") == ("skipped_no_table", ())
