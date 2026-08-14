import subprocess, sys, tempfile, os
from pathlib import Path

import pytest

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


def test_legacy_dedupe_repoints_fk_children_to_survivor(tmp_path):
    """Review-round finding (IMPORTANT): the pre-dedupe DELETE above
    orphans any child row still pointing at a deleted duplicate --
    CalibrationSample/CarOutcome/EmailNotification/AlertCompanyTranslation
    all carry ForeignKey("alert_companies.id"), and SQLite FK enforcement
    is off by default, so the DELETE would silently orphan them rather
    than error. 0006 must repoint every child row to the survivor first
    (or drop it, on a unique-constraint collision with a row the survivor
    already owns) before the duplicate rows are deleted."""
    import sqlite3

    db = tmp_path / "legacy_dupes_fk.db"
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
            "VALUES ('DUP2.NS', 'Dup Co 2', 'other', 'OTHER', 'NORMAL')")
        company_id = conn.execute("SELECT id FROM companies").fetchone()[0]
        inserted_ids = []
        for _ in range(2):
            conn.execute(
                "INSERT INTO alert_companies "
                "(alert_id, company_id, direction, magnitude_low, magnitude_high, "
                "confidence_score, time_horizon, basis, confidence, impact_level) "
                "VALUES (?, ?, 'bullish', 1.0, 2.0, 50, 'Short-Term', 'direct_mention', "
                "'llm_estimate', 'direct')", (alert_id, company_id))
            inserted_ids.append(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        conn.commit()
        survivor_id = max(inserted_ids)
        loser_id = min(inserted_ids)

        # A child row attached to the NON-survivor, on a child table whose
        # own unique constraint is (alert_company_id, horizon_days) --
        # not a collision case (the survivor has no calibration_samples
        # row at all yet), so this must simply be REPOINTED.
        conn.execute(
            "INSERT INTO calibration_samples "
            "(alert_company_id, category, company_id, direction, magnitude_actual, horizon_days, sampled_at) "
            "VALUES (?, 'other', ?, 'bullish', 2.0, 1, datetime('now'))",
            (loser_id, company_id))
        calibration_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # A car_outcomes row on EACH of the two duplicates -- that table's
        # unique constraint is on alert_company_id ALONE, so repointing
        # the loser's row onto the survivor MUST collide; the survivor's
        # own row must be the one that survives.
        conn.execute(
            "INSERT INTO car_outcomes (alert_company_id, company_id, category, "
            "day0_excess_move_pct, car_pct, computed_at) "
            "VALUES (?, ?, 'other', 99.0, 99.0, datetime('now'))", (survivor_id, company_id))
        survivor_car_outcome_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO car_outcomes (alert_company_id, company_id, category, "
            "day0_excess_move_pct, car_pct, computed_at) "
            "VALUES (?, ?, 'other', 1.0, 1.0, datetime('now'))", (loser_id, company_id))
        conn.commit()
    finally:
        conn.close()

    upgrade = _run_alembic(url)
    assert upgrade.returncode == 0, upgrade.stderr

    conn = sqlite3.connect(db)
    try:
        cal_rows = conn.execute(
            "SELECT id, alert_company_id FROM calibration_samples WHERE id = ?",
            (calibration_id,)).fetchall()
        assert cal_rows == [(calibration_id, survivor_id)], (
            "child row attached to the non-survivor must be repointed at the survivor")

        car_rows = conn.execute(
            "SELECT id, alert_company_id, day0_excess_move_pct FROM car_outcomes"
        ).fetchall()
        assert car_rows == [(survivor_car_outcome_id, survivor_id, 99.0)], (
            "on a unique-constraint collision the survivor's OWN row must win, "
            "the loser's dropped -- never the other way, and never both left in place")
    finally:
        conn.close()


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


def test_upgrade_head_adds_alert_company_materiality_grade(tmp_path):
    """Final-review finding I3: 0007 adds alert_companies.materiality_grade
    -- the COMPOSITE grade the publication gate evaluated. Without it,
    app.market.ripple_layers re-derived a grade from the naked
    `materiality` float and served HIGH for a candidate the gate had
    capped to MEDIUM."""
    import sqlite3

    db = tmp_path / "materiality_grade.db"
    url = f"sqlite:///{db}"
    result = _run_alembic(url)
    assert result.returncode == 0, result.stderr

    conn = sqlite3.connect(db)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(alert_companies)")}
    finally:
        conn.close()
    assert "materiality_grade" in columns


# ===========================================================================
# 0008 -- final blueprint: new columns, tier rewrite, contradiction repair,
# gated-row trigger backstop, alert idempotency key
# ===========================================================================


def _seed_legacy_alert(conn, *, url, ticker):
    """One article + alert + company on a DB stamped at 0007. Returns
    (alert_id, company_id)."""
    conn.execute(
        "INSERT INTO articles (source, url, title, content, fetched_at, status) "
        "VALUES ('t', ?, 'x', 'c', datetime('now'), 'ANALYZED')", (url,))
    article_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO alerts (article_id, category, prompt_version, knowledge_version, "
        "refinement_attempts, created_at) "
        "VALUES (?, 'commodity', 'v1', 'v1', 0, datetime('now'))", (article_id,))
    alert_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO companies (ticker, name, sector, index_tier, tradeability) "
        "VALUES (?, 'Co', 'oil_gas', 'NIFTY500', 'NORMAL')", (ticker,))
    company_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    return alert_id, company_id


