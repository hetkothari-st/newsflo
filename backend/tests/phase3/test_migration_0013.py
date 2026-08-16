"""Migration 0013 -- ripple discovery schema, and the DDL-drift guards.

Same discipline as 0008/0011/0012: trigger, view and index DDL is
DUPLICATED between `app/models.py` (create_all -- the whole test suite and
every fresh dev DB) and the migration (production), because a migration must
never import app code that drifts underneath it. Drift is closed
mechanically by the byte-identity test below.
"""
import os
import subprocess
import sys
from pathlib import Path

import yaml
from sqlalchemy import create_engine, inspect, text

BACKEND = Path(__file__).resolve().parents[2]
MIGRATION = BACKEND / "alembic" / "versions" / "0013_v5_ripple_discovery.py"
TAGS_YAML = BACKEND / "config" / "exposure_tags.yaml"

RIPPLE_TABLES = ("valid_exposure_tag", "mechanism_edge", "io_coefficient",
                 "coverage_gap")
# valid_exposure_tag is the ONE exception: it is controlled vocabulary, and
# the migration populates it from config/exposure_tags.yaml by design.
EMPTY_TABLES = ("mechanism_edge", "io_coefficient", "coverage_gap")


def _alembic(db_url: str, *args: str):
    env = dict(os.environ, DATABASE_URL=db_url)
    return subprocess.run([sys.executable, "-m", "alembic", *args],
                          cwd=BACKEND, env=env, capture_output=True, text=True)


