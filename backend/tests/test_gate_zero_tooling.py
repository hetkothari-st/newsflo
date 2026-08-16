"""V5 SESSION 0 -- Gate Zero tooling tests (written BEFORE the tooling).

Covers the four deliverables of docs/v5/CLAUDE_CODE_PROMPTS.md "SESSION 0":
migration 0010's eval schema, the standalone labeling UI, the offline
CSV/JSON importer, and scripts/score_baseline.py.

The load-bearing tests here are the NEGATIVE ones, in the spirit of
docs/v5/00_MASTER_CONTEXT.md's fabrication guard:

  * the scorer must FAIL LOUDLY on an empty corpus -- never report 0% or
    100% over zero labels (that is the single test the session prompt
    calls out by name);
  * the scorer must not be able to reach an LLM at all (static import scan
    + a subprocess proving no provider module lands in sys.modules);
  * the labeling UI must serve the article and NOTHING the system
    produced -- one leaked ticker anchors the labeler and destroys the
    label's value (08_PHASE_7 labeling protocol);
  * fixture data must never reach a production table.
"""
import ast
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DatabaseError

BACKEND = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND.parent
FIXTURES = BACKEND / "tests" / "fixtures" / "eval"

EVAL_TABLES = ("eval_event", "eval_label", "eval_event_label", "eval_adjudication")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _run_alembic(db_url):
    env = dict(os.environ, DATABASE_URL=db_url)
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND, env=env, capture_output=True, text=True)


@pytest.fixture()
def eval_db(tmp_path):
    """A file-backed SQLite DB carrying BOTH the production schema (so the
    scorer has alerts/alert_companies/articles to read) and the eval
    schema. File-backed, not in-memory, because several tests drive the
    CLIs in a subprocess against the same URL."""
    from app.db import Base
    from app import models  # noqa: F401  registers the production tables
    from app.eval.schema import create_eval_tables

    path = tmp_path / "gate_zero.db"
    url = f"sqlite:///{path.as_posix()}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    create_eval_tables(engine)
    return SimpleNamespace(engine=engine, url=url, path=path)


def _seed_article(conn, *, article_id, title, body, url):
    conn.execute(text(
        "INSERT INTO articles (id, source, url, title, content, status, fetched_at) "
        "VALUES (:i, 'FixtureWire', :u, :t, :c, 'ANALYZED', :f)"
    ), {"i": article_id, "u": url, "t": title, "c": body,
        "f": datetime(2026, 8, 1, tzinfo=timezone.utc)})


def _seed_company(conn, *, company_id, ticker, name, sector, sub_sector=None):
    conn.execute(text(
        "INSERT INTO companies (id, ticker, name, sector, sub_sector, index_tier, "
        "market, tradeability) VALUES (:i, :tk, :n, :s, :ss, 'NIFTY500', 'INDIA', 'NORMAL')"
    ), {"i": company_id, "tk": ticker, "n": name, "s": sector, "ss": sub_sector})


def _seed_alert(conn, *, alert_id, article_id, facts=None):
    conn.execute(text(
        "INSERT INTO alerts (id, article_id, category, created_at, facts, refinement_attempts) "
        "VALUES (:i, :a, 'Energy', :c, :f, 0)"
    ), {"i": alert_id, "a": article_id, "c": datetime(2026, 8, 1, tzinfo=timezone.utc),
        "f": facts})


def _seed_alert_company(conn, *, alert_id, company_id, direction, display_tier=None,
                        economic_effect=None, gate_state=None, mechanism=None,
                        rationale=None, why=None, causal_distance=None,
                        impact_level="direct"):
    conn.execute(text(
        "INSERT INTO alert_companies (alert_id, company_id, direction, magnitude_low, "
        "magnitude_high, confidence_score, time_horizon, basis, confidence, impact_level, "
        "display_tier, gate_state, economic_effect, mechanism, rationale, why, causal_distance) "
        "VALUES (:al, :co, :d, 1.0, 2.0, 70, 'Short-Term', 'direct_mention', 'llm_estimate', "
        ":il, :dt, :gs, :ee, :me, :ra, :wh, :cd)"
    ), {"al": alert_id, "co": company_id, "d": direction, "il": impact_level,
        "dt": display_tier, "gs": gate_state, "ee": economic_effect, "me": mechanism,
        "ra": rationale, "wh": why, "cd": causal_distance})


