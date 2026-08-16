"""TASK 0.3 tests -- single-writer enforcement, PROVEN BY THE DATABASE.

docs/v5/01_PHASE_0_canonical_truth.md TESTS/test_single_writer.py:
  * a non-reducer connection attempting INSERT on company_impact is refused
  * a stale worker with an unregistered reducer_version is rejected
  * an out-of-order upsert with a lower reducer_run_seq does not overwrite

SQLITE SUBSTITUTION (controller adaptation, binding): this repo is SQLite,
which has no roles and no GRANT. The Postgres role DDL is documented
verbatim in migration 0011's docstring for the future port; the enforcement
that actually runs here is a pair of BEFORE INSERT / BEFORE UPDATE triggers
keyed on a per-connection temp table that ONLY
`app.core.impact_writer.reducer_session` creates. A stale worker holding a
write handle to the same database file is refused AT THE DATABASE, which is
what the DoD's "proven by integration test, not by inspection" requires.

Version fencing is likewise a trigger rather than the phase file's FK: this
repo never enables SQLite's `PRAGMA foreign_keys`, so a declared FK is
inert here (the FK is still declared, for Postgres and for documentation).
The trigger additionally honours `supported_version.active`, which an FK
cannot express.
"""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import sessionmaker

from app.db import Base


@pytest.fixture()
def impact_db(tmp_path):
    """A file-backed SQLite DB built by create_all -- i.e. exercising the
    models.py DDL hooks, the same way the rest of the suite gets the 0008
    gated-row triggers."""
    from app import models  # noqa: F401

    url = f"sqlite:///{tmp_path / 'impact.db'}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    # create_all seeds `supported_version` with the running REDUCER_VERSION
    # via the same after_create hook that installs the triggers, so a
    # create_all-built DB matches a migrated one.
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _row(**overrides) -> dict:
    from app.core.reducer import REDUCER_VERSION

    row = {
        "event_id": "fixture:crude-shock-1",
        "company_id": 9001,
        "analysis_version": "v3:fixture",
        "reducer_version": REDUCER_VERSION,
        "reducer_run_seq": 1,
        "net_effect": "NEGATIVE",
        "publication_tier": "PRIMARY",
        "directness": "DIRECT",
        "graph_distance": 1,
        "discovery_source": "MENTION",
        "needs_reanalysis": 0,
        "decision_trace_id": "trace-1",
    }
    row.update(overrides)
    return row


def _insert_sql(row: dict) -> tuple[str, dict]:
    columns = ", ".join(row)
    values = ", ".join(f":{key}" for key in row)
    return f"INSERT INTO company_impact ({columns}) VALUES ({values})", row


def test_a_non_reducer_connection_cannot_insert_company_impact(impact_db):
    sql, params = _insert_sql(_row())
    with pytest.raises(DatabaseError) as excinfo:
        impact_db.execute(text(sql), params)
    assert "reducer" in str(excinfo.value).lower()


def test_a_non_reducer_connection_cannot_update_company_impact(impact_db):
    from app.core.impact_writer import reducer_session

    sql, params = _insert_sql(_row())
    with reducer_session(impact_db):
        impact_db.execute(text(sql), params)
        impact_db.commit()

    with pytest.raises(DatabaseError) as excinfo:
        impact_db.execute(text(
            "UPDATE company_impact SET net_effect = 'POSITIVE' "
            "WHERE event_id = :e"), {"e": "fixture:crude-shock-1"})
    assert "reducer" in str(excinfo.value).lower()


def test_the_reducer_session_can_write_and_the_guard_is_restored(impact_db):
    from app.core.impact_writer import reducer_session

    sql, params = _insert_sql(_row())
    with reducer_session(impact_db):
        impact_db.execute(text(sql), params)
        impact_db.commit()
    assert impact_db.execute(
        text("SELECT count(*) FROM company_impact")).scalar() == 1

    # ...and the temp table is gone again, so the very next statement on the
    # SAME connection is refused.
    with pytest.raises(DatabaseError):
        impact_db.execute(text(
            "UPDATE company_impact SET net_effect = 'POSITIVE'"))