def _upgrade(tmp_path):
    url = f"sqlite:///{tmp_path / 'ripple.db'}"
    result = _alembic(url, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    return url


def test_the_migration_chains_from_0012():
    source = MIGRATION.read_text(encoding="utf-8")
    assert "down_revision = '0012'" in source or 'down_revision = "0012"' in source
    assert "revision = '0013'" in source or 'revision = "0013"' in source


def test_upgrade_head_creates_the_ripple_tables(tmp_path):
    engine = create_engine(_upgrade(tmp_path))
    assert set(RIPPLE_TABLES) <= set(inspect(engine).get_table_names())
    engine.dispose()


def test_the_migration_writes_no_row_except_the_vocabulary(tmp_path):
    """The ONE documented exception to Phase 3's empty-tables rule. A tag
    name is a word this system is allowed to use, not a claim about a
    company; every other table ships empty."""
    engine = create_engine(_upgrade(tmp_path))
    with engine.connect() as connection:
        for table in EMPTY_TABLES:
            count = connection.execute(
                text(f"SELECT count(*) FROM {table}")).scalar()
            assert count == 0, f"0013 seeded {count} row(s) into {table}"
        tags = {row[0] for row in connection.execute(text(
            "SELECT exposure_tag FROM valid_exposure_tag"))}
    expected = yaml.safe_load(TAGS_YAML.read_text(encoding="utf-8"))
    from app.ledger.exposure_tags import load_vocabulary
    assert tags == set(load_vocabulary().tags)
    assert expected["version"]
    engine.dispose()


def test_the_migration_installs_the_vocabulary_guard(tmp_path):
    engine = create_engine(_upgrade(tmp_path))
    with engine.connect() as connection:
        triggers = {row[0] for row in connection.execute(text(
            "SELECT name FROM sqlite_master WHERE type='trigger'"))}
        views = {row[0] for row in connection.execute(text(
            "SELECT name FROM sqlite_master WHERE type='view'"))}
        indexes = {row[0] for row in connection.execute(text(
            "SELECT name FROM sqlite_master WHERE type='index'"))}
    assert {"company_exposure_valid_tag_insert",
            "company_exposure_valid_tag_update",
            "mechanism_edge_valid_tag_insert",
            "mechanism_edge_valid_tag_update"} <= triggers
    assert "exposure_index" in views
    assert "ix_company_exposure_tag_share" in indexes
    engine.dispose()


def test_the_migration_leaves_every_earlier_trigger_installed(tmp_path):
    engine = create_engine(_upgrade(tmp_path))
    with engine.connect() as connection:
        triggers = {row[0] for row in connection.execute(text(
            "SELECT name FROM sqlite_master WHERE type='trigger'"))}
    assert {"alert_companies_gated_consistency",
            "alert_companies_gated_consistency_insert",
            "company_impact_reducer_only_insert",
            "signal_append_only_update",
            "company_exposure_review_only_insert",
            "company_exposure_review_only_delete"} <= triggers
    engine.dispose()


def test_the_migration_does_not_alter_any_existing_table():
    """Additive only. A SQLite batch rebuild silently drops a table's
    triggers, and `company_exposure` carries three of them."""
    from tests.phase3.conftest import code_lines

    for number, line in code_lines(MIGRATION):
        for forbidden in ("batch_alter_table", "add_column", "alter_column",
                          "drop_column"):
            assert forbidden not in line, f"0013:{number} uses {forbidden}"


def test_the_migration_is_rerunnable_over_its_own_output(tmp_path):
    url = _upgrade(tmp_path)
    assert _alembic(url, "downgrade", "0012").returncode == 0
    result = _alembic(url, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    engine = create_engine(url)
    assert set(RIPPLE_TABLES) <= set(inspect(engine).get_table_names())
    engine.dispose()


def test_models_and_0013_ddl_are_byte_identical():
    from app.models import V5_RIPPLE_DDL

    source = MIGRATION.read_text(encoding="utf-8")
    for statement in V5_RIPPLE_DDL:
        assert statement.strip() in source, (
            "a Phase 3 DDL statement in app/models.py is not present verbatim "
            f"in migration 0013:\n{statement}")


def test_the_postgres_materialized_view_ddl_is_documented_for_the_port():
    source = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE MATERIALIZED VIEW" in source
    assert "REFRESH MATERIALIZED VIEW CONCURRENTLY" in source


def test_create_all_and_the_migration_agree_on_the_ripple_tables(tmp_path):
    from app.db import Base
    from app import models  # noqa: F401

    migrated = create_engine(_upgrade(tmp_path))
    fresh = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    Base.metadata.create_all(fresh)
    try:
        for table in RIPPLE_TABLES:
            a = {c["name"] for c in inspect(migrated).get_columns(table)}
            b = {c["name"] for c in inspect(fresh).get_columns(table)}
            assert a == b, f"{table}: migration {sorted(a)} != models {sorted(b)}"
    finally:
        migrated.dispose()
        fresh.dispose()


def test_create_all_also_seeds_the_vocabulary(tmp_path):
    """A test database built with create_all must reject an unknown tag for
    the same reason a migrated one does -- otherwise the guard is a
    production-only promise."""
    from app.db import Base
    from app import models  # noqa: F401
    from app.ledger.exposure_tags import load_vocabulary

    engine = create_engine(f"sqlite:///{tmp_path / 'created.db'}")
    Base.metadata.create_all(engine)
    with engine.connect() as connection:
        tags = {row[0] for row in connection.execute(text(
            "SELECT exposure_tag FROM valid_exposure_tag"))}
    assert tags == set(load_vocabulary().tags)
    engine.dispose()


def test_the_boot_check_polices_the_vocabulary_guard(tmp_path):
    from tools.migrate_on_boot import RIPPLE_TRIGGERS, check_ripple_guard

    assert "company_exposure_valid_tag_insert" in RIPPLE_TRIGGERS

    url = _upgrade(tmp_path)
    assert check_ripple_guard(url) == ("ok", ())

    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text(
            "DROP TRIGGER company_exposure_valid_tag_insert"))
    engine.dispose()
    status, missing = check_ripple_guard(url)
    assert status == "missing"
    assert missing == ("company_exposure_valid_tag_insert",)


def test_boot_asserts_the_ripple_guard(tmp_path):
    import pytest

    from tools.migrate_on_boot import RippleGuardMissing, _assert_ripple_guard

    url = _upgrade(tmp_path)
    _assert_ripple_guard(url, "sqlite")          # does not raise
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("DROP TRIGGER mechanism_edge_valid_tag_insert"))
    engine.dispose()
    with pytest.raises(RippleGuardMissing):
        _assert_ripple_guard(url, "sqlite")