def _score(db, tmp_path, extra=()):
    out = tmp_path / "BASELINE_test.md"
    proc = subprocess.run(
        [sys.executable, "scripts/score_baseline.py", "--db", db.url,
         "--out", str(out), "--commit", "deadbeef", "--date", "2026-08-17", *extra],
        cwd=BACKEND, capture_output=True, text=True,
        env=dict(os.environ, ENABLE_SCHEDULER="false"))
    return proc, out


# ---------------------------------------------------------------------------
# 1. migration 0010
# ---------------------------------------------------------------------------

def test_migration_creates_the_four_eval_tables(tmp_path):
    db = tmp_path / "m.db"
    result = _run_alembic(f"sqlite:///{db.as_posix()}")
    assert result.returncode == 0, result.stderr

    import sqlite3
    conn = sqlite3.connect(db)
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    for name in EVAL_TABLES:
        assert name in tables, f"{name} missing after `alembic upgrade head`"


def test_migration_is_idempotent(tmp_path):
    url = f"sqlite:///{(tmp_path / 'twice.db').as_posix()}"
    assert _run_alembic(url).returncode == 0
    assert _run_alembic(url).returncode == 0


def test_migration_ships_empty_tables(tmp_path):
    """The fabrication guard, as a test: 0010 creates schema, never data."""
    db = tmp_path / "empty.db"
    assert _run_alembic(f"sqlite:///{db.as_posix()}").returncode == 0

    import sqlite3
    conn = sqlite3.connect(db)
    try:
        for name in EVAL_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] == 0
    finally:
        conn.close()


def test_migration_leaves_the_gated_row_triggers_installed(tmp_path):
    """0008's §26 backstop triggers live on alert_companies, and SQLite
    drops every trigger on a batch_alter_table rebuild. 0010 must not touch
    that table at all."""
    from tools.migrate_on_boot import GATED_ROW_TRIGGERS

    db = tmp_path / "trig.db"
    assert _run_alembic(f"sqlite:///{db.as_posix()}").returncode == 0

    import sqlite3
    conn = sqlite3.connect(db)
    try:
        triggers = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'")}
    finally:
        conn.close()
    for name in GATED_ROW_TRIGGERS:
        assert name in triggers


def test_migration_schema_matches_the_declared_metadata(tmp_path):
    """The migration DDL and app/eval/schema.py must not drift apart."""
    from app.eval.schema import create_eval_tables

    migrated = tmp_path / "mig.db"
    assert _run_alembic(f"sqlite:///{migrated.as_posix()}").returncode == 0

    declared = tmp_path / "declared.db"
    create_eval_tables(create_engine(f"sqlite:///{declared.as_posix()}"))

    import sqlite3

    def columns(path):
        conn = sqlite3.connect(path)
        try:
            return {t: [r[1] for r in conn.execute(f"PRAGMA table_info({t})")]
                    for t in EVAL_TABLES}
        finally:
            conn.close()

    assert columns(migrated) == columns(declared)


def test_eval_tables_are_not_in_the_production_metadata():
    """app.db.Base.metadata drives init_db()'s create_all in production.
    The eval tables carry their own MetaData so nothing about the running
    app changes."""
    from app.db import Base
    from app import models  # noqa: F401

    for name in EVAL_TABLES:
        assert name not in Base.metadata.tables


@pytest.mark.parametrize("column,value,table,payload", [
    ("stratum", "not_a_stratum", "eval_event",
     "INSERT INTO eval_event (event_id, stratum, article_ref) VALUES ('e1', :v, 'a')"),
    ("expected_tier", "SORT_OF_PRIMARY", "eval_label",
     "INSERT INTO eval_label (event_id, company_ref, labeler, expected_tier) "
     "VALUES ('e1', 'X', 'l', :v)"),
    ("resolution", "MAYBE", "eval_adjudication",
     "INSERT INTO eval_adjudication (event_id, company_ref, resolution) "
     "VALUES ('e1', 'X', :v)"),
])
def test_check_constraints_reject_unknown_vocabulary(tmp_path, column, value, table, payload):
    db = tmp_path / "ck.db"
    assert _run_alembic(f"sqlite:///{db.as_posix()}").returncode == 0
    engine = create_engine(f"sqlite:///{db.as_posix()}")
    with engine.begin() as conn:
        with pytest.raises(DatabaseError):
            conn.execute(text(payload), {"v": value})


