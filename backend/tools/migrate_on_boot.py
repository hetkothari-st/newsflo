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
