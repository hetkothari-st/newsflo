"""FIX ROUND 2 (Critical C1) -- the reducer capability must never survive a
connection's return to the pool.

WHY THE EXISTING GUARD TESTS COULD NOT SEE THIS. `tests/phase0`'s other
writer tests use a StaticPool `:memory:` engine: ONE connection, forever, so
"the capability leaked to the next borrower" and "the DROP ran on a
different connection" are both unrepresentable. Production runs a
file-backed engine with a real pool. Every test in this file therefore
builds a `QueuePool` engine with `pool_size >= 2` -- the shape that made the
breach observable.

THE TWO FAILURE MODES, both proven below:
  1. `Session.commit()` INSIDE `with reducer_session(...)` releases the
     connection to the pool while the TEMP capability table is still on it,
     so the next Session to borrow that connection can write
     `company_impact`.
  2. With more than one pooled connection, the `finally` DROP can run on a
     DIFFERENT connection than the one that got the CREATE -- a silent
     no-op, leaving the original connection privileged for the lifetime of
     the process.
"""
import sqlite3

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from app.db import Base
from tests.phase0 import fixtures

POOL_SIZE = 2


@pytest.fixture()
def pooled(tmp_path):
    """A file-backed engine with a REAL pool, plus a sessionmaker."""
    from app import models  # noqa: F401

    engine = create_engine(
        f"sqlite:///{tmp_path / 'pool.db'}", poolclass=QueuePool,
        pool_size=POOL_SIZE, max_overflow=0,
        connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)

    # Warm every slot so the pool really holds POOL_SIZE distinct
    # connections -- a lazily-created pool would hand out the same one and
    # hide exactly what this file is testing.
    warm = [engine.connect() for _ in range(POOL_SIZE)]
    for connection in warm:
        connection.close()

    try:
        yield engine, sessionmaker(bind=engine)
    finally:
        engine.dispose()


def _impact():
    from app.core.reducer import reduce_company_impact

    return reduce_company_impact(
        fixtures.signals(fixtures.PRIMARY_COMPANY_ID), fixtures.reducer_config())


def _insert_attempt(session, suffix: str):
    from app.core.reducer import REDUCER_VERSION

    session.execute(text(
        "INSERT INTO company_impact (event_id, company_id, analysis_version, "
        "reducer_version, reducer_run_seq, publication_tier) "
        "VALUES (:e, 1, :a, :v, 1, 'PRIMARY')"),
        {"e": f"intruder:{suffix}", "a": f"v:{suffix}", "v": REDUCER_VERSION})


def _sweep_every_pooled_connection(Session) -> list[str]:
    """Hold POOL_SIZE sessions open AT ONCE so each necessarily borrows a
    DIFFERENT pooled connection, and try to write from every one. Returns
    the connections that were NOT refused."""
    sessions = []
    breached = []
    try:
        for index in range(POOL_SIZE):
            session = Session()
            # Force the checkout now, so the sessions really do hold
            # distinct connections while the next one is opened.
            session.execute(text("SELECT 1"))
            sessions.append(session)
        for index, session in enumerate(sessions):
            try:
                _insert_attempt(session, f"sweep{index}")
            except DatabaseError:
                session.rollback()
                continue
            breached.append(f"pooled connection {index} accepted a write")
    finally:
        for session in sessions:
            session.close()
    return breached


# --- the breach itself ------------------------------------------------------

def test_persisting_leaves_no_pooled_connection_privileged(pooled):
    """C1. After a real canonical write, EVERY connection in the pool must
    still be refused."""
    from app.core.impact_writer import persist_company_impact

    engine, Session = pooled
    session = Session()
    try:
        persist_company_impact(session, _impact(), reducer_run_seq=1)
    finally:
        session.close()

    assert not _sweep_every_pooled_connection(Session)


def test_the_written_row_is_actually_committed(pooled):
    """The fix moves the commit OUT of the guard -- it must not move it out
    of existence."""
    from app.core.impact_writer import persist_company_impact

    engine, Session = pooled
    session = Session()
    try:
        persist_company_impact(session, _impact(), reducer_run_seq=1)
    finally:
        session.close()

    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT count(*) FROM company_impact")).scalar() == 1