def test_check_constraints_accept_the_declared_vocabulary(tmp_path):
    from app.eval.schema import STRATA, EXPECTED_TIERS, RESOLUTIONS

    db = tmp_path / "ok.db"
    assert _run_alembic(f"sqlite:///{db.as_posix()}").returncode == 0
    engine = create_engine(f"sqlite:///{db.as_posix()}")
    with engine.begin() as conn:
        for i, stratum in enumerate(STRATA):
            conn.execute(text(
                "INSERT INTO eval_event (event_id, stratum, article_ref) "
                "VALUES (:e, :s, 'ref')"), {"e": f"e{i}", "s": stratum})
        for i, tier in enumerate(EXPECTED_TIERS):
            conn.execute(text(
                "INSERT INTO eval_label (event_id, company_ref, labeler, expected_tier) "
                "VALUES ('e0', :c, 'l', :t)"), {"c": f"C{i}", "t": tier})
        for i, res in enumerate(RESOLUTIONS):
            conn.execute(text(
                "INSERT INTO eval_adjudication (event_id, company_ref, resolution) "
                "VALUES ('e0', :c, :r)"), {"c": f"C{i}", "r": res})


# ---------------------------------------------------------------------------
# 2. importer
# ---------------------------------------------------------------------------

def test_importer_round_trip_and_idempotency(eval_db):
    from tools.eval_import import run_import

    first = run_import(eval_db.engine,
                       events=FIXTURES / "events.csv",
                       labels=FIXTURES / "labels.csv",
                       event_labels=FIXTURES / "event_labels.csv")
    assert first["events"] > 0 and first["labels"] > 0 and first["event_labels"] > 0

    with eval_db.engine.connect() as conn:
        events = conn.execute(text("SELECT COUNT(*) FROM eval_event")).scalar()
        labels = conn.execute(text("SELECT COUNT(*) FROM eval_label")).scalar()

    # Re-import the same files: upsert on the primary keys, no duplicates.
    run_import(eval_db.engine,
               events=FIXTURES / "events.csv",
               labels=FIXTURES / "labels.csv",
               event_labels=FIXTURES / "event_labels.csv")
    with eval_db.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM eval_event")).scalar() == events
        assert conn.execute(text("SELECT COUNT(*) FROM eval_label")).scalar() == labels


def test_importer_reads_json_bundles(eval_db):
    from tools.eval_import import run_import

    counts = run_import(eval_db.engine, bundle=FIXTURES / "bundle.json")
    assert counts["events"] > 0
    with eval_db.engine.connect() as conn:
        strata = {r[0] for r in conn.execute(text("SELECT stratum FROM eval_event"))}
    assert "null_event" in strata


def test_importer_refuses_unknown_stratum_and_writes_nothing(eval_db, tmp_path):
    from tools.eval_import import run_import, EvalImportError

    bad = tmp_path / "bad_events.csv"
    bad.write_text(
        "event_id,stratum,article_ref\n"
        "evt_ok,commodity,https://fixture.invalid/a\n"
        "evt_bad,rumour,https://fixture.invalid/b\n", encoding="utf-8")

    with pytest.raises(EvalImportError) as excinfo:
        run_import(eval_db.engine, events=bad)
    assert "rumour" in str(excinfo.value)

    with eval_db.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM eval_event")).scalar() == 0


def test_importer_refuses_unknown_tier_and_writes_nothing(eval_db, tmp_path):
    from tools.eval_import import run_import, EvalImportError

    events = tmp_path / "e.csv"
    events.write_text("event_id,stratum,article_ref\n"
                      "evt_ok,commodity,https://fixture.invalid/a\n", encoding="utf-8")
    bad = tmp_path / "bad_labels.csv"
    bad.write_text("event_id,company_ref,labeler,expected_tier\n"
                   "evt_ok,FIXTCO,labeler_a,PROBABLY_PRIMARY\n", encoding="utf-8")

    with pytest.raises(EvalImportError):
        run_import(eval_db.engine, events=events, labels=bad)

    with eval_db.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM eval_event")).scalar() == 0
        assert conn.execute(text("SELECT COUNT(*) FROM eval_label")).scalar() == 0


def test_no_fixture_data_reaches_production_tables(eval_db):
    """00_MASTER_CONTEXT: 'a test asserting no fixture data reaches
    production tables must exist'."""
    from tools.eval_import import run_import
    from app.db import Base
    from app import models  # noqa: F401

    run_import(eval_db.engine,
               events=FIXTURES / "events.csv",
               labels=FIXTURES / "labels.csv",
               event_labels=FIXTURES / "event_labels.csv")

    with eval_db.engine.connect() as conn:
        for table in Base.metadata.tables:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            assert count == 0, f"eval fixture import wrote {count} row(s) into {table}"