def _insert_alert_company(conn, alert_id, company_id, **overrides):
    values = {
        "direction": "bullish", "magnitude_low": 1.0, "magnitude_high": 2.0,
        "rationale": "r", "confidence_score": 50, "time_horizon": "Short-Term",
        "basis": "direct_mention", "confidence": "llm_estimate",
        "impact_level": "direct", "economic_effect": None,
        "display_tier": None, "gate_state": None,
    }
    values.update(overrides)
    columns = ["alert_id", "company_id", *values]
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO alert_companies ({', '.join(columns)}) VALUES ({placeholders})",
        (alert_id, company_id, *values.values()))
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _upgrade_to(url, revision):
    env = dict(os.environ, DATABASE_URL=url)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=BACKEND, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_upgrade_head_adds_blueprint_columns(tmp_path):
    """Blueprint §21/§22: discovery, causality and evidence stop being
    overloaded onto `basis` -- each gets its own column, plus the edge's
    own controlled relation type. All nullable: the legacy corpus has none
    of them and must stay honestly NULL."""
    import sqlite3

    db = tmp_path / "blueprint_columns.db"
    result = _run_alembic(f"sqlite:///{db}")
    assert result.returncode == 0, result.stderr

    conn = sqlite3.connect(db)
    try:
        ac = {r[1] for r in conn.execute("PRAGMA table_info(alert_companies)")}
        dr = {r[1] for r in conn.execute("PRAGMA table_info(company_decision_records)")}
        alerts = {r[1] for r in conn.execute("PRAGMA table_info(alerts)")}
    finally:
        conn.close()

    for column in ("causal_directness", "discovery_source", "evidence_source",
                   "edge_relation", "confidence_band"):
        assert column in ac, f"missing alert_companies.{column}"
    assert "causal_directness" in dr, "missing company_decision_records.causal_directness"
    assert "content_key" in alerts, "missing alerts.content_key"


