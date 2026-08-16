"""Migration 0012 -- the V5 exposure ledger, and the DDL-drift guards.

Same discipline as 0008/0011 (controller adaptation): the trigger and view
DDL is DUPLICATED between `app/models.py` (create_all -- the whole test
suite and every fresh dev DB) and the migration (production), because a
migration must never import app code that drifts underneath it. Drift is
closed mechanically by the byte-identity test below.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

BACKEND = Path(__file__).resolve().parents[2]
MIGRATION = BACKEND / "alembic" / "versions" / "0012_v5_exposure_ledger.py"

LEDGER_TABLES = ("company_exposure", "company_segment", "company_financials",
                 "pass_through_curve", "company_modifier", "exposure_proposal",
                 "filing_artefact", "company_entity_meta",
                 "entity_corporate_action", "company_alias_window")


def _alembic(db_url: str, *args: str):
    env = dict(os.environ, DATABASE_URL=db_url)
    return subprocess.run([sys.executable, "-m", "alembic", *args],
                          cwd=BACKEND, env=env, capture_output=True, text=True)


def _upgrade(tmp_path):
    url = f"sqlite:///{tmp_path / 'ledger.db'}"
    result = _alembic(url, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    return url


def test_upgrade_head_creates_the_ledger_tables(tmp_path):
    engine = create_engine(_upgrade(tmp_path))
    tables = set(inspect(engine).get_table_names())
    assert set(LEDGER_TABLES) <= tables
    engine.dispose()


def test_the_migration_writes_no_ledger_rows(tmp_path):
    """Phase 1 produces NO data. A migration that seeded a single exposure
    row would be the fabrication the master context forbids."""
    engine = create_engine(_upgrade(tmp_path))
    with engine.connect() as connection:
        for table in LEDGER_TABLES:
            count = connection.execute(text(f"SELECT count(*) FROM {table}")).scalar()
            assert count == 0, f"0012 seeded {count} row(s) into {table}"
    engine.dispose()


def test_migration_installs_the_ledger_write_guard(tmp_path):
    engine = create_engine(_upgrade(tmp_path))
    with engine.connect() as connection:
        triggers = {row[0] for row in connection.execute(text(
            "SELECT name FROM sqlite_master WHERE type='trigger'"))}
        views = {row[0] for row in connection.execute(text(
            "SELECT name FROM sqlite_master WHERE type='view'"))}
    assert {"company_exposure_review_only_insert",
            "company_exposure_review_only_update",
            "company_exposure_review_only_delete"} <= triggers
    assert {"extractor_quality", "exposure_coverage"} <= views
    engine.dispose()


def test_the_boot_check_polices_the_delete_guard_too(tmp_path):
    """FIX ROUND 1 / I1: the DELETE guard is worthless if a later migration
    can drop it unnoticed, so it joins the boot-asserted list."""
    from tools.migrate_on_boot import LEDGER_TRIGGERS, check_ledger_guard

    assert "company_exposure_review_only_delete" in LEDGER_TRIGGERS

    url = _upgrade(tmp_path)
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("DROP TRIGGER company_exposure_review_only_delete"))
    engine.dispose()

    status, missing = check_ledger_guard(url)
    assert status == "missing"
    assert "company_exposure_review_only_delete" in missing


def test_migration_leaves_the_earlier_triggers_installed(tmp_path):
    """0008's §26 gated-row triggers and 0011's single-writer triggers must
    both survive 0012 -- a batch rebuild of an existing SQLite table
    silently drops its triggers."""
    from tools.migrate_on_boot import GATED_ROW_TRIGGERS

    engine = create_engine(_upgrade(tmp_path))
    with engine.connect() as connection:
        triggers = {row[0] for row in connection.execute(text(
            "SELECT name FROM sqlite_master WHERE type='trigger'"))}
    assert set(GATED_ROW_TRIGGERS) <= triggers
    assert {"company_impact_reducer_only_insert", "signal_append_only_update"} <= triggers
    engine.dispose()


def test_migration_does_not_alter_any_existing_table():
    source = MIGRATION.read_text(encoding="utf-8")
    body = source.split('"""', 2)[-1]
    for verb in ("batch_alter_table", "op.alter_column", "op.add_column"):
        assert verb not in body, f"0012 calls {verb} on an existing table"


def test_migration_is_rerunnable_over_its_own_output(tmp_path):
    url = _upgrade(tmp_path)
    assert _alembic(url, "downgrade", "0011").returncode == 0
    result = _alembic(url, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    engine = create_engine(url)
    assert "company_exposure" in set(inspect(engine).get_table_names())
    engine.dispose()


def test_models_and_0012_ddl_are_byte_identical():
    from app.models import V5_LEDGER_DDL

    source = MIGRATION.read_text(encoding="utf-8")
    found = re.findall(r'^_[A-Z0-9_]+_(?:TRIGGER|VIEW) = """(.*?)"""', source,
                       flags=re.MULTILINE | re.DOTALL)
    assert len(found) == len(V5_LEDGER_DDL), (
        f"0012 defines {len(found)} DDL literals, models.py exports "
        f"{len(V5_LEDGER_DDL)}")
    normalize = lambda s: " ".join(s.split())  # noqa: E731
    assert [normalize(s) for s in found] == [normalize(s) for s in V5_LEDGER_DDL], (
        "the ledger DDL in 0012 has drifted from app/models.py -- migrated "
        "and create_all-built DBs would enforce different rules")


def test_the_postgres_role_ddl_is_documented_for_the_port():
    source = MIGRATION.read_text(encoding="utf-8")
    for needle in ("CREATE ROLE newsflo_ledger_reviewer", "GRANT", "REVOKE"):
        assert needle in source


def test_create_all_and_the_migration_agree_on_the_ledger_tables(tmp_path):
    from app import models  # noqa: F401
    from app.db import Base

    migrated = create_engine(_upgrade(tmp_path))
    created = create_engine(f"sqlite:///{tmp_path / 'created.db'}")
    Base.metadata.create_all(created)

    for table in LEDGER_TABLES:
        a = {c["name"] for c in inspect(migrated).get_columns(table)}
        b = {c["name"] for c in inspect(created).get_columns(table)}
        assert a == b, f"{table}: migration {sorted(a - b)} vs models {sorted(b - a)}"
    migrated.dispose()
    created.dispose()


def test_boot_asserts_the_ledger_guard(tmp_path):
    """migrate_on_boot refuses to start when the ledger write guard is gone
    -- the same discipline the §26 and V5 single-writer checks already have,
    in a SEPARATE function over a SEPARATE trigger list."""
    from tools.migrate_on_boot import (
        LedgerGuardMissing, _assert_ledger_guard, check_ledger_guard,
    )

    url = _upgrade(tmp_path)
    assert check_ledger_guard(url)[0] == "ok"

    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("DROP TRIGGER company_exposure_review_only_insert"))
    engine.dispose()

    status, missing = check_ledger_guard(url)
    assert status == "missing"
    assert "company_exposure_review_only_insert" in missing
    try:
        _assert_ledger_guard(url, "sqlite")
    except LedgerGuardMissing:
        pass
    else:                                        # pragma: no cover
        raise AssertionError("boot did not refuse an unguarded ledger")
