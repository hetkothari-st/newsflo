"""TASK 1.5 -- the nightly staleness job.

    python scripts/flag_stale_exposures.py
    python scripts/flag_stale_exposures.py --db sqlite:///./newsflo.db --as-of 2026-08-17

Sets `company_exposure.stale` to whatever the dates say, and prints the
ledger's age metrics. Idempotent: a second run reports 0 changed rows.

DELIBERATELY NOT SCHEDULED. Nothing registers this with the app's scheduler:
the controller adaptation requires a new config flag defaulting to FALSE
before any automatic run, and existing scheduler jobs are not touched. Run it
by hand or from cron.

It holds no reviewer privilege and must not: `stale` is a DERIVED flag, and
the ledger's write guard is scoped to the claim columns precisely so this job
can maintain it without being able to change what a filing said.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import sqlalchemy as sa  # noqa: E402

from app.ledger.coverage import age_alert, metrics_text  # noqa: E402
from app.ledger.staleness import flag_stale_exposures  # noqa: E402


def run(engine, *, as_of: date, verbose: bool = False) -> int:
    """Flag/unflag, then report. Returns the number of rows that CHANGED."""
    with engine.begin() as connection:
        changed = flag_stale_exposures(connection, as_of=as_of)
        alert = age_alert(connection, as_of=as_of)
        metrics = metrics_text(connection, as_of=as_of)
    if verbose:
        print(f"[ledger] {changed} exposure row(s) changed staleness state "
              f"as of {as_of.isoformat()}")
        print(metrics)
        if alert:
            print(f"[ledger] ALERT: {alert}")
    return changed


def _default_db_url() -> str:
    return os.environ.get("DATABASE_URL", "sqlite:///./newsflo.db")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Flag exposures past their freshness window as STALE.")
    parser.add_argument("--db", default=None,
                        help="SQLAlchemy URL (default: $DATABASE_URL, else "
                             "sqlite:///./newsflo.db)")
    parser.add_argument("--as-of", default=None,
                        help="ISO date to evaluate staleness at (default: today "
                             "in UTC). Stated explicitly so a run is reproducible.")
    args = parser.parse_args(argv)

    as_of = (date.fromisoformat(args.as_of) if args.as_of
             else datetime.now(timezone.utc).date())
    engine = sa.create_engine(args.db or _default_db_url())
    try:
        run(engine, as_of=as_of, verbose=True)
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