def test_0008_rewrites_legacy_secondary_tiers(tmp_path):
    """Ruling R3: SECONDARY_RIPPLE is the one secondary tier name. Rows
    written as 'secondary_deep_dive' (V4) or 'secondary' (pre-Task-4) are
    the SAME tier under two dead names -- a reader-facing filter on the new
    name would silently drop them, so the data is rewritten, not
    dual-read."""
    import sqlite3

    db = tmp_path / "tier_rewrite.db"
    url = f"sqlite:///{db}"
    _upgrade_to(url, "0007")

    conn = sqlite3.connect(db)
    try:
        alert_id, company_id = _seed_legacy_alert(
            conn, url="https://example.test/tier", ticker="TIER1.NS")
        deep_dive_id = _insert_alert_company(
            conn, alert_id, company_id, display_tier="secondary_deep_dive",
            gate_state="DISPLAY_ELIGIBLE")
        _, company2_id = _seed_legacy_alert(
            conn, url="https://example.test/tier2", ticker="TIER2.NS")
        legacy_secondary_id = _insert_alert_company(
            conn, alert_id, company2_id, display_tier="secondary",
            gate_state="DISPLAY_ELIGIBLE")
        primary_id = _insert_alert_company(
            conn, alert_id, company_id + 1000, display_tier="primary",
            gate_state="DISPLAY_ELIGIBLE")
        for tier in ("secondary_deep_dive", "secondary", "primary"):
            conn.execute(
                "INSERT INTO company_decision_records "
                "(alert_id, ticker, final_state, display_tier, created_at) "
                "VALUES (?, ?, 'DISPLAY_ELIGIBLE', ?, datetime('now'))",
                (alert_id, f"{tier}.NS", tier))
        conn.commit()
    finally:
        conn.close()

    assert _run_alembic(url).returncode == 0

    conn = sqlite3.connect(db)
    try:
        tiers = dict(conn.execute(
            "SELECT id, display_tier FROM alert_companies"))
        assert tiers[deep_dive_id] == "secondary_ripple"
        assert tiers[legacy_secondary_id] == "secondary_ripple"
        assert tiers[primary_id] == "primary", "primary must be untouched"

        dr_tiers = dict(conn.execute(
            "SELECT ticker, display_tier FROM company_decision_records"))
        assert dr_tiers["secondary_deep_dive.NS"] == "secondary_ripple"
        assert dr_tiers["secondary.NS"] == "secondary_ripple"
        assert dr_tiers["primary.NS"] == "primary"
    finally:
        conn.close()


def test_0008_repairs_contradictory_gated_rows(tmp_path):
    """Blueprint §4, the live OIL.NS row: a GATED row whose `direction`
    contradicts its authoritative `economic_effect` is repaired in place
    (direction derived from effect), because the trigger installed in the
    same migration would otherwise make that row permanently unwritable."""
    import sqlite3

    db = tmp_path / "contradiction.db"
    url = f"sqlite:///{db}"
    _upgrade_to(url, "0007")

    conn = sqlite3.connect(db)
    try:
        alert_id, company_id = _seed_legacy_alert(
            conn, url="https://example.test/oil", ticker="OIL.NS")
        # The real contradiction: positive fundamentals, bearish badge.
        bad_positive = _insert_alert_company(
            conn, alert_id, company_id, direction="bearish",
            economic_effect="positive", gate_state="DISPLAY_ELIGIBLE",
            display_tier="primary")
        bad_negative = _insert_alert_company(
            conn, alert_id, company_id + 1, direction="bullish",
            economic_effect="negative", gate_state="DISPLAY_ELIGIBLE",
            display_tier="primary")
        # Ungated legacy row with the SAME contradiction -- untouched: it
        # has no gate semantics and the trigger will never fire on it.
        legacy = _insert_alert_company(
            conn, alert_id, company_id + 2, direction="bearish",
            economic_effect="positive", gate_state=None)
        # A gated row whose effect is not directional -- never rewritten.
        mixed = _insert_alert_company(
            conn, alert_id, company_id + 3, direction="bearish",
            economic_effect="mixed", gate_state="DISPLAY_ELIGIBLE",
            display_tier="primary")
        conn.commit()
    finally:
        conn.close()

    assert _run_alembic(url).returncode == 0

    conn = sqlite3.connect(db)
    try:
        rows = dict(conn.execute("SELECT id, direction FROM alert_companies"))
    finally:
        conn.close()
    assert rows[bad_positive] == "bullish"
    assert rows[bad_negative] == "bearish"
    assert rows[legacy] == "bearish", "ungated legacy row must not be rewritten"
    assert rows[mixed] == "bearish", "non-directional effect must not be rewritten"