def test_a_stale_worker_with_an_unregistered_reducer_version_is_rejected(impact_db):
    from app.core.impact_writer import reducer_session

    sql, params = _insert_sql(_row(reducer_version="r4.9.0-stale"))
    with reducer_session(impact_db):
        with pytest.raises(DatabaseError) as excinfo:
            impact_db.execute(text(sql), params)
    assert "version" in str(excinfo.value).lower()


def test_a_deactivated_reducer_version_is_rejected(impact_db):
    from app.core.impact_writer import reducer_session
    from app.core.reducer import REDUCER_VERSION

    impact_db.execute(text(
        "UPDATE supported_version SET active = 0 WHERE reducer_version = :v"),
        {"v": REDUCER_VERSION})
    impact_db.commit()
    sql, params = _insert_sql(_row())
    with reducer_session(impact_db):
        with pytest.raises(DatabaseError):
            impact_db.execute(text(sql), params)


def test_out_of_order_upsert_with_a_lower_run_seq_does_not_overwrite(impact_db):
    from app.core.impact_writer import reducer_session, upsert_impact_row

    with reducer_session(impact_db):
        upsert_impact_row(impact_db, _row(reducer_run_seq=7, net_effect="NEGATIVE"))
        upsert_impact_row(impact_db, _row(reducer_run_seq=3, net_effect="POSITIVE"))
        impact_db.commit()

    rows = impact_db.execute(text(
        "SELECT net_effect, reducer_run_seq FROM company_impact")).all()
    assert rows == [("NEGATIVE", 7)], (
        "a lower-sequence (stale) write overwrote a newer one")


def test_a_higher_run_seq_does_overwrite(impact_db):
    from app.core.impact_writer import reducer_session, upsert_impact_row

    with reducer_session(impact_db):
        upsert_impact_row(impact_db, _row(reducer_run_seq=3, net_effect="POSITIVE"))
        upsert_impact_row(impact_db, _row(reducer_run_seq=9, net_effect="NEGATIVE"))
        impact_db.commit()

    assert impact_db.execute(text(
        "SELECT net_effect, reducer_run_seq FROM company_impact")).all() == \
        [("NEGATIVE", 9)]


def test_signal_table_is_append_only(impact_db):
    from app.models import Signal, utcnow

    impact_db.add(Signal(
        signal_id="sig-1", event_id="fixture:crude-shock-1", company_id=9001,
        stage="SENSITIVITY", kind="CHANNEL", payload_json="{}",
        created_by="fixture", analysis_version="v3:fixture", created_at=utcnow()))
    impact_db.commit()

    with pytest.raises(DatabaseError):
        impact_db.execute(text("UPDATE signal SET stage = 'X' WHERE signal_id = 'sig-1'"))
    impact_db.rollback()
    with pytest.raises(DatabaseError):
        impact_db.execute(text("DELETE FROM signal WHERE signal_id = 'sig-1'"))


def test_the_api_process_asserts_it_cannot_write_company_impact(impact_db):
    """Task 0.3's startup assertion. It must PASS on an ordinary session
    (which cannot write) and FAIL loudly if it is ever run from inside a
    reducer session (which can)."""
    from app.core.impact_writer import (
        ReducerPrivilegeError, assert_cannot_write_company_impact, reducer_session,
    )

    assert_cannot_write_company_impact(impact_db)  # must not raise

    with reducer_session(impact_db):
        with pytest.raises(ReducerPrivilegeError):
            assert_cannot_write_company_impact(impact_db)


def test_the_startup_assertion_runs_on_app_boot():
    """Not enough to have the helper -- the API process must actually call
    it. Source-level check keeps it from being quietly dropped."""
    from pathlib import Path

    main = (Path(__file__).resolve().parents[2] / "app" / "main.py").read_text(
        encoding="utf-8")
    assert "assert_cannot_write_company_impact" in main
