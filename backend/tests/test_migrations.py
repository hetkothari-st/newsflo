import subprocess, sys, tempfile, os
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _run_alembic(db_url):
    env = dict(os.environ, DATABASE_URL=db_url)
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND, env=env, capture_output=True, text=True)


def test_upgrade_head_on_empty_sqlite(tmp_path):
    url = f"sqlite:///{tmp_path/'fresh.db'}"
    result = _run_alembic(url)
    assert result.returncode == 0, result.stderr


def test_upgrade_head_is_idempotent(tmp_path):
    url = f"sqlite:///{tmp_path/'twice.db'}"
    assert _run_alembic(url).returncode == 0
    assert _run_alembic(url).returncode == 0


def test_upgrade_head_creates_evidence_table(tmp_path):
    """Corrective-v4 Task 5: the evidence_records table (0002) must exist
    on a fresh DB after `alembic upgrade head`, not only via create_all."""
    import sqlite3

    db = tmp_path / "evidence.db"
    url = f"sqlite:///{db}"
    result = _run_alembic(url)
    assert result.returncode == 0, result.stderr

    conn = sqlite3.connect(db)
    try:
        tables = {
            row[0] for row in
            conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()
    assert "evidence_records" in tables


def test_upgrade_head_adds_exposure_provenance_columns(tmp_path):
    """Corrective-v4 Task 6: the exposure self-certification fix's new
    company_node_exposures columns (0003) must exist on a fresh DB after
    `alembic upgrade head`, not only via create_all."""
    import sqlite3

    db = tmp_path / "provenance.db"
    url = f"sqlite:///{db}"
    result = _run_alembic(url)
    assert result.returncode == 0, result.stderr

    conn = sqlite3.connect(db)
    try:
        columns = {
            row[1] for row in
            conn.execute("PRAGMA table_info(company_node_exposures)")
        }
    finally:
        conn.close()
    for column in (
        "review_after", "source_type", "source_url", "source_date",
        "evidence_id", "verification_version",
    ):
        assert column in columns, f"missing company_node_exposures.{column}"


def test_upgrade_on_legacy_created_db(tmp_path):
    """A DB created by the old create_all/_ADDED_COLUMNS path must accept
    `alembic stamp baseline` + upgrade without error."""
    db = tmp_path / "legacy.db"
    url = f"sqlite:///{db}"
    env = dict(os.environ, DATABASE_URL=url)
    boot = subprocess.run(
        [sys.executable, "-c",
         "from app.db import init_db; init_db()"],
        cwd=BACKEND, env=env, capture_output=True, text=True)
    assert boot.returncode == 0, boot.stderr
    stamp = subprocess.run(
        [sys.executable, "-m", "alembic", "stamp", "0001"],
        cwd=BACKEND, env=env, capture_output=True, text=True)
    assert stamp.returncode == 0, stamp.stderr
    assert _run_alembic(url).returncode == 0