def test_0008_installs_gated_consistency_triggers(tmp_path):
    """§26 backstop: the triggers must exist on a migrated DB (the
    create_all half of the same guarantee is pinned in
    tests/test_gated_row_immutability.py), and must actually refuse the
    write that the stale pre-V4 worker performed."""
    import sqlite3

    db = tmp_path / "triggers.db"
    url = f"sqlite:///{db}"
    assert _run_alembic(url).returncode == 0

    conn = sqlite3.connect(db)
    try:
        triggers = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'")}
        assert "alert_companies_gated_consistency" in triggers
        assert "alert_companies_gated_consistency_insert" in triggers

        alert_id, company_id = _seed_legacy_alert(
            conn, url="https://example.test/trig", ticker="TRIG.NS")
        row_id = _insert_alert_company(
            conn, alert_id, company_id, direction="bullish",
            economic_effect="positive", gate_state="DISPLAY_ELIGIBLE",
            display_tier="primary")
        conn.commit()

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE alert_companies SET direction = 'bearish' WHERE id = ?",
                (row_id,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE alert_companies SET rationale = NULL WHERE id = ?",
                (row_id,))
        conn.rollback()
        assert conn.execute(
            "SELECT direction FROM alert_companies WHERE id = ?",
            (row_id,)).fetchone()[0] == "bullish"
    finally:
        conn.close()


def test_0008_adds_partial_unique_content_key_index(tmp_path):
    """§26 idempotency: two processes persisting the identical analysis of
    the identical article must collide. PARTIAL on purpose -- the legacy
    corpus has NULL content_key and multiple alerts per article."""
    import sqlite3

    db = tmp_path / "content_key.db"
    url = f"sqlite:///{db}"
    assert _run_alembic(url).returncode == 0

    conn = sqlite3.connect(db)
    try:
        indexes = {r[1]: r for r in conn.execute("PRAGMA index_list(alerts)")}
        assert "uq_alerts_article_content" in indexes
        # PRAGMA index_list columns: (seq, name, unique, origin, partial).
        assert indexes["uq_alerts_article_content"][2] == 1, "index must be UNIQUE"
        assert indexes["uq_alerts_article_content"][4] == 1, (
            "index must be PARTIAL (WHERE content_key IS NOT NULL), not a "
            "plain unique index over the whole table -- the legacy corpus "
            "has many NULL-key alerts per article")

        conn.execute(
            "INSERT INTO articles (source, url, title, content, fetched_at, status) "
            "VALUES ('t','https://example.test/ck','x','c', datetime('now'), 'ANALYZED')")
        article_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()

        def _insert(content_key):
            conn.execute(
                "INSERT INTO alerts (article_id, category, refinement_attempts, "
                "created_at, content_key) VALUES (?, 'commodity', 0, datetime('now'), ?)",
                (article_id, content_key))
            conn.commit()

        _insert("key-1")
        with pytest.raises(sqlite3.IntegrityError):
            _insert("key-1")
        conn.rollback()

        # A different key, and any number of NULL-key rows, coexist.
        _insert("key-2")
        _insert(None)
        _insert(None)
        assert conn.execute(
            "SELECT COUNT(*) FROM alerts WHERE article_id = ?",
            (article_id,)).fetchone()[0] == 4
    finally:
        conn.close()


def test_0008_is_rerunnable_over_its_own_output(tmp_path):
    """Same guard discipline as 0002-0007: 0008's own statements must
    survive being replayed over a database they have ALREADY been applied
    to -- which is what the boot path effectively does whenever a DB is
    re-stamped or restored behind head.

    Note the `alembic stamp 0007` in the middle: without it the second
    `upgrade head` is a no-op (the DB is already at 0008 and alembic simply
    skips the revision), so it would prove nothing at all. Stamping back to
    0007 makes alembic genuinely RE-EXECUTE 0008's body against a database
    that already carries every column, index and trigger it creates."""
    import sqlite3

    db = tmp_path / "rerun_0008.db"
    url = f"sqlite:///{db}"
    assert _run_alembic(url).returncode == 0

    env = dict(os.environ, DATABASE_URL=url)
    stamp_back = subprocess.run(
        [sys.executable, "-m", "alembic", "stamp", "0007"],
        cwd=BACKEND, env=env, capture_output=True, text=True)
    assert stamp_back.returncode == 0, stamp_back.stderr
    assert _current_revision(db) == {"0007"}, "fixture precondition: 0008 will re-run"

    second = _run_alembic(url)
    assert second.returncode == 0, second.stderr
    assert _current_revision(db) == _head_revision()

    conn = sqlite3.connect(db)
    try:
        triggers = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'")}
        indexes = {r[1] for r in conn.execute("PRAGMA index_list(alerts)")}
        ac = {r[1] for r in conn.execute("PRAGMA table_info(alert_companies)")}
    finally:
        conn.close()
    assert "alert_companies_gated_consistency" in triggers
    assert "alert_companies_gated_consistency_insert" in triggers
    assert "uq_alerts_article_content" in indexes
    assert "edge_relation" in ac