def test_the_capability_is_gone_from_the_writers_own_connection(pooled):
    """Not merely 'some connection is clean': the one that did the write."""
    from app.core.impact_writer import REDUCER_SESSION_TABLE, persist_company_impact

    engine, Session = pooled
    session = Session()
    try:
        persist_company_impact(session, _impact(), reducer_run_seq=1)
        present = session.execute(text(
            "SELECT count(*) FROM pragma_table_list WHERE schema = 'temp' "
            "AND name = :name"), {"name": REDUCER_SESSION_TABLE}).scalar()
        assert present == 0
        with pytest.raises(DatabaseError):
            _insert_attempt(session, "after")
        session.rollback()
    finally:
        session.close()


# --- failure mode 2, pinned as executable documentation ---------------------

def test_dropping_a_temp_table_from_another_connection_is_a_silent_noop(pooled):
    """A SQLite TEMP table lives on the CONNECTION. A `finally` DROP that
    lands on a different pooled connection succeeds, changes nothing, and
    leaves the original connection privileged -- silently."""
    from app.core.impact_writer import REDUCER_SESSION_TABLE

    engine, _ = pooled
    first = engine.connect()
    second = engine.connect()
    try:
        first.execute(text(
            f"CREATE TEMP TABLE {REDUCER_SESSION_TABLE} (granted INTEGER)"))
        # The "cleanup", on the wrong connection. No error, no effect.
        second.execute(text(f"DROP TABLE IF EXISTS temp.{REDUCER_SESSION_TABLE}"))

        still_there = first.execute(text(
            "SELECT count(*) FROM pragma_table_list WHERE schema = 'temp' "
            "AND name = :name"), {"name": REDUCER_SESSION_TABLE}).scalar()
        assert still_there == 1, (
            "this test documents a hazard; if it fails, SQLite's temp-schema "
            "semantics changed and the whole guard needs rethinking")
    finally:
        first.close()
        second.close()


def test_a_leaked_capability_is_scrubbed_when_the_connection_returns(pooled):
    """Belt and braces: even if some future code path leaves the token on a
    connection, the pool `checkin` listener in app/db.py removes it before
    the connection can be handed to anyone else."""
    from app.core.impact_writer import REDUCER_SESSION_TABLE

    engine, Session = pooled
    leaky = Session()
    try:
        leaky.execute(text(
            f"CREATE TEMP TABLE {REDUCER_SESSION_TABLE} (granted INTEGER)"))
        leaky.commit()
    finally:
        leaky.close()          # <- checkin runs here

    assert not _sweep_every_pooled_connection(Session)


def test_the_scrub_listener_is_registered_and_dialect_guarded():
    from app.db import CAPABILITY_TEMP_TABLES, scrub_capability_tables

    assert "_newsflo_reducer_session" in CAPABILITY_TEMP_TABLES
    assert "_newsflo_ledger_review_session" in CAPABILITY_TEMP_TABLES

    # A non-SQLite DBAPI connection must be left completely alone.
    class _NotSqlite:
        def execute(self, *args, **kwargs):        # pragma: no cover
            raise AssertionError("the scrub touched a non-SQLite connection")

    scrub_capability_tables(_NotSqlite(), None)


def test_the_scrub_never_breaks_checkin(pooled, caplog):
    """A failing DROP must not propagate out of checkin -- a connection that
    cannot return to the pool takes the process down with it."""
    from app.db import scrub_capability_tables

    class _Exploding(sqlite3.Connection):
        pass

    connection = sqlite3.connect(":memory:", factory=_Exploding)
    connection.close()                       # every execute now raises
    scrub_capability_tables(connection, None)   # must not raise


# --- the shape rule, pinned in source ---------------------------------------

def _commits_inside_a_guard(path) -> list[str]:
    """Any `session.commit()` lexically inside a `with reducer_session(...)`
    block. That is the C1 defect, and it is cheap to make unrepeatable."""
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.With):
            continue
        guarded = any(
            isinstance(item.context_expr, ast.Call)
            and getattr(item.context_expr.func, "id", "") == "reducer_session"
            for item in node.items)
        if not guarded:
            continue
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "commit"):
                found.append(f"{path.name}:{inner.lineno}")
    return found


def test_no_writer_commits_inside_the_reducer_guard():
    from pathlib import Path

    backend = Path(__file__).resolve().parents[2]
    for path in (backend / "app" / "core" / "impact_writer.py",
                 backend / "scripts" / "backfill_company_impact.py"):
        offenders = _commits_inside_a_guard(path)
        assert not offenders, (
            f"commit inside a reducer_session block at {offenders} -- a "
            "commit releases the connection to the pool while it still "
            "carries the capability token (fix round 2, C1)")