def test_fixture_files_are_marked_as_fixtures():
    text_blob = (FIXTURES / "events.csv").read_text(encoding="utf-8")
    assert "_fixture" in text_blob
    bundle = json.loads((FIXTURES / "bundle.json").read_text(encoding="utf-8"))
    assert bundle.get("_fixture") is True


# ---------------------------------------------------------------------------
# 3. labeling UI (standalone app)
# ---------------------------------------------------------------------------

@pytest.fixture()
def ui_client(eval_db):
    from fastapi.testclient import TestClient
    from tools.eval_ui import build_app

    with eval_db.engine.begin() as conn:
        _seed_article(conn, article_id=1,
                      title="Brent crude jumps after supply disruption",
                      body="Crude oil prices rose sharply on Monday.",
                      url="https://fixture.invalid/crude-1")
        _seed_company(conn, company_id=1, ticker="ZZANCHOR", name="Zz Anchor Refineries",
                      sector="Energy", sub_sector="Refineries")
        _seed_alert(conn, alert_id=1, article_id=1)
        _seed_alert_company(conn, alert_id=1, company_id=1, direction="bearish",
                            display_tier="primary", gate_state="DISPLAY_ELIGIBLE",
                            economic_effect="negative",
                            mechanism="ZZMECHANISM crude input cost rises",
                            rationale="ZZRATIONALE margin compression")
        conn.execute(text(
            "INSERT INTO eval_event (event_id, stratum, article_ref, notes) "
            "VALUES ('evt_ui_1', 'commodity', '1', 'ui test')"))

    return TestClient(build_app(eval_db.engine))


def test_label_view_serves_the_article(ui_client):
    resp = ui_client.get("/eval/label", params={"labeler": "labeler_a"})
    assert resp.status_code == 200
    assert "Brent crude jumps after supply disruption" in resp.text
    assert "Crude oil prices rose sharply" in resp.text


def test_label_view_leaks_no_system_output(ui_client):
    """Anchoring destroys the label (08_PHASE_7 protocol): the labeler must
    not see a single ticker, company, mechanism, rationale or gate state
    the system produced. The seeded analysis uses ZZ-prefixed sentinels so
    a leak cannot hide behind ordinary vocabulary."""
    resp = ui_client.get("/eval/label", params={"labeler": "labeler_a"})
    body = resp.text
    for leaked in ("ZZANCHOR", "Zz Anchor Refineries", "ZZMECHANISM",
                   "ZZRATIONALE", "DISPLAY_ELIGIBLE"):
        assert leaked not in body, f"labeling view leaked system output: {leaked!r}"


def test_label_ui_cannot_read_the_system_output_tables():
    """Structural version of the test above: the labeling UI's source must
    not mention a system-output table at all, so no future edit can
    accidentally start rendering one."""
    src = (BACKEND / "tools" / "eval_ui.py").read_text(encoding="utf-8")
    code = "\n".join(line for line in src.splitlines()
                     if not line.lstrip().startswith("#"))
    # strip the module docstring, which legitimately explains the rule
    body = code.split('"""', 2)[-1]
    for table in ("alert_companies", "FROM alerts", "impact_edges"):
        assert table not in body, f"eval_ui.py touches system output: {table!r}"


def test_label_post_saves_labels_families_and_identity(ui_client, eval_db):
    resp = ui_client.post("/eval/label", data={
        "labeler": "labeler_a",
        "event_id": "evt_ui_1",
        "primary_companies": "AAA, BBB",
        "absent_companies": "CCC",
        "ripple_families": "refiners, oil marketing",
        "directions": "AAA:bearish, BBB:bullish",
        "rationale": "crude up hits refiner margins",
    }, follow_redirects=False)
    assert resp.status_code in (200, 302, 303)

    with eval_db.engine.connect() as conn:
        rows = {r[0]: (r[1], r[2], r[3]) for r in conn.execute(text(
            "SELECT company_ref, expected_tier, expected_direction, labeler "
            "FROM eval_label WHERE event_id='evt_ui_1'"))}
        assert rows["AAA"][0] == "PRIMARY" and rows["AAA"][1] == "bearish"
        assert rows["BBB"][0] == "PRIMARY" and rows["BBB"][1] == "bullish"
        assert rows["CCC"][0] == "ABSENT"
        assert rows["AAA"][2] == "labeler_a"

        families, labeled_at = conn.execute(text(
            "SELECT ripple_families_json, labeled_at FROM eval_event_label "
            "WHERE event_id='evt_ui_1' AND labeler='labeler_a'")).one()
        assert json.loads(families) == ["refiners", "oil marketing"]
        assert labeled_at is not None