def _normalized_sql(statement: str) -> str:
    """Whitespace-insensitive comparison: the two copies live in files with
    different indentation conventions, and only the SQL must match."""
    return " ".join(statement.split())


def test_models_and_0008_trigger_ddl_are_byte_identical():
    """Fix-round finding 1: the §26 trigger SQL is DUPLICATED between
    app/models.py (the create_all DDL hook) and 0008 (production DBs),
    because a migration must never import app code that drifts underneath
    it. Nothing but this test stops the two copies from silently diverging
    -- which would leave migrated databases and create_all-built databases
    (i.e. production and the entire test suite) enforcing different rules,
    the exact class of gap where a §26 violation hides.

    0008's source is read as TEXT rather than imported: importing a
    migration module executes alembic's revision bookkeeping, and the point
    is to compare the file as it will actually be replayed."""
    import re

    from app.models import GATED_ROW_TRIGGER_DDL

    source = (BACKEND / "alembic" / "versions" /
              "0008_three_tier_blueprint.py").read_text(encoding="utf-8")
    found = re.findall(
        r'^_(?:UPDATE|INSERT)_TRIGGER = """(.*?)"""', source,
        flags=re.MULTILINE | re.DOTALL)
    assert len(found) == 2, (
        "0008 must define exactly _UPDATE_TRIGGER and _INSERT_TRIGGER as "
        f"module-level triple-quoted literals; found {len(found)}")

    assert [_normalized_sql(s) for s in found] == \
           [_normalized_sql(s) for s in GATED_ROW_TRIGGER_DDL], (
        "the trigger DDL in alembic/versions/0008_three_tier_blueprint.py "
        "has drifted from app/models.py's GATED_ROW_TRIGGER_DDL -- change "
        "BOTH or migrated and create_all-built DBs will enforce different "
        "gated-row rules")


def test_batch_recreating_alert_companies_drops_the_triggers(tmp_path):
    """Fix-round finding 1, the latent hazard itself, pinned as executable
    documentation: SQLite drops every trigger attached to a dropped table,
    and Alembic's batch_alter_table implements a SQLite ALTER by rebuilding
    the table -- so a future migration that batch-alters alert_companies
    silently takes the whole §26 backstop with it, leaving a schema that
    LOOKS correct.

    This test asserts the failure mode is real (so nobody 'fixes' the
    warning blocks in models.py / 0008 by deleting them), and that
    re-emitting the exported DDL restores the guarantee -- the remedy those
    warnings prescribe."""
    from sqlalchemy import create_engine, text as sa_text

    from app.models import emit_gated_row_triggers

    db = tmp_path / "batch_rebuild.db"
    url = f"sqlite:///{db}"
    assert _run_alembic(url).returncode == 0

    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            before = {r[0] for r in conn.execute(sa_text(
                "SELECT name FROM sqlite_master WHERE type='trigger'"))}
            assert "alert_companies_gated_consistency" in before

            # Exactly what a batch rebuild does to the table.
            conn.execute(sa_text(
                "CREATE TABLE ac_rebuilt AS SELECT * FROM alert_companies"))
            conn.execute(sa_text("DROP TABLE alert_companies"))
            conn.execute(sa_text(
                "ALTER TABLE ac_rebuilt RENAME TO alert_companies"))

            after = {r[0] for r in conn.execute(sa_text(
                "SELECT name FROM sqlite_master WHERE type='trigger'"))}
            assert "alert_companies_gated_consistency" not in after, (
                "if this ever stops being true the warning blocks can go")

            # The prescribed remedy: re-emit at the end of the batch op.
            assert emit_gated_row_triggers(conn) is True
            restored = {r[0] for r in conn.execute(sa_text(
                "SELECT name FROM sqlite_master WHERE type='trigger'"))}
        assert "alert_companies_gated_consistency" in restored
        assert "alert_companies_gated_consistency_insert" in restored
    finally:
        engine.dispose()


