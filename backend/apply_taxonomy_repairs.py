# backend/apply_taxonomy_repairs.py
"""Applies taxonomy fixes for companies whose sector/sub_sector are
incoherent -- app.companies.integrity.check_sub_sectors flags a company
whenever its sub_sector isn't in its own sector's branch of
app.companies.sub_sectors.SUB_SECTOR_TAXONOMY.

Two repair passes, run in sequence:

1. TAXONOMY_REPAIRS below -- an explicit, auditable (ticker, field,
   expected_value) table. These are confirmed, reviewed judgment calls, not
   guesses: e.g. ETERNAL.NS (food delivery) was tagged fmcg/personal_care,
   which put it in the SAME sub_sector as HUL -- and
   app.companies.resolution._TIER_RANK ranks NIFTY50 first, so when a
   crude-oil story's fmcg fan-out looked for a personal_care anchor, it
   reached for ETERNAL.NS before HUL and showed food delivery as "directly
   affected" by a crude-oil supply shock. Its fix (sub_sector -> "retail")
   is not something a mechanical derivation could produce, because "retail"
   sits in fmcg's own branch of the taxonomy -- moving ETERNAL.NS out of
   personal_care took a human call about where it actually belongs, not a
   lookup.

2. A derived pass over every REMAINING check_sub_sectors() violation (run
   after the explicit pass above, so a violation the explicit table already
   fixed isn't double-reported). For each one, if the sub_sector's owning
   sector is unambiguous (SubSectorViolation.correct_sector is not None --
   i.e. the sub_sector name appears in exactly one branch of
   SUB_SECTOR_TAXONOMY), this sets the company's `sector` to that owning
   sector. This is the case a 2026-08 merge that grew the company universe
   from 1,016 to 5,321 rows and reset most sectors to "other" created at
   scale: 126 companies kept a real sub_sector (e.g. BAJAJ-AUTO.NS /
   two_wheeler, GRASIM.NS / cement) while their sector was reset to
   "other" -- an unambiguous, mechanically-derivable mismatch, not a
   judgment call. Where the sub_sector is unknown to the taxonomy or (not
   currently possible, but not assumed) claimed by more than one sector,
   the row is left untouched and reported, never guessed.

Both passes are idempotent and safe to re-run: a row already carrying the
expected value is reported "already correct" (explicit pass) or simply
stops appearing as a violation (derived pass) and is left untouched, so
running this against a database where the fixes already landed changes
nothing and reports that cleanly. Plain ORM attribute reads/writes only --
no dialect-specific SQL -- so it runs unmodified against SQLite (local dev)
and PostgreSQL (production) alike.

Note: app.db.SessionLocal is created with autoflush=False, so the derived
pass explicitly flushes after the explicit pass before it queries -- without
that, the derived pass's check_sub_sectors() query would run against
pre-explicit-repair data even within the same still-uncommitted session.

Usage (from the backend/ directory):
    .venv/Scripts/python apply_taxonomy_repairs.py --dry-run
    .venv/Scripts/python apply_taxonomy_repairs.py
    railway run python apply_taxonomy_repairs.py   # against production
"""
import argparse
from dataclasses import dataclass

from app.companies.integrity import check_sub_sectors
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
#
# These three stay hardcoded even though the derived pass below (Job 2's
# generalisation) could reproduce ASIANPAINT.NS and INDIGO.NS's fixes on
# its own -- ETERNAL.NS's cannot be derived (it's a sub_sector rewrite,
# not a sector lookup), and keeping all three together in one reviewed
# table is clearer than splitting judgment calls from lookups that happen
# to agree with them.
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
    expected: str | None
    previous: str | None
    status: str  # "applied" | "already_correct" | "not_found" | "ambiguous"
    # Extra context for the derived pass only (which sub_sector drove the
    # fix, or why an ambiguous/unknown one was left alone). None for every
    # explicit-table result.
    note: str | None = None


