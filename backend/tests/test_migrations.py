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


def test_upgrade_head_adds_market_integrity_columns(tmp_path):
    """Corrective-v4 Task 14: the market-integrity fix's new market_moves
    columns (0005) must exist on a fresh DB after `alembic upgrade head`,
    not only via create_all."""
    import sqlite3

    db = tmp_path / "integrity.db"
    url = f"sqlite:///{db}"
    result = _run_alembic(url)
    assert result.returncode == 0, result.stderr

    conn = sqlite3.connect(db)
    try:
        columns = {
            row[1] for row in
            conn.execute("PRAGMA table_info(market_moves)")
        }
    finally:
        conn.close()
    for column in ("data_quality", "session_state", "reaction_significance"):
        assert column in columns, f"missing market_moves.{column}"


def test_upgrade_head_adds_decision_record_completeness_columns(tmp_path):
    """Corrective-v4 Task 18: the decision-record completeness fix's new
    company_decision_records columns (0006) must exist on a fresh DB after
    `alembic upgrade head`, not only via create_all."""
    import sqlite3

    db = tmp_path / "decision_record.db"
    url = f"sqlite:///{db}"
    result = _run_alembic(url)
    assert result.returncode == 0, result.stderr

    conn = sqlite3.connect(db)
    try:
        columns = {
            row[1] for row in
            conn.execute("PRAGMA table_info(company_decision_records)")
        }
    finally:
        conn.close()
    for column in (
        "discovery_sources_json", "gate_inputs_json", "evidence_ids_json",
        "provider", "model", "analysis_quality", "correction_json",
    ):
        assert column in columns, f"missing company_decision_records.{column}"


def test_upgrade_head_adds_decision_record_composite_index_not_unique(tmp_path):
    """LEDGER RULING (Task 18, supersedes the plan's unique constraint on
    alert_id/ticker/analysis_version): duplicate-rejection rows ARE the
    audit trail, so 0006 adds a composite INDEX, never a UNIQUE constraint,
    on (alert_id, ticker) -- two rows with the same (alert_id, ticker) must
    insert cleanly."""
    import sqlite3

    db = tmp_path / "decision_index.db"
    url = f"sqlite:///{db}"
    assert _run_alembic(url).returncode == 0

    conn = sqlite3.connect(db)
    try:
        indexes = conn.execute("PRAGMA index_list(company_decision_records)").fetchall()
        by_name = {row[1]: row for row in indexes}
        assert "ix_decision_alert_ticker" in by_name
        # column[2] in PRAGMA index_list is the "unique" flag.
        assert by_name["ix_decision_alert_ticker"][2] == 0

        # Two rows sharing (alert_id, ticker) must insert without error --
        # the whole point of an index instead of a unique constraint here.
        conn.execute(
            "INSERT INTO articles (source, url, title, content, fetched_at, status) "
            "VALUES ('t','https://x','x','c', datetime('now'), 'ANALYZED')")
        article_id = conn.execute("SELECT id FROM articles").fetchone()[0]
        conn.execute(
            "INSERT INTO alerts (article_id, category, prompt_version, knowledge_version, "
            "refinement_attempts, created_at) "
            "VALUES (?, 'other', 'v1', 'v1', 0, datetime('now'))", (article_id,))
        alert_id = conn.execute("SELECT id FROM alerts").fetchone()[0]
        for _ in range(2):
            conn.execute(
                "INSERT INTO company_decision_records "
                "(alert_id, ticker, final_state, display_tier, created_at) "
                "VALUES (?, 'DUP.NS', 'REJECT_DUPLICATE', 'excluded', datetime('now'))",
                (alert_id,))
        conn.commit()
        count = conn.execute(
            "SELECT COUNT(*) FROM company_decision_records WHERE alert_id = ? AND ticker = 'DUP.NS'",
            (alert_id,)).fetchone()[0]
        assert count == 2
    finally:
        conn.close()


def test_upgrade_head_adds_alert_company_unique_constraint_and_impact_edge_index(tmp_path):
    """Corrective-v4 Task 18 (plan-gap carry): 0006 also adds
    UniqueConstraint(alert_id, company_id) on alert_companies and
    Index(impact_edges.alert_id)."""
    import sqlite3

    db = tmp_path / "constraints.db"
    url = f"sqlite:///{db}"
    assert _run_alembic(url).returncode == 0

    conn = sqlite3.connect(db)
    try:
        ac_indexes = conn.execute("PRAGMA index_list(alert_companies)").fetchall()
        assert any(row[2] == 1 for row in ac_indexes), "no unique index on alert_companies"

        edge_indexes = {row[1] for row in conn.execute("PRAGMA index_list(impact_edges)")}
        assert "ix_impact_edges_alert_id" in edge_indexes
    finally:
        conn.close()


def test_legacy_alert_companies_duplicates_deduped_on_upgrade(tmp_path):
    """Corrective-v4 Task 18: a legacy DB (built before 0006, so
    alert_companies never enforced (alert_id, company_id) uniqueness) may
    already carry duplicate rows for one candidate -- 0006 must dedupe them
    (keeping MAX(id)) BEFORE adding the constraint, or the upgrade itself
    would fail against real production data."""
    import sqlite3

    db = tmp_path / "legacy_dupes.db"
    url = f"sqlite:///{db}"
    env = dict(os.environ, DATABASE_URL=url)
    stamp0005 = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "0005"],
        cwd=BACKEND, env=env, capture_output=True, text=True)
    assert stamp0005.returncode == 0, stamp0005.stderr

    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT INTO articles (source, url, title, content, fetched_at, status) "
            "VALUES ('t','https://x','x','c', datetime('now'), 'ANALYZED')")
        article_id = conn.execute("SELECT id FROM articles").fetchone()[0]
        conn.execute(
            "INSERT INTO alerts (article_id, category, prompt_version, knowledge_version, "
            "refinement_attempts, created_at) "
            "VALUES (?, 'other', 'v1', 'v1', 0, datetime('now'))", (article_id,))
        alert_id = conn.execute("SELECT id FROM alerts").fetchone()[0]
        conn.execute(
            "INSERT INTO companies (ticker, name, sector, index_tier, tradeability) "
            "VALUES ('DUP.NS', 'Dup Co', 'other', 'OTHER', 'NORMAL')")
        company_id = conn.execute("SELECT id FROM companies").fetchone()[0]
        inserted_ids = []
        for _ in range(3):
            conn.execute(
                "INSERT INTO alert_companies "
                "(alert_id, company_id, direction, magnitude_low, magnitude_high, "
                "confidence_score, time_horizon, basis, confidence, impact_level) "
                "VALUES (?, ?, 'bullish', 1.0, 2.0, 50, 'Short-Term', 'direct_mention', "
                "'llm_estimate', 'direct')", (alert_id, company_id))
            inserted_ids.append(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        conn.commit()
        expected_survivor = max(inserted_ids)
        assert conn.execute(
            "SELECT COUNT(*) FROM alert_companies WHERE alert_id = ? AND company_id = ?",
            (alert_id, company_id)).fetchone()[0] == 3
    finally:
        conn.close()

    upgrade = _run_alembic(url)
    assert upgrade.returncode == 0, upgrade.stderr

    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT id FROM alert_companies WHERE alert_id = ? AND company_id = ?",
            (alert_id, company_id)).fetchall()
    finally:
        conn.close()
    assert [r[0] for r in rows] == [expected_survivor]


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