# ===========================================================================
# migrate_on_boot: the ONE place migrations actually run in production
# ===========================================================================
# Final-review blocker C1: nothing in the deploy path ever ran
# `alembic upgrade head` -- the Dockerfile started uvicorn directly and
# init_db()'s _ADDED_COLUMNS is frozen, so every column added by 0002+ was
# simply absent against a PRE-EXISTING database while the code wrote it
# unconditionally. backend/tools/migrate_on_boot.py closes that, and the
# Dockerfile now runs it before uvicorn.


def _boot(db_url):
    env = dict(os.environ, DATABASE_URL=db_url)
    return subprocess.run(
        [sys.executable, "tools/migrate_on_boot.py"],
        cwd=BACKEND, env=env, capture_output=True, text=True)


def _current_revision(db_path):
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        return {row[0] for row in conn.execute("SELECT version_num FROM alembic_version")}
    finally:
        conn.close()


def _head_revision():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    return set(ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini"))).get_heads())


def test_migrate_on_boot_builds_an_empty_db_to_head(tmp_path):
    """State 3 (empty DB): nothing exists at all -- build the whole schema
    from the migrations."""
    db = tmp_path / "boot_empty.db"
    result = _boot(f"sqlite:///{db}")
    assert result.returncode == 0, result.stderr
    assert db.exists()
    assert _current_revision(db) == _head_revision()


def test_migrate_on_boot_adopts_a_legacy_init_db_database(tmp_path):
    """State 2 (legacy DB): a database created by the pre-Alembic
    create_all/_ADDED_COLUMNS path has core tables but no alembic_version.
    Running the baseline's CREATE TABLEs against it would fail, so it must
    be STAMPED at 0001 first and then upgraded -- and it must end up with
    the columns 0002+ add, which is the whole production failure this
    closes."""
    import sqlite3

    db = tmp_path / "boot_legacy.db"
    url = f"sqlite:///{db}"
    env = dict(os.environ, DATABASE_URL=url)
    legacy = subprocess.run(
        [sys.executable, "-c", "from app.db import init_db; init_db()"],
        cwd=BACKEND, env=env, capture_output=True, text=True)
    assert legacy.returncode == 0, legacy.stderr

    conn = sqlite3.connect(db)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert "alerts" in tables, "fixture precondition: legacy DB has core tables"
    assert "alembic_version" not in tables, "fixture precondition: not alembic-managed yet"

    result = _boot(url)
    assert result.returncode == 0, result.stderr
    assert _current_revision(db) == _head_revision()

    conn = sqlite3.connect(db)
    try:
        mm = {r[1] for r in conn.execute("PRAGMA table_info(market_moves)")}
        ac = {r[1] for r in conn.execute("PRAGMA table_info(alert_companies)")}
    finally:
        conn.close()
    # Columns the running code writes flag-independently -- the exact
    # "no such column" crash C1 describes.
    for column in ("data_quality", "session_state", "reaction_significance"):
        assert column in mm, f"missing market_moves.{column} after boot migration"
    assert "materiality_grade" in ac


def test_migrate_on_boot_adopts_a_table_incomplete_legacy_db(tmp_path):
    """First real-world sync (newsflo-local, 2026-08-14): a legacy DB can
    be missing whole TABLES too, not just columns -- this one predated
    company_decision_records, and 0006's column reflection crashed with
    NoSuchTableError because stamping skips 0001's CREATE TABLEs. The
    boot path must create_all missing tables before upgrading."""
    import sqlite3

    db = tmp_path / "boot_legacy_incomplete.db"
    url = f"sqlite:///{db}"
    env = dict(os.environ, DATABASE_URL=url)
    legacy = subprocess.run(
        [sys.executable, "-c", "from app.db import init_db; init_db()"],
        cwd=BACKEND, env=env, capture_output=True, text=True)
    assert legacy.returncode == 0, legacy.stderr

    conn = sqlite3.connect(db)
    try:
        conn.execute("DROP TABLE company_decision_records")
        conn.execute("DROP TABLE evidence_records")
        conn.commit()
    finally:
        conn.close()

    result = _boot(url)
    assert result.returncode == 0, result.stderr
    assert _current_revision(db) == _head_revision()

    conn = sqlite3.connect(db)
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        dr = {r[1] for r in conn.execute(
            "PRAGMA table_info(company_decision_records)")}
    finally:
        conn.close()
    assert "company_decision_records" in tables
    assert "evidence_records" in tables
    # Recreated table carries the current-model shape including 0006's
    # completeness columns; the guarded migrations no-op over it.
    assert "gate_inputs_json" in dr


def test_migrate_on_boot_on_an_already_migrated_db_is_a_noop(tmp_path):
    """State 1 (managed DB), already at head: exits 0, stays at head."""
    db = tmp_path / "boot_managed.db"
    url = f"sqlite:///{db}"
    assert _run_alembic(url).returncode == 0
    before = _current_revision(db)

    result = _boot(url)
    assert result.returncode == 0, result.stderr
    assert _current_revision(db) == before == _head_revision()


def test_migrate_on_boot_upgrades_a_partially_migrated_db(tmp_path):
    """State 1 (managed DB), BEHIND head -- a real deploy of new code onto
    a DB migrated by the previous release."""
    db = tmp_path / "boot_partial.db"
    url = f"sqlite:///{db}"
    env = dict(os.environ, DATABASE_URL=url)
    partial = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "0005"],
        cwd=BACKEND, env=env, capture_output=True, text=True)
    assert partial.returncode == 0, partial.stderr
    assert _current_revision(db) == {"0005"}

    result = _boot(url)
    assert result.returncode == 0, result.stderr
    assert _current_revision(db) == _head_revision()