def _apply_explicit_repairs(session, dry_run: bool) -> list[RepairResult]:
    """Stages every (ticker, field, expected_value) repair in
    TAXONOMY_REPAIRS onto `session` -- always via setattr, even when
    dry_run, so the derived pass that follows reasons about the correct
    post-explicit-repair state. The caller rolls the whole session back at
    the end when dry_run is True, so nothing is actually persisted."""
    results = []
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

        setattr(company, field, expected)
        results.append(RepairResult(ticker, field, expected, previous, status="applied"))
    return results


def _apply_derived_repairs(session) -> list[RepairResult]:
    """Second, derived repair pass: for every sector/sub_sector coherence
    violation still present after the explicit pass above (per
    app.companies.integrity.check_sub_sectors), fixes `sector` when the
    sub_sector's owning sector is unambiguous. Never touches sub_sector --
    a derivation over "which sector's branch already contains this
    sub_sector" can only tell you the sector, never invent a different
    sub_sector for the row.

    Ambiguous or taxonomy-unknown sub_sectors (correct_sector is None) are
    reported with status="ambiguous" and left completely untouched -- this
    function never guesses."""
    results = []
    for violation in check_sub_sectors(session):
        if violation.correct_sector is None:
            results.append(RepairResult(
                violation.ticker, "sector", expected=None, previous=violation.sector,
                status="ambiguous",
                note=f"sub_sector {violation.sub_sector!r} is not owned by exactly one sector -- left unchanged",
            ))
            continue

        company = session.query(Company).filter_by(ticker=violation.ticker).one()
        previous = company.sector
        setattr(company, "sector", violation.correct_sector)
        results.append(RepairResult(
            violation.ticker, "sector", violation.correct_sector, previous, status="applied",
            note=f"derived from sub_sector {violation.sub_sector!r}",
        ))
    return results


def apply_taxonomy_repairs(session, dry_run: bool = False) -> list[RepairResult]:
    """Runs the explicit pass, then the derived pass, against `session`.
    Never raises on a missing ticker in the explicit table (reports
    "not_found" instead) -- a repair table entry surviving after its target
    row was independently deleted must not crash the whole run. Commits
    once at the end when dry_run is False; rolls the whole session back
    (undoing every staged change from both passes) when dry_run is True, so
    no write survives."""
    explicit_results = _apply_explicit_repairs(session, dry_run)
    # SessionLocal is autoflush=False (see module docstring) -- without an
    # explicit flush here, the derived pass's check_sub_sectors() query
    # would not see the explicit pass's still-pending changes, even within
    # the same uncommitted transaction.
    session.flush()
    derived_results = _apply_derived_repairs(session)

    if dry_run:
        session.rollback()
    else:
        session.commit()
    return explicit_results + derived_results


def _print_report(results: list[RepairResult], dry_run: bool) -> None:
    verb = "would set" if dry_run else "set"
    for r in results:
        if r.status == "not_found":
            print(f"  {r.ticker:18} {r.field:12} SKIPPED: no Company row with this ticker")
        elif r.status == "already_correct":
            print(f"  {r.ticker:18} {r.field:12} already {r.expected!r} -- nothing to do")
        elif r.status == "ambiguous":
            print(f"  {r.ticker:18} {r.field:12} REPORTED, not fixed: {r.note}")
        else:
            suffix = f"  ({r.note})" if r.note else ""
            print(f"  {r.ticker:18} {r.field:12} {verb} {r.previous!r} -> {r.expected!r}{suffix}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="report what would change without writing anything")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        results = apply_taxonomy_repairs(session, dry_run=args.dry_run)
        _print_report(results, args.dry_run)
        applied = sum(1 for r in results if r.status == "applied")
        ambiguous = sum(1 for r in results if r.status == "ambiguous")
        print(f"\n{applied} {'would be fixed' if args.dry_run else 'fixed'}, "
              f"{ambiguous} reported (ambiguous/unknown, left alone).")
        print("\n--dry-run: nothing written." if args.dry_run else "\nDone.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
