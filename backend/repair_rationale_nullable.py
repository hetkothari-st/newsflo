# backend/repair_rationale_nullable.py
"""One-off SQLite schema repair: alert_companies.rationale NOT NULL -> nullable.

Task 6 relaxed this in the ORM (a sector_inference row persists no rationale,
and a row whose direction was flipped by measurement has its contradictory
rationale cleared). The persistent dev database predates that change and the
project has no migration tool, so the constraint is still live there --
meaning any new alert with a fan-out company fails to persist.

Rebuilds the table from the ORM definition rather than hand-written DDL, so
the new schema matches the model by construction. Idempotent: exits without
touching anything if the column is already nullable.
"""
from sqlalchemy import inspect, text
from sqlalchemy.schema import CreateTable

from app.db import Base, engine
from app.models import AlertCompany  # noqa: F401  registers the table on Base


def rationale_is_nullable() -> bool:
    for column in inspect(engine).get_columns("alert_companies"):
        if column["name"] == "rationale":
            return bool(column["nullable"])
    raise RuntimeError("alert_companies.rationale not found")


def main() -> None:
    # This script's whole rebuild-the-table approach (RENAME, CreateTable,
    # copy, DROP, legacy_alter_table PRAGMAs) is SQLite-specific -- running
    # it against Postgres would fail on the first PRAGMA statement at best,
    # or silently do the wrong thing at worst. Its name invites running it
    # during this branch's deploy without checking which database it's
    # pointed at -- guard explicitly rather than rely on that not happening.
    if engine.dialect.name != "sqlite":
        raise RuntimeError(
            f"repair_rationale_nullable.py is a SQLite-only table rebuild; "
            f"this database is {engine.dialect.name!r}. On Postgres, run "
            f"instead: ALTER TABLE alert_companies ALTER COLUMN rationale DROP NOT NULL;"
        )

    if rationale_is_nullable():
        print("alert_companies.rationale is already nullable -- nothing to do.")
        return

    table = Base.metadata.tables["alert_companies"]
    columns = ", ".join(c.name for c in table.columns)

    # A single physical connection for the whole repair, AUTOCOMMIT set once
    # at construction. SQLAlchemy rejects switching isolation_level mid-life
    # once a Transaction() has autobegun on the connection (which merely
    # executing the PRAGMA statements below triggers), so the transaction
    # itself is driven with explicit BEGIN/COMMIT/ROLLBACK text instead of
    # conn.begin() -- SQLite's DDL is transactional, so RENAME/CREATE/DROP
    # inside that BEGIN roll back correctly together.
    conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    try:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        # Since SQLite 3.25, "ALTER TABLE x RENAME TO y" rewrites every OTHER
        # table's FK clauses that reference x to reference y instead -- the
        # opposite of what a table-rebuild needs (calibration_samples,
        # email_notifications, alert_company_translations, and car_outcomes
        # must keep referencing the name "alert_companies", which the newly
        # created table takes over). legacy_alter_table restores the old,
        # non-rewriting rename behavior.
        conn.execute(text("PRAGMA legacy_alter_table=ON"))

        conn.execute(text("BEGIN"))
        try:
            before = conn.execute(text("SELECT COUNT(*) FROM alert_companies")).scalar_one()
            print(f"rows before: {before}")

            conn.execute(text("ALTER TABLE alert_companies RENAME TO alert_companies_old"))
            # Recreates the table (no indexes exist on alert_companies, so
            # there is nothing else to recreate) from the ORM definition, on
            # this same connection/transaction -- not table.create(engine),
            # which would check out a different connection.
            conn.execute(CreateTable(table))

            # Explicit column list, never SELECT * -- column ORDER must not
            # be assumed to match between the old table and the ORM
            # definition.
            conn.execute(text(
                f"INSERT INTO alert_companies ({columns}) SELECT {columns} FROM alert_companies_old"
            ))

            after = conn.execute(text("SELECT COUNT(*) FROM alert_companies")).scalar_one()
            print(f"rows after:  {after}")
            if after != before:
                raise RuntimeError(f"row count changed ({before} -> {after})")

            conn.execute(text("DROP TABLE alert_companies_old"))

            violations = conn.execute(text("PRAGMA foreign_key_check")).fetchall()
            if violations:
                raise RuntimeError(f"foreign_key_check reported violations: {violations}")

            conn.execute(text("COMMIT"))
        except Exception:
            conn.execute(text("ROLLBACK"))
            raise
    finally:
        try:
            conn.execute(text("PRAGMA legacy_alter_table=OFF"))
            conn.execute(text("PRAGMA foreign_keys=ON"))
        finally:
            conn.close()

    print("done; rationale is now nullable" if rationale_is_nullable() else "FAILED: still NOT NULL")


if __name__ == "__main__":
    main()