def test_migrate_on_boot_is_idempotent_across_all_three_states(tmp_path):
    """Boot runs on EVERY container start, including restart loops. Each
    entry state must survive being migrated repeatedly."""
    empty = tmp_path / "idem_empty.db"
    assert _boot(f"sqlite:///{empty}").returncode == 0
    assert _boot(f"sqlite:///{empty}").returncode == 0
    assert _current_revision(empty) == _head_revision()

    legacy = tmp_path / "idem_legacy.db"
    legacy_url = f"sqlite:///{legacy}"
    env = dict(os.environ, DATABASE_URL=legacy_url)
    assert subprocess.run(
        [sys.executable, "-c", "from app.db import init_db; init_db()"],
        cwd=BACKEND, env=env, capture_output=True, text=True).returncode == 0
    assert _boot(legacy_url).returncode == 0
    assert _boot(legacy_url).returncode == 0
    assert _boot(legacy_url).returncode == 0
    assert _current_revision(legacy) == _head_revision()


def test_dockerfile_runs_migrations_before_uvicorn():
    """The script only helps if the deploy path actually calls it. Pinned
    against the Dockerfile itself: this is the regression that shipped
    18 unreachable columns to production."""
    dockerfile = (BACKEND.parent / "Dockerfile").read_text(encoding="utf-8")
    cmd = [line for line in dockerfile.splitlines() if line.startswith("CMD")]
    assert len(cmd) == 1, cmd
    assert "tools/migrate_on_boot.py" in cmd[0]
    assert cmd[0].index("migrate_on_boot.py") < cmd[0].index("uvicorn"), (
        "migrations must run BEFORE the server starts")
    assert "&&" in cmd[0], (
        "a failed migration must abort the container, never fall through to uvicorn")
