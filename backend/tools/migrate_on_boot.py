"""Run Alembic to head at container boot -- the ONE place migrations
actually execute in production.

WHY THIS EXISTS (final-review blocker C1). Schema ownership moved to
Alembic on 2026-08-13 (see app/db.py: `_ADDED_COLUMNS` is frozen), but
nothing in the deploy path ever ran `alembic upgrade head`: the Dockerfile
started uvicorn directly, and `init_db()` -- the only schema step that DID
run -- can no longer add a column, because every column added since the
freeze lives in a migration instead. `create_all()` builds missing TABLES
but never missing COLUMNS on a table that already exists, so against a
PRE-EXISTING database (exactly production) the ~18 columns added by
migrations 0002-0007 were simply absent while the code wrote them
unconditionally (app/pipeline.py's event_cause /
expected_market_sensitivity writes, app/market/measure.py's data_quality /
session_state / reaction_significance writes -- none of them flag-gated).
The first ingested article would have crashed on "no such column".

WHAT IT DOES. Three states, one decision each, all idempotent:

  1. `alembic_version` table present -> the DB is already Alembic-managed.
     `alembic upgrade head`. (Already at head -> no-op, exit 0.)
  2. No `alembic_version`, but core tables (e.g. `alerts`) present -> a
     LEGACY database created by the pre-Alembic `init_db()` /
     `_ADDED_COLUMNS` path. Stamping it as `0001` (the baseline generated
     FROM those very models) tells Alembic "everything through the
     baseline already exists", then `upgrade head` applies 0002+ only.
     Running the baseline's CREATE TABLEs against it would fail instead.
  3. Neither -> a brand-new, empty database. `alembic upgrade head` builds
     it from nothing.

Every migration 0002..0008 is itself write-guarded (each checks the
inspector before adding a column/index/constraint, and 0008's triggers and
partial index are CREATE ... IF NOT EXISTS), so re-running this script
against any of the three states is safe.

After the upgrade it also ASSERTS the §26 gated-row trigger backstop is
still installed on SQLite (see `check_gated_row_triggers`) -- the one thing
a future migration can silently destroy without any test or runtime path
noticing.

Exits non-zero and logs loudly on any failure -- a container that cannot
migrate must NOT come up serving a half-migrated schema. Run it before
uvicorn (see the repo Dockerfile's CMD).
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
# Importing `app.config` needs the backend directory importable even when
# this script is invoked as `python tools/migrate_on_boot.py` from
# elsewhere.
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

logger = logging.getLogger("migrate_on_boot")

# Any one of these existing means "this DB predates Alembic but is not
# empty" -- `alerts` is the oldest, most central table in the schema and
# has existed since the first release; the others are belt-and-braces for
# a DB that somehow lost it.
_CORE_TABLES = ("alerts", "articles", "companies")

# The §26 gated-row backstop installed by 0008 (and by app/models.py's
# `after_create` hook / `emit_gated_row_triggers`). SQLite drops every
# trigger attached to a table it drops, and Alembic's `batch_alter_table`
# rebuilds a SQLite table by DROP + RENAME without copying triggers -- so
# ANY future migration that batch-alters `alert_companies` silently removes
# both of these unless it re-emits them (see the warning block in
# app/models.py). Nothing detected that; this does.
GATED_ROW_TRIGGERS = (
    "alert_companies_gated_consistency",
    "alert_companies_gated_consistency_insert",
)


class GatedRowTriggersMissing(RuntimeError):
    """The gated-row consistency triggers are absent after migration."""


def check_gated_row_triggers(url: str) -> tuple[str, tuple[str, ...]]:
    """Post-migration presence check for the §26 trigger backstop.

    Returns `(status, missing)` where status is one of:
      "ok"                -- both triggers present
      "missing"           -- `missing` names the absent trigger(s)
      "skipped_dialect"   -- not SQLite; the triggers are SQLite-only by
                             design (the Postgres port is a ledgered,
                             deliberate absence -- see the 0008 docstring
                             and app/models.py's emit_gated_row_triggers,
                             which no-ops off SQLite). Never a failure.
      "skipped_no_table"  -- no `alert_companies` table to protect yet.

    Factored out of `migrate_on_boot` so it is directly testable without
    spawning a boot process.
    """
    from sqlalchemy import create_engine, inspect, text

    if not url.startswith("sqlite"):
        return "skipped_dialect", ()

    engine = create_engine(url, connect_args={"check_same_thread": False})
    try:
        if "alert_companies" not in set(inspect(engine).get_table_names()):
            return "skipped_no_table", ()
        with engine.connect() as connection:
            present = {
                row[0] for row in connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type='trigger'"))
            }
    finally:
        engine.dispose()

    missing = tuple(name for name in GATED_ROW_TRIGGERS if name not in present)
    return ("missing" if missing else "ok"), missing


def _assert_gated_row_triggers(url: str, scheme: str) -> None:
    """Fail the boot when the backstop is gone. Loud on purpose: a
    half-enforced schema serving gated rows with no database-level guard is
    exactly the silent loss this check exists to prevent, and a container
    that cannot prove the guard is installed must NOT come up."""
    status, missing = check_gated_row_triggers(url)
    if status == "ok":
        logger.info("[migrate] gated-row trigger backstop present (%s)",
                    ", ".join(GATED_ROW_TRIGGERS))
        return
    if status == "skipped_dialect":
        logger.info(
            "[migrate] %s dialect: gated-row triggers are SQLite-only by "
            "design; presence check skipped", scheme)
        return
    if status == "skipped_no_table":
        logger.info(
            "[migrate] no alert_companies table; gated-row trigger check "
            "skipped")
        return

    message = (
        "[migrate] FATAL: the alert_companies gated-row trigger backstop is "
        "MISSING after migration -- absent trigger(s): "
        + ", ".join(missing)
        + ". SQLite drops triggers with the table, and Alembic's "
        "batch_alter_table rebuilds a table without copying them, so a "
        "recent migration that batch-altered alert_companies almost "
        "certainly removed them. That migration must re-emit the CREATE "
        "TRIGGER statements verbatim (see app/models.py's warning block); "
        "refusing to start with an unguarded gated-row table."
    )
    logger.error(message)
    print(message, file=sys.stderr)
    raise GatedRowTriggersMissing(message)


# ---------------------------------------------------------------------------
# V5 Phase 0 (Task 0.3) backstop -- ADDITIVE, deliberately separate from the
# §26 list above, which must not be touched.
# ---------------------------------------------------------------------------
# company_impact is writable only inside a reducer session, and `signal` is
# append-only. Both guarantees are triggers (migration 0011 + app/models.py's
# after_create hooks), and both die silently if a future migration ever
# rebuilds those tables. Nothing detects that; this does.
V5_TRIGGERS = (
    "company_impact_reducer_only_insert",
    "company_impact_reducer_only_update",
    "company_impact_version_fence_insert",
    "company_impact_version_fence_update",
    "signal_append_only_update",
    "signal_append_only_delete",
)


class V5TriggersMissing(RuntimeError):
    """The V5 single-writer / append-only triggers are absent after migration."""


def check_v5_triggers(url: str) -> tuple[str, tuple[str, ...]]:
    """Same contract as `check_gated_row_triggers`: returns
    `(status, missing)` with status in {"ok", "missing", "skipped_dialect",
    "skipped_no_table"}."""
    from sqlalchemy import create_engine, inspect, text

    if not url.startswith("sqlite"):
        return "skipped_dialect", ()

    engine = create_engine(url, connect_args={"check_same_thread": False})
    try:
        tables = set(inspect(engine).get_table_names())
        if not {"company_impact", "signal"} <= tables:
            return "skipped_no_table", ()
        with engine.connect() as connection:
            present = {
                row[0] for row in connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type='trigger'"))
            }
    finally:
        engine.dispose()

    missing = tuple(name for name in V5_TRIGGERS if name not in present)
    return ("missing" if missing else "ok"), missing


def _assert_v5_triggers(url: str, scheme: str) -> None:
    status, missing = check_v5_triggers(url)
    if status == "ok":
        logger.info("[migrate] V5 single-writer trigger backstop present")
        return
    if status == "skipped_dialect":
        logger.info(
            "[migrate] %s dialect: the V5 backstop is role privileges, not "
            "triggers (see migration 0011's docstring); check skipped", scheme)
        return
    if status == "skipped_no_table":
        logger.info("[migrate] no company_impact/signal tables; V5 trigger "
                    "check skipped")
        return

    message = (
        "[migrate] FATAL: the V5 single-writer/append-only trigger backstop is "
        "MISSING after migration -- absent trigger(s): " + ", ".join(missing)
        + ". company_impact would be writable by any process and `signal` "
        "would be mutable; refusing to start.")
    logger.error(message)
    print(message, file=sys.stderr)
    raise V5TriggersMissing(message)


# ---------------------------------------------------------------------------
# V5 Phase 1 (Task 1.1/1.4) ledger backstop -- ADDITIVE again, and again
# deliberately separate from both lists above.
# ---------------------------------------------------------------------------
# `company_exposure` is writable only inside a review session (migration 0012
# + app/models.py's after_create hooks). Without these triggers any process --
# including an LLM extractor -- could write the ledger directly, which is the
# one thing the phase file forbids "under any circumstance".
LEDGER_TRIGGERS = (
    "company_exposure_review_only_insert",
    "company_exposure_review_only_update",
)


class LedgerGuardMissing(RuntimeError):
    """The V5 ledger review-only triggers are absent after migration."""


def check_ledger_guard(url: str) -> tuple[str, tuple[str, ...]]:
    """Same contract as the two checks above: returns `(status, missing)`
    with status in {"ok", "missing", "skipped_dialect", "skipped_no_table"}."""
    from sqlalchemy import create_engine, inspect, text

    if not url.startswith("sqlite"):
        return "skipped_dialect", ()

    engine = create_engine(url, connect_args={"check_same_thread": False})
    try:
        if "company_exposure" not in set(inspect(engine).get_table_names()):
            return "skipped_no_table", ()
        with engine.connect() as connection:
            present = {
                row[0] for row in connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type='trigger'"))
            }
    finally:
        engine.dispose()

    missing = tuple(name for name in LEDGER_TRIGGERS if name not in present)
    return ("missing" if missing else "ok"), missing


def _assert_ledger_guard(url: str, scheme: str) -> None:
    status, missing = check_ledger_guard(url)
    if status == "ok":
        logger.info("[migrate] V5 ledger review-only guard present")
        return
    if status == "skipped_dialect":
        logger.info(
            "[migrate] %s dialect: the ledger guard is role privileges, not "
            "triggers (see migration 0012's docstring); check skipped", scheme)
        return
    if status == "skipped_no_table":
        logger.info("[migrate] no company_exposure table; ledger guard check "
                    "skipped")
        return

    message = (
        "[migrate] FATAL: the V5 exposure-ledger review-only guard is MISSING "
        "after migration -- absent trigger(s): " + ", ".join(missing)
        + ". company_exposure would be writable without review; refusing to "
        "start.")
    logger.error(message)
    print(message, file=sys.stderr)
    raise LedgerGuardMissing(message)


def _database_url() -> str:
    """Same resolution order as every other entrypoint (app/db.py,
    alembic/env.py): DATABASE_URL wins, else settings' own default."""
    from app.config import settings

    return os.environ.get("DATABASE_URL") or settings.database_url


