"""Migration 0011 -- the V5 canonical tables, and the DDL-drift guards.

Follows the 0008 pattern (controller adaptation): the trigger DDL is
DUPLICATED between `app/models.py` (the create_all hook, which is what the
whole test suite and every fresh dev DB get) and the migration (which is
what production gets), because a migration must never import app code that
drifts underneath it. Drift is closed mechanically by the byte-identity
test below.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

BACKEND = Path(__file__).resolve().parents[2]
MIGRATION = BACKEND / "alembic" / "versions" / "0011_v5_single_writer.py"


def _alembic(db_url: str, *args: str):
    """Same shape as tests/test_migrations.py: a SUBPROCESS with
    DATABASE_URL, because app.db builds its engine at import time from
    settings and an in-process alembic run would migrate the dev DB."""
    env = dict(os.environ, DATABASE_URL=db_url)
    return subprocess.run([sys.executable, "-m", "alembic", *args],
                          cwd=BACKEND, env=env, capture_output=True, text=True)


def _upgrade(tmp_path):
    url = f"sqlite:///{tmp_path / 'v5.db'}"
    result = _alembic(url, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    return url


def test_upgrade_head_creates_the_v5_tables(tmp_path):
    engine = create_engine(_upgrade(tmp_path))
    tables = set(inspect(engine).get_table_names())
    assert {"signal", "supported_version", "company_impact",
            "firewall_deletion"} <= tables
    engine.dispose()


def test_company_impact_has_the_separation_columns_and_uniqueness(tmp_path):
    engine = create_engine(_upgrade(tmp_path))
    inspector = inspect(engine)
    columns = {c["name"] for c in inspector.get_columns("company_impact")}
    assert {"directness", "graph_distance", "discovery_source",
            "publication_tier", "needs_reanalysis", "reducer_version",
            "reducer_run_seq", "analysis_version"} <= columns

    uniques = {tuple(u["column_names"])
               for u in inspector.get_unique_constraints("company_impact")}
    uniques |= {tuple(i["column_names"]) for i in
                inspector.get_indexes("company_impact") if i["unique"]}
    assert ("event_id", "company_id", "analysis_version") in uniques
    engine.dispose()


def test_migration_registers_the_current_reducer_version(tmp_path):
    from app.core.reducer import REDUCER_VERSION

    engine = create_engine(_upgrade(tmp_path))
    with engine.connect() as connection:
        rows = connection.execute(text(
            "SELECT reducer_version, active FROM supported_version")).all()
    assert (REDUCER_VERSION, 1) in [(r[0], int(r[1])) for r in rows]
    engine.dispose()


def test_migration_installs_the_v5_triggers(tmp_path):
    engine = create_engine(_upgrade(tmp_path))
    with engine.connect() as connection:
        triggers = {row[0] for row in connection.execute(text(
            "SELECT name FROM sqlite_master WHERE type='trigger'"))}
    assert {"company_impact_reducer_only_insert",
            "company_impact_reducer_only_update",
            "signal_append_only_update",
            "signal_append_only_delete"} <= triggers
    engine.dispose()


def test_migration_leaves_the_0008_gated_row_triggers_installed(tmp_path):
    """0008's warning: a batch_alter_table over alert_companies silently
    drops the §26 backstop. 0011 must not touch that table at all."""
    from tools.migrate_on_boot import GATED_ROW_TRIGGERS

    engine = create_engine(_upgrade(tmp_path))
    with engine.connect() as connection:
        triggers = {row[0] for row in connection.execute(text(
            "SELECT name FROM sqlite_master WHERE type='trigger'"))}
    assert set(GATED_ROW_TRIGGERS) <= triggers
    engine.dispose()


def test_migration_does_not_alter_any_existing_table():
    """0011 must create new tables only: a batch rebuild of an existing
    SQLite table silently drops its triggers (see 0008's warning). The
    docstring MENTIONS batch_alter_table to explain exactly that, so the
    check is on executable lines, not on prose."""
    source = MIGRATION.read_text(encoding="utf-8")
    body = source.split('"""', 2)[-1]          # everything after the docstring
    for verb in ("batch_alter_table", "op.alter_column", "op.add_column"):
        assert verb not in body, f"0011 calls {verb} on an existing table"


def test_migration_is_rerunnable_over_its_own_output(tmp_path):
    url = _upgrade(tmp_path)
    assert _alembic(url, "downgrade", "0010").returncode == 0
    result = _alembic(url, "upgrade", "head")
    assert result.returncode == 0, result.stderr

    engine = create_engine(url)
    assert "company_impact" in set(inspect(engine).get_table_names())
    engine.dispose()


def test_models_and_0011_trigger_ddl_are_byte_identical():
    from app.models import V5_TRIGGER_DDL

    source = MIGRATION.read_text(encoding="utf-8")
    found = re.findall(r'^_[A-Z_]+_TRIGGER = """(.*?)"""', source,
                       flags=re.MULTILINE | re.DOTALL)
    assert len(found) == len(V5_TRIGGER_DDL), (
        f"0011 defines {len(found)} trigger literals, models.py exports "
        f"{len(V5_TRIGGER_DDL)}")
    normalize = lambda s: " ".join(s.split())  # noqa: E731
    assert [normalize(s) for s in found] == \
           [normalize(s) for s in V5_TRIGGER_DDL], (
        "the V5 trigger DDL in 0011 has drifted from app/models.py -- "
        "migrated and create_all-built DBs would enforce different rules")


def test_the_postgres_role_ddl_is_documented_for_the_port():
    """The phase file's Task 0.3 is Postgres role DDL. SQLite cannot express
    it; the substitution is only honest if the real DDL is recorded."""
    source = MIGRATION.read_text(encoding="utf-8")
    for needle in ("CREATE ROLE newsflo_reducer", "GRANT", "REVOKE"):
        assert needle in source


def test_create_all_and_the_migration_agree_on_the_v5_tables(tmp_path):
    """The suite builds its schema with create_all; production migrates.
    The two must produce the same V5 columns."""
    from app import models  # noqa: F401
    from app.db import Base

    migrated = create_engine(_upgrade(tmp_path))
    created = create_engine(f"sqlite:///{tmp_path / 'created.db'}")
    Base.metadata.create_all(created)

    for table in ("signal", "supported_version", "company_impact",
                  "firewall_deletion"):
        a = {c["name"] for c in inspect(migrated).get_columns(table)}
        b = {c["name"] for c in inspect(created).get_columns(table)}
        assert a == b, f"{table}: migration {sorted(a - b)} vs models {sorted(b - a)}"
    migrated.dispose()
    created.dispose()


def test_boot_asserts_the_v5_triggers(tmp_path):
    """tools/migrate_on_boot refuses to start when the Task 0.3 backstop is
    gone -- same discipline the §26 gated-row check already has, in a
    SEPARATE function over a SEPARATE trigger list."""
    from tools.migrate_on_boot import V5TriggersMissing, _assert_v5_triggers, check_v5_triggers

    url = _upgrade(tmp_path)
    assert check_v5_triggers(url)[0] == "ok"

    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("DROP TRIGGER company_impact_reducer_only_insert"))
    engine.dispose()

    status, missing = check_v5_triggers(url)
    assert status == "missing"
    assert "company_impact_reducer_only_insert" in missing
    try:
        _assert_v5_triggers(url, "sqlite")
    except V5TriggersMissing:
        pass
    else:                                        # pragma: no cover
        raise AssertionError("boot did not refuse an unguarded schema")


def test_the_gated_row_trigger_check_is_untouched():
    """The §26 list must keep policing exactly alert_companies -- the V5
    check is additive, not a replacement."""
    from tools.migrate_on_boot import GATED_ROW_TRIGGERS

    assert GATED_ROW_TRIGGERS == ("alert_companies_gated_consistency",
                                  "alert_companies_gated_consistency_insert")
