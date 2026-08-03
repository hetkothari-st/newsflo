# backend/apply_taxonomy_repairs.py
"""Applies the specific taxonomy fixes backend/audit_taxonomy.py's own
docstring identifies as the root cause of a real, confirmed-live bug:
ETERNAL.NS (food delivery) was tagged fmcg/personal_care, which put it in
the SAME sub_sector as HUL -- and app.companies.resolution._TIER_RANK ranks
NIFTY50 first, so when a crude-oil story's fmcg fan-out looked for a
personal_care anchor, it reached for ETERNAL.NS before HUL and showed food
delivery as "directly affected" by a crude-oil supply shock.

Until now these three fixes existed ONLY as manual edits to the untracked
dev database (backend/newsflo.db, gitignored, never deployed) -- production
Postgres has never received them, so the ETERNAL.NS bug is still live there
today. audit_taxonomy.py is deliberately read-only (see its own docstring),
so it was never going to apply anything; this script is the write side,
built to be reviewed, re-run, and trusted rather than hand-edited again.

Driven entirely by TAXONOMY_REPAIRS below -- an explicit, auditable
(ticker, field, expected_value) table, not hand-rolled per-row SQL --
so a reviewer can see exactly what will change before it changes, and a new
repair is a one-line addition rather than a new code path.

Idempotent and safe to re-run: a row already carrying the expected value is
reported "already correct" and left untouched, so running this against a
database where the fix already landed (by this script's own prior run, or
by any other means) changes nothing and reports that cleanly. Plain ORM
attribute reads/writes only -- no dialect-specific SQL -- so it runs
unmodified against SQLite (local dev) and PostgreSQL (production) alike.

Usage (from the backend/ directory):
    .venv/Scripts/python apply_taxonomy_repairs.py --dry-run
    .venv/Scripts/python apply_taxonomy_repairs.py
    railway run python apply_taxonomy_repairs.py   # against production
"""
import argparse
from dataclasses import dataclass

from app.db import SessionLocal
from app.models import Company

# (ticker, field, expected_value). field must be "sector" or "sub_sector"
# (see _VALID_FIELDS below) -- the two Company columns audit_taxonomy.py
# flags. Each entry here is a confirmed, reviewed fix, not a guess:
#
# - ETERNAL.NS: sub_sector personal_care -> retail. Food delivery, not
#   personal care -- this is the exact mis-tagging that let ETERNAL.NS
#   anchor the fmcg/personal_care sub-sector fan-out alongside HUL.
# - ASIANPAINT.NS: sector fmcg -> chemicals. Paints is a chemicals
#   sub-sector (SUB_SECTOR_TAXONOMY["chemicals"] includes "paints"; fmcg's
#   branch does not), confirmed by check_sub_sectors as an unambiguous
#   single-owner violation.
# - INDIGO.NS: sector -> railways_transport. An airline, not a generic
#   "other" company -- railways_transport's branch is where aviation
#   belongs (see SUB_SECTOR_TAXONOMY["railways_transport"]).
TAXONOMY_REPAIRS: tuple[tuple[str, str, str], ...] = (
    ("ETERNAL.NS", "sub_sector", "retail"),
    ("ASIANPAINT.NS", "sector", "chemicals"),
    ("INDIGO.NS", "sector", "railways_transport"),
)

_VALID_FIELDS = frozenset({"sector", "sub_sector"})


@dataclass(frozen=True)
class RepairResult:
    ticker: str
    field: str
    expected: str
    previous: str | None
    status: str  # "applied" | "already_correct" | "not_found"


def apply_taxonomy_repairs(session, dry_run: bool = False) -> list[RepairResult]:
    """Applies (or, when dry_run, only inspects) every (ticker, field,
    expected_value) repair in TAXONOMY_REPAIRS. Never raises on a missing
    ticker (reports "not_found" instead) -- a repair table entry surviving
    after its target row was independently deleted must not crash the
    whole run. Commits once at the end when dry_run is False; makes no
    write at all when dry_run is True."""
    results: list[RepairResult] = []
    for ticker, field, expected in TAXONOMY_REPAIRS:
        if field not in _VALID_FIELDS:
            raise ValueError(f"unsupported field {field!r} in TAXONOMY_REPAIRS -- must be one of {_VALID_FIELDS}")

        company = session.query(Company).filter_by(ticker=ticker).one_or_none()
        if company is None:
            results.append(RepairResult(ticker, field, expected, previous=None, status="not_found"))
            continue

        previous = getattr(company, field)
        if previous == expected:
            results.append(RepairResult(ticker, field, expected, previous, status="already_correct"))
            continue

        if not dry_run:
            setattr(company, field, expected)
        results.append(RepairResult(ticker, field, expected, previous, status="applied"))

    if not dry_run:
        session.commit()
    return results


def _print_report(results: list[RepairResult], dry_run: bool) -> None:
    for r in results:
        if r.status == "not_found":
            print(f"  {r.ticker:18} {r.field:12} SKIPPED: no Company row with this ticker")
        elif r.status == "already_correct":
            print(f"  {r.ticker:18} {r.field:12} already {r.expected!r} -- nothing to do")
        else:
            verb = "would set" if dry_run else "set"
            print(f"  {r.ticker:18} {r.field:12} {verb} {r.previous!r} -> {r.expected!r}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="report what would change without writing anything")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        results = apply_taxonomy_repairs(session, dry_run=args.dry_run)
        _print_report(results, args.dry_run)
        print("\n--dry-run: nothing written." if args.dry_run else "\nDone.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