def _table_names(url: str) -> set[str]:
    from sqlalchemy import create_engine, inspect

    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _create_missing_tables(url: str) -> None:
    """create_all for TABLES a stamped/managed DB never got (tables are
    only created by 0001 on empty DBs or by whichever code version first
    ran against the file). Never touches existing tables; new tables are
    built at current-model shape and the guarded column migrations then
    no-op over them."""
    from sqlalchemy import create_engine

    import app.models  # noqa: F401 -- registers every table on Base.metadata
    from app.db import Base

    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()


def _alembic(url: str, *args: str) -> None:
    """Run one alembic command in a subprocess. Subprocess rather than the
    Python API on purpose: alembic/env.py configures logging from
    alembic.ini and runs `context.run_migrations()` at import time, which
    is safe to do exactly once per process -- a second in-process
    invocation in the same run (stamp, then upgrade) would re-enter it."""
    command = [sys.executable, "-m", "alembic", *args]
    logger.info("running: %s", " ".join(command))
    result = subprocess.run(
        command,
        cwd=str(BACKEND_DIR),
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        logger.info("alembic stdout:\n%s", result.stdout.strip())
    if result.stderr.strip():
        # Alembic writes its normal progress log to stderr; only the return
        # code distinguishes success from failure.
        logger.info("alembic stderr:\n%s", result.stderr.strip())
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic {' '.join(args)} failed with exit code {result.returncode}"
        )