def test_index_shows_label_progress(ui_client):
    ui_client.post("/eval/label", data={
        "labeler": "labeler_a", "event_id": "evt_ui_1",
        "primary_companies": "AAA", "absent_companies": "", "ripple_families": "",
        "directions": "", "rationale": "x"}, follow_redirects=False)
    resp = ui_client.get("/")
    assert resp.status_code == 200
    assert "evt_ui_1" in resp.text
    assert "1/2" in resp.text


def test_adjudicate_view_and_post(ui_client, eval_db):
    for labeler, primaries in (("labeler_a", "AAA,BBB"), ("labeler_b", "AAA")):
        ui_client.post("/eval/label", data={
            "labeler": labeler, "event_id": "evt_ui_1",
            "primary_companies": primaries, "absent_companies": "",
            "ripple_families": "refiners", "directions": "", "rationale": "x"},
            follow_redirects=False)

    view = ui_client.get("/eval/adjudicate", params={"event_id": "evt_ui_1"})
    assert view.status_code == 200
    assert "labeler_a" in view.text and "labeler_b" in view.text
    assert "BBB" in view.text  # the disagreement is surfaced

    resp = ui_client.post("/eval/adjudicate", data={
        "event_id": "evt_ui_1", "resolved_by": "owner",
        "resolution_AAA": "MERGED", "resolution_BBB": "DISPUTED",
        "note_BBB": "cannot agree",
    }, follow_redirects=False)
    assert resp.status_code in (200, 302, 303)

    with eval_db.engine.connect() as conn:
        rows = dict(conn.execute(text(
            "SELECT company_ref, resolution FROM eval_adjudication "
            "WHERE event_id='evt_ui_1'")).all())
    assert rows["AAA"] == "MERGED"
    assert rows["BBB"] == "DISPUTED"


def test_ui_is_not_wired_into_the_production_app():
    """The labeling UI is a standalone process; nothing in app/main.py may
    mount it."""
    main_src = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")
    assert "eval_ui" not in main_src
    assert "/eval/" not in main_src


# ---------------------------------------------------------------------------
# 4. scorer -- loud failure, no LLM, real metrics
# ---------------------------------------------------------------------------

def test_scorer_fails_loudly_on_an_empty_corpus(eval_db, tmp_path):
    """THE mandated test: never 0%, never 100%, on zero data."""
    proc, out = _score(eval_db, tmp_path)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    combined = proc.stdout + proc.stderr
    assert "EMPTY" in combined.upper()
    assert "0%" not in combined and "100%" not in combined
    assert not out.exists(), "a baseline was written for an empty corpus"


def test_scorer_fails_loudly_when_events_exist_but_no_labels(eval_db, tmp_path):
    with eval_db.engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO eval_event (event_id, stratum, article_ref) "
            "VALUES ('e1', 'commodity', '1')"))
    proc, out = _score(eval_db, tmp_path)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "label" in (proc.stdout + proc.stderr).lower()
    assert not out.exists()


FORBIDDEN_IMPORT_ROOTS = (
    "anthropic", "openai", "google", "groq", "httpx", "requests", "urllib3",
    "app.analysis", "app.pipeline", "app.scheduler", "app.ingestion", "app.main",
)