def migrate_on_boot(url: str | None = None) -> str:
    """Bring the database at `url` (default: the app's own DATABASE_URL) to
    Alembic head. Returns the state it detected -- "managed", "legacy" or
    "empty" -- for logging and tests. Raises on failure."""
    url = url or _database_url()
    # Never log the URL itself: a Postgres DSN carries the password.
    scheme = url.split("://", 1)[0]
    tables = _table_names(url)

    if "alembic_version" in tables:
        state = "managed"
        logger.info("[migrate] %s DB is alembic-managed; upgrading to head", scheme)
        _create_missing_tables(url)
        _alembic(url, "upgrade", "head")
    elif tables & set(_CORE_TABLES):
        state = "legacy"
        logger.warning(
            "[migrate] %s DB has core tables but no alembic_version -- "
            "pre-alembic legacy DB; stamping 0001 then upgrading to head", scheme,
        )
        _alembic(url, "stamp", "0001")
        # Stamping skips 0001's create_table calls, so a legacy DB that
        # predates any table (first hit in the wild: an ingestion copy
        # missing company_decision_records) would crash 0006's column
        # reflection. create_all adds the missing TABLES only -- every
        # later column migration is guarded add-if-missing, so building
        # a new table at current-model shape and then upgrading is safe.
        _create_missing_tables(url)
        _alembic(url, "upgrade", "head")
    else:
        state = "empty"
        logger.info("[migrate] %s DB is empty; building schema from head", scheme)
        _alembic(url, "upgrade", "head")

    # Post-upgrade §26 DB backstop assertion. Runs on every path, after the
    # schema is at head -- raises (and so fails the boot) when a trigger is
    # gone.
    _assert_gated_row_triggers(url, scheme)
    # V5 Phase 0 Task 0.3 backstop, checked the same way and for the same
    # reason. Separate function and separate trigger list ON PURPOSE: the
    # §26 check above polices alert_companies and must stay exactly as it
    # is; this one polices company_impact and signal.
    _assert_v5_triggers(url, scheme)
    # V5 Phase 1 Task 1.1/1.4 backstop: the exposure ledger's review-only
    # write guard. Third separate list, same discipline.
    _assert_ledger_guard(url, scheme)

    logger.info("[migrate] done (%s DB) -- schema at alembic head", state)
    return state


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        migrate_on_boot()
    except Exception:
        logger.exception(
            "[migrate] FAILED -- refusing to start with an unmigrated schema")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