def test_scorer_imports_no_llm_or_network_module():
    src = (BACKEND / "scripts" / "score_baseline.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                imported.add(node.module)
    for name in imported:
        for bad in FORBIDDEN_IMPORT_ROOTS:
            assert not (name == bad or name.startswith(bad + ".")), \
                f"score_baseline.py imports {name!r} -- the scorer must be unable to call an LLM"


def test_scorer_process_never_loads_a_provider_sdk():
    """Static scan plus proof: importing the scorer must not pull a
    provider SDK in transitively either."""
    probe = (
        "import sys; sys.path.insert(0, '.');"
        "import scripts.score_baseline;"
        "bad=[m for m in ('anthropic','openai','groq','google.generativeai') if m in sys.modules];"
        "print('LOADED:'+','.join(bad));"
        "raise SystemExit(1 if bad else 0)"
    )
    proc = subprocess.run([sys.executable, "-c", probe], cwd=BACKEND,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_cohens_kappa_reproduces_a_hand_computed_value():
    """Four companies, two labelers:
        X: PRIMARY/PRIMARY, Y: PRIMARY/ABSENT,
        Z: ABSENT/ABSENT,   W: SECONDARY_RIPPLE/SECONDARY_RIPPLE
    p_o = 3/4 = 0.75
    A marginals: PRIMARY .5, ABSENT .25, SECONDARY .25
    B marginals: PRIMARY .25, ABSENT .5,  SECONDARY .25
    p_e = .5*.25 + .25*.5 + .25*.25 = 0.3125
    kappa = (.75-.3125)/(1-.3125) = 7/11 = 0.636363...
    """
    from scripts.score_baseline import cohens_kappa

    pairs = [("PRIMARY", "PRIMARY"), ("PRIMARY", "ABSENT"),
             ("ABSENT", "ABSENT"), ("SECONDARY_RIPPLE", "SECONDARY_RIPPLE")]
    assert cohens_kappa(pairs) == pytest.approx(7 / 11)


def test_cohens_kappa_is_undefined_not_perfect_without_variance():
    from scripts.score_baseline import cohens_kappa

    assert cohens_kappa([("PRIMARY", "PRIMARY"), ("PRIMARY", "PRIMARY")]) is None
    assert cohens_kappa([]) is None


def test_kappa_over_corpus_matches_the_labels(eval_db):
    from scripts.score_baseline import kappa_over_corpus

    with eval_db.engine.begin() as conn:
        conn.execute(text("INSERT INTO eval_event (event_id, stratum, article_ref) "
                          "VALUES ('e1', 'commodity', '1')"))
        rows = [("X", "labeler_a", "PRIMARY"), ("X", "labeler_b", "PRIMARY"),
                ("Y", "labeler_a", "PRIMARY"), ("Y", "labeler_b", "ABSENT"),
                ("Z", "labeler_a", "ABSENT"), ("Z", "labeler_b", "ABSENT"),
                ("W", "labeler_a", "SECONDARY_RIPPLE"), ("W", "labeler_b", "SECONDARY_RIPPLE")]
        for company, labeler, tier in rows:
            conn.execute(text(
                "INSERT INTO eval_label (event_id, company_ref, labeler, expected_tier) "
                "VALUES ('e1', :c, :l, :t)"), {"c": company, "l": labeler, "t": tier})

    with eval_db.engine.connect() as conn:
        kappa, n_pairs, _note = kappa_over_corpus(conn)
    assert n_pairs == 4
    assert kappa == pytest.approx(7 / 11)


# --- end-to-end scoring on a seeded corpus ---------------------------------

@pytest.fixture()
def scored_corpus(eval_db):
    """One crude event with a real stored analysis, one null event with a
    (wrongly) published PRIMARY, one event whose article was never
    analysed (UNSCORED)."""
    with eval_db.engine.begin() as conn:
        _seed_article(conn, article_id=1, title="Crude spikes",
                      body="Brent rose after a supply outage.",
                      url="https://fixture.invalid/crude-1")
        _seed_article(conn, article_id=2, title="Bank branch reopens",
                      body="A branch reopened in Pune.",
                      url="https://fixture.invalid/null-1")
        _seed_article(conn, article_id=3, title="Never analysed",
                      body="No alert exists for this one.",
                      url="https://fixture.invalid/unscored-1")

        _seed_company(conn, company_id=1, ticker="HITCO", name="Hit Refineries",
                      sector="Energy", sub_sector="Refineries")
        _seed_company(conn, company_id=2, ticker="MISSCO", name="Miss Oil Marketing",
                      sector="Energy", sub_sector="Oil Marketing")
        _seed_company(conn, company_id=3, ticker="FPCO", name="False Positive Ltd",
                      sector="Chemicals", sub_sector="Specialty Chemicals")
        _seed_company(conn, company_id=4, ticker="RIPCO", name="Ripple Paints",
                      sector="Chemicals", sub_sector="Paints")
        _seed_company(conn, company_id=5, ticker="NULLCO", name="Null Bank",
                      sector="Banking", sub_sector="Private Banks")

        _seed_alert(conn, alert_id=1, article_id=1, facts="Brent rose after a supply outage.")
        # true positive, correct direction
        _seed_alert_company(conn, alert_id=1, company_id=1, direction="bearish",
                            display_tier="primary", mechanism="crude input cost",
                            rationale="margin squeeze")
        # false positive PRIMARY (both labelers said ABSENT)
        _seed_alert_company(conn, alert_id=1, company_id=3, direction="bullish",
                            display_tier="primary", mechanism="none stated")
        # secondary ripple in the Paints family
        _seed_alert_company(conn, alert_id=1, company_id=4, direction="bearish",
                            display_tier="secondary_ripple", mechanism="crude derivative input",
                            causal_distance=2, impact_level="indirect_l1")

        _seed_alert(conn, alert_id=2, article_id=2)
        _seed_alert_company(conn, alert_id=2, company_id=5, direction="bullish",
                            display_tier="primary", mechanism="branch expansion")

        # events
        for event_id, stratum, ref in (("evt_crude", "commodity", "1"),
                                       ("evt_null", "null_event", "2"),
                                       ("evt_unscored", "commodity", "3")):
            conn.execute(text(
                "INSERT INTO eval_event (event_id, stratum, article_ref) "
                "VALUES (:e, :s, :r)"), {"e": event_id, "s": stratum, "r": ref})

        def label(event_id, company, labeler, tier, direction=None):
            conn.execute(text(
                "INSERT INTO eval_label (event_id, company_ref, labeler, expected_tier, "
                "expected_direction, labeled_at) VALUES (:e, :c, :l, :t, :d, :ts)"),
                {"e": event_id, "c": company, "l": labeler, "t": tier, "d": direction,
                 "ts": datetime(2026, 8, 15, tzinfo=timezone.utc)})

        for labeler in ("labeler_a", "labeler_b"):
            label("evt_crude", "HITCO", labeler, "PRIMARY", "bearish")
            label("evt_crude", "MISSCO", labeler, "PRIMARY", "bearish")
            conn.execute(text(
                "INSERT INTO eval_event_label (event_id, labeler, ripple_families_json, labeled_at) "
                "VALUES ('evt_crude', :l, :f, :ts)"),
                {"l": labeler, "f": json.dumps(["Paints", "Aviation"]),
                 "ts": datetime(2026, 8, 15, tzinfo=timezone.utc)})
            label("evt_null", "NULLCO", labeler, "ABSENT")
            conn.execute(text(
                "INSERT INTO eval_event_label (event_id, labeler, ripple_families_json, labeled_at) "
                "VALUES ('evt_null', :l, '[]', :ts)"),
                {"l": labeler, "ts": datetime(2026, 8, 15, tzinfo=timezone.utc)})
            label("evt_unscored", "HITCO", labeler, "PRIMARY", "bearish")
            conn.execute(text(
                "INSERT INTO eval_event_label (event_id, labeler, ripple_families_json, labeled_at) "
                "VALUES ('evt_unscored', :l, '[]', :ts)"),
                {"l": labeler, "ts": datetime(2026, 8, 15, tzinfo=timezone.utc)})
    return eval_db


def test_scorer_emits_the_exact_section_2_fields(scored_corpus, tmp_path):
    proc, out = _score(scored_corpus, tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    md = out.read_text(encoding="utf-8")

    assert "NEWSFLO BASELINE — 2026-08-17 — commit deadbeef" in md.splitlines()[0]
    for field in ("PRIMARY precision", "PRIMARY recall", "Wrong-direction rate",
                  "Ripple family recall", "False PRIMARY on null events",
                  "Fabricated numerals found", "Internal contradictions"):
        assert field in md, f"BASELINE.md missing §2 field: {field}"
    assert "per-stratum" in md.lower()
    assert "null event" in md.lower()


def test_scorer_computes_precision_and_recall(scored_corpus, tmp_path):
    from scripts.score_baseline import score_corpus

    with scored_corpus.engine.connect() as conn:
        result = score_corpus(conn)

    # evt_crude: published PRIMARY {HITCO, FPCO}; expected PRIMARY {HITCO, MISSCO}
    # evt_null:  published PRIMARY {NULLCO}; expected ABSENT
    # -> TP=1, FP=2 (FPCO, NULLCO), FN=1 (MISSCO)
    assert result.primary_true_positives == 1
    assert result.primary_false_positives == 2
    assert result.primary_false_negatives == 1
    assert result.primary_precision == pytest.approx(1 / 3)
    assert result.primary_recall == pytest.approx(1 / 2)


def test_scorer_reports_unscored_events_loudly(scored_corpus, tmp_path):
    proc, out = _score(scored_corpus, tmp_path)
    assert "evt_unscored" in proc.stdout + proc.stderr
    assert "UNSCORED" in (proc.stdout + proc.stderr).upper()
    assert "evt_unscored" in out.read_text(encoding="utf-8")


def test_scorer_counts_false_primary_on_null_events(scored_corpus, tmp_path):
    from scripts.score_baseline import score_corpus

    with scored_corpus.engine.connect() as conn:
        result = score_corpus(conn)
    assert result.null_events_total == 1
    assert result.null_events_with_primary == 1


def test_scorer_measures_ripple_family_recall(scored_corpus):
    from scripts.score_baseline import score_corpus

    with scored_corpus.engine.connect() as conn:
        result = score_corpus(conn)
    # expected families {Paints, Aviation}; RIPCO (sub_sector Paints) is
    # published secondary -> 1 of 2.
    assert result.ripple_families_expected == 2
    assert result.ripple_families_hit == 1


def test_scorer_excludes_disputed_from_precision_denominators(scored_corpus):
    from scripts.score_baseline import score_corpus

    with scored_corpus.engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO eval_adjudication (event_id, company_ref, resolution) "
            "VALUES ('evt_crude', 'MISSCO', 'DISPUTED')"))
    with scored_corpus.engine.connect() as conn:
        result = score_corpus(conn)

    assert result.disputed_pairs == 1
    assert result.primary_false_negatives == 0
    assert result.primary_recall == pytest.approx(1.0)


def test_scorer_detects_wrong_direction(scored_corpus):
    from scripts.score_baseline import score_corpus

    with scored_corpus.engine.begin() as conn:
        conn.execute(text(
            "UPDATE alert_companies SET direction='bullish' "
            "WHERE alert_id=1 AND company_id=1"))
    with scored_corpus.engine.connect() as conn:
        result = score_corpus(conn)
    assert result.wrong_direction == 1
    assert result.wrong_direction_denominator == 1


def test_scorer_detects_internal_contradictions(scored_corpus):
    from scripts.score_baseline import score_corpus

    with scored_corpus.engine.begin() as conn:
        # gate_state NULL -> the §26 trigger does not fire; exactly the
        # legacy shape this audit exists to catch.
        conn.execute(text(
            "UPDATE alert_companies SET economic_effect='positive' "
            "WHERE alert_id=1 AND company_id=1"))
    with scored_corpus.engine.connect() as conn:
        result = score_corpus(conn)
    assert result.internal_contradictions >= 1


def test_scorer_detects_fabricated_numerals(scored_corpus):
    from scripts.score_baseline import score_corpus

    with scored_corpus.engine.connect() as conn:
        clean = score_corpus(conn)
    assert clean.fabricated_numerals == 0

    with scored_corpus.engine.begin() as conn:
        conn.execute(text(
            "UPDATE alert_companies SET rationale='margins fall 37% on crude' "
            "WHERE alert_id=1 AND company_id=1"))
    with scored_corpus.engine.connect() as conn:
        dirty = score_corpus(conn)
    assert dirty.fabricated_numerals >= 1


def test_scorer_reads_legacy_rows_through_the_derived_tier(scored_corpus):
    """Most stored rows predate the V4 strict gate and carry
    display_tier=NULL. The scorer must still see them -- and must disclose
    how many it read that way."""
    from scripts.score_baseline import score_corpus

    with scored_corpus.engine.begin() as conn:
        conn.execute(text("UPDATE alert_companies SET display_tier=NULL"))
    with scored_corpus.engine.connect() as conn:
        result = score_corpus(conn)

    assert result.rows_tier_derived == result.rows_scored > 0
    # HITCO (impact_level=direct) is still read as published PRIMARY, and
    # RIPCO (causal_distance=2) is still read as secondary.
    assert result.primary_true_positives == 1
    assert result.ripple_families_hit == 1


def test_scorer_never_writes_to_production_tables(scored_corpus, tmp_path):
    with scored_corpus.engine.connect() as conn:
        before = conn.execute(text("SELECT COUNT(*) FROM alert_companies")).scalar()
    proc, _out = _score(scored_corpus, tmp_path)
    assert proc.returncode == 0
    with scored_corpus.engine.connect() as conn:
        after = conn.execute(text("SELECT COUNT(*) FROM alert_companies")).scalar()
    assert before == after


def test_secondary_tier_spellings_track_the_publication_gate():
    """The scorer holds its own copy of the legacy tier spellings (it must
    not import app.analysis). This pins the copy to the source of truth."""
    from app.analysis.impact_graph.publication_gate import (
        LEGACY_SECONDARY_SPELLINGS, TIER_SECONDARY_RIPPLE, TIER_PRIMARY)
    from scripts.score_baseline import SECONDARY_TIERS, PRIMARY_TIER

    assert PRIMARY_TIER == TIER_PRIMARY
    assert set(SECONDARY_TIERS) == {TIER_SECONDARY_RIPPLE, *LEGACY_SECONDARY_SPELLINGS}
