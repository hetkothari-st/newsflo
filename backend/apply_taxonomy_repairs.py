# backend/apply_taxonomy_repairs.py
"""Applies taxonomy fixes for companies whose sector/sub_sector are
incoherent -- app.companies.integrity.check_sub_sectors flags a company
whenever its sub_sector isn't in its own sector's branch of
app.companies.sub_sectors.SUB_SECTOR_TAXONOMY.

Two repair passes, run in sequence, followed by a validation pass:

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
   SUB_SECTOR_TAXONOMY) AND that sub_sector is a real, specific value (not
   a "*_other" catch-all bucket), this sets the company's `sector` to that
   owning sector. This is the case a 2026-08 merge that grew the company
   universe from 1,016 to 5,321 rows and reset most sectors to "other"
   created at scale: 126 companies kept a real sub_sector (e.g.
   BAJAJ-AUTO.NS / two_wheeler, GRASIM.NS / cement) while their sector was
   reset to "other" -- an unambiguous, mechanically-derivable mismatch, not
   a judgment call.

   A "*_other" sub_sector (e.g. "fmcg_other", "metals_other") is
   deliberately excluded from this derivation even though _sector_owning()
   still resolves it to exactly one sector: every sector's taxonomy branch
   has its own catch-all bucket, so "*_other" carries no signal about
   which sector the company actually belongs to -- only that whoever set
   it didn't know. Confirmed live: repairing "fmcg_other" -> fmcg swept in
   six hotel chains, IRCTC (railway ticketing), Naukri/IndiaMART/CarTrade
   (internet plays), and eight consumer-durables makers (Voltas,
   Whirlpool, Havells, Dixon...); "metals_other" -> metals promoted
   ADANIENT.NS -- a ports-and-airports conglomerate -- to the #1 spot in
   the metals fan-out. These rows are reported (status="catchall_skipped")
   and left completely untouched, same as an unknown/ambiguous sub_sector.

   Where the sub_sector is unknown to the taxonomy or (not currently
   possible, but not assumed) claimed by more than one sector, the row is
   left untouched and reported, never guessed.

3. A validation pass (_assert_no_new_violations) that re-runs
   check_sub_sectors() after both repair passes above and compares its
   result against a snapshot taken before either pass ran. Confirmed live:
   an earlier version of the ASIANPAINT.NS explicit entry set only `sector`
   (fmcg -> chemicals) and was correct against the dev database, where the
   row started other/paints -- but production's row started
   other/personal_care, so that same entry would have landed
   chemicals/personal_care, which is ITSELF a fresh check_sub_sectors
   violation ("personal_care" is fmcg's, not chemicals'). A repair script
   that can create the exact defect it exists to remove must not exit
   successfully -- so this pass raises TaxonomyRepairIntegrityError (and the
   session is rolled back, dry-run or not) whenever the post-repair state
   contains a violation signature -- (ticker, sector, sub_sector) -- that
   wasn't already present before this run. See TAXONOMY_REPAIRS above,
   which now sets both fields for ASIANPAINT.NS so the repair is correct
   regardless of which environment it runs against.

Both repair passes are idempotent and safe to re-run: a row already carrying the
expected value is reported "already correct" (explicit pass) or simply
stops appearing as a violation (derived pass) and is left untouched, so
running this against a database where the fixes already landed changes
nothing and reports that cleanly. Plain ORM attribute reads/writes only --
no dialect-specific SQL -- so it runs unmodified against SQLite (local dev)
and PostgreSQL (production) alike.

Note: app.db.SessionLocal is created with autoflush=False, so the derived
pass explicitly flushes after the explicit pass before it queries. This
matters specifically for check_sub_sectors()'s SQL-level
`Company.sub_sector.isnot(None)` predicate: a future explicit repair that
sets sub_sector on a row FROM NULL needs that flush for the predicate to
even see the row. It is not needed for the current TAXONOMY_REPAIRS
entries' in-place attribute changes (personal_care -> retail, etc.) --
those rows are already non-null in the DB, so the WHERE clause matches
them regardless of flush, and the derived pass's query returns the SAME
still-dirty Python objects via SQLAlchemy's identity map either way. Kept
anyway because it costs nothing and protects the next repair-table entry
that isn't shaped like today's three.

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
# - ASIANPAINT.NS: BOTH sector -> chemicals AND sub_sector -> paints.
#   Asian Paints is a paints manufacturer; "paints" is a chemicals
#   sub-sector (SUB_SECTOR_TAXONOMY["chemicals"] includes "paints" and no
#   other branch does -- confirmed unambiguous). Both fields are repaired
#   explicitly, regardless of the row's starting sub_sector, because that
#   starting value differs by environment: dev had other/paints (only
#   sector was wrong), production has other/personal_care (both fields are
#   wrong). A sector-only fix is correct against dev and silently WRONG
#   against production -- it would land chemicals/personal_care, which is
#   itself a fresh taxonomy violation ("personal_care" belongs to fmcg, not
#   chemicals) and exactly the class of bug this script exists to remove.
#   Setting both fields makes the repair correct regardless of which
#   environment it runs against, and the post-repair validation pass below
#   (see _assert_no_new_violations) fails loudly if a future edit to this
#   table reintroduces a mismatched pair like that.
# - INDIGO.NS: sector -> railways_transport. An airline, not a generic
#   "other" company -- railways_transport's branch is where aviation
#   belongs (see SUB_SECTOR_TAXONOMY["railways_transport"]). Its sub_sector
#   is NULL in both dev and production, so there is nothing for a second
#   field-entry to fix here -- NULL sub_sector is never a violation.
#
# These four stay hardcoded even though the derived pass below (Job 2's
# generalisation) could reproduce ASIANPAINT.NS's sector and INDIGO.NS's
# fix on its own -- ETERNAL.NS's and ASIANPAINT.NS's sub_sector rewrites
# cannot be derived (they're judgment calls about which specific sub_sector
# a company belongs to, not a sector lookup), and keeping all four together
# in one reviewed table is clearer than splitting judgment calls from
# lookups that happen to agree with them.
TAXONOMY_REPAIRS: tuple[tuple[str, str, str], ...] = (
    ("ETERNAL.NS", "sub_sector", "retail"),
    ("ASIANPAINT.NS", "sector", "chemicals"),
    ("ASIANPAINT.NS", "sub_sector", "paints"),
    ("INDIGO.NS", "sector", "railways_transport"),
)

_VALID_FIELDS = frozenset({"sector", "sub_sector"})


class TaxonomyRepairIntegrityError(RuntimeError):
    """Raised when, after both repair passes, check_sub_sectors() reports a
    sector/sub_sector violation that did NOT exist before this run started
    -- i.e. the repairs themselves manufactured a fresh instance of the
    exact defect this script exists to remove (see _assert_no_new_violations
    and the ASIANPAINT.NS incident documented on TAXONOMY_REPAIRS above:
    a sector-only fix that was correct against dev's other/paints but wrong
    against production's other/personal_care, landing chemicals/personal_care
    -- a brand new violation). apply_taxonomy_repairs rolls the session back
    before raising this, in both dry-run and real runs, so a run that would
    create such a violation never commits it -- refusing to write a bad
    state is strictly better than reporting success on one."""


@dataclass(frozen=True)
class RepairResult:
    ticker: str
    field: str
    expected: str | None
    previous: str | None
    status: str  # "applied" | "already_correct" | "not_found" | "ambiguous" | "catchall_skipped"
    # Extra context for the derived pass only (which sub_sector drove the
    # fix, or why an ambiguous/unknown/catch-all one was left alone). None
    # for every explicit-table result.
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
    function never guesses. Nor does it repair a "*_other" catch-all
    sub_sector, even when _sector_owning() resolves it to exactly one
    sector: every sector has its own catch-all bucket, so owning it
    unambiguously still carries no real signal about where the company
    belongs (see the module docstring for the fmcg_other/metals_other
    incidents this guards against). Those rows get status="catchall_skipped"
    and are reported separately from "ambiguous", also left untouched."""
    results = []
    for violation in check_sub_sectors(session):
        if violation.sub_sector.endswith("_other"):
            results.append(RepairResult(
                violation.ticker, "sector", expected=None, previous=violation.sector,
                status="catchall_skipped",
                note=(
                    f"sub_sector {violation.sub_sector!r} is a catch-all bucket -- its unambiguous "
                    f"owning sector ({violation.correct_sector!r}) carries no real signal about this "
                    "company, so it was left unchanged rather than repaired"
                ),
            ))
            continue

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


def _violation_signature(violation) -> tuple[str, str, str]:
    """A violation's identity for before/after comparison: which row, and
    exactly which (sector, sub_sector) pairing is the problem. Comparing on
    the full triple -- not just the ticker -- is what lets a pre-existing,
    correctly-left-alone violation (ambiguous or catch-all, unchanged by
    either pass) be told apart from a violation the repairs themselves
    produced: a ticker that was ALREADY violating before this run (e.g.
    production's ASIANPAINT.NS starting as other/personal_care) and is
    STILL violating after with a DIFFERENT pairing (chemicals/personal_care)
    is exactly as new-and-bad as a ticker that wasn't violating at all
    before. Same ticker, same problem-shape, different specific pairing =
    a new violation the guard must catch."""
    return (violation.ticker, violation.sector, violation.sub_sector)


def _assert_no_new_violations(session, baseline_signatures: set[tuple[str, str, str]], dry_run: bool) -> None:
    """Guard of last resort: re-runs check_sub_sectors() after both repair
    passes and compares against the violations present before this run
    started. A repair script whose own repairs can create the thing it
    repairs must not exit successfully -- so any violation signature that
    is new (not present in the baseline) raises TaxonomyRepairIntegrityError
    with every offending row named, instead of silently reporting success.

    Runs identically under --dry-run: the comparison is made against the
    session's current (staged, not-yet-committed) state, so it reports
    exactly what the post-repair state WOULD be without requiring a write.
    The caller is responsible for rolling back before or after this raises;
    this function only reads."""
    final_signatures = {_violation_signature(v) for v in check_sub_sectors(session)}
    new_signatures = final_signatures - baseline_signatures
    if not new_signatures:
        return

    offenders = ", ".join(
        f"{ticker} ({sector}/{sub_sector})" for ticker, sector, sub_sector in sorted(new_signatures)
    )
    verb = "would create" if dry_run else "created"
    raise TaxonomyRepairIntegrityError(
        f"apply_taxonomy_repairs {verb} {len(new_signatures)} new sector/sub_sector "
        f"violation(s) that did not exist before this run: {offenders}. Refusing to "
        f"{'report success' if dry_run else 'commit'} -- fix the offending TAXONOMY_REPAIRS "
        "entry (or SUB_SECTOR_TAXONOMY) before rerunning."
    )


def apply_taxonomy_repairs(session, dry_run: bool = False) -> list[RepairResult]:
    """Runs the explicit pass, then the derived pass, against `session`,
    then validates the result before ever committing (see
    _assert_no_new_violations). Never raises on a missing ticker in the
    explicit table (reports "not_found" instead) -- a repair table entry
    surviving after its target row was independently deleted must not
    crash the whole run. Commits once at the end when dry_run is False and
    validation passes; rolls the whole session back (undoing every staged
    change from both passes) when dry_run is True, or when validation finds
    the repairs produced a fresh violation -- so a bad state is never
    committed, dry-run or not."""
    # Captured before any repair mutates the session, so it reflects the
    # true starting state -- this is what "new" is measured against.
    baseline_signatures = {_violation_signature(v) for v in check_sub_sectors(session)}

    explicit_results = _apply_explicit_repairs(session, dry_run)
    # SessionLocal is autoflush=False (see module docstring). This flush
    # matters for check_sub_sectors()'s SQL-level `sub_sector.isnot(None)`
    # predicate -- a future explicit repair setting sub_sector FROM NULL
    # needs it to be seen at all. Today's TAXONOMY_REPAIRS entries mostly
    # change already-non-null attributes in place, which the derived pass
    # would see via the identity map with or without this flush; kept
    # anyway since it costs nothing and protects the next repair shaped
    # differently from today's.
    session.flush()
    derived_results = _apply_derived_repairs(session)
    # Flushed again for the same reason, ahead of the post-repair
    # validation query below -- it must see the derived pass's writes too.
    session.flush()

    try:
        _assert_no_new_violations(session, baseline_signatures, dry_run)
    except TaxonomyRepairIntegrityError:
        session.rollback()
        raise

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
        elif r.status == "catchall_skipped":
            print(f"  {r.ticker:18} {r.field:12} SKIPPED (catch-all), not fixed: {r.note}")
        else:
            suffix = f"  ({r.note})" if r.note else ""
            print(f"  {r.ticker:18} {r.field:12} {verb} {r.previous!r} -> {r.expected!r}{suffix}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="report what would change without writing anything")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        try:
            results = apply_taxonomy_repairs(session, dry_run=args.dry_run)
        except TaxonomyRepairIntegrityError as exc:
            print(f"\nFAILED: {exc}")
            raise SystemExit(1) from exc
        _print_report(results, args.dry_run)
        applied = sum(1 for r in results if r.status == "applied")
        ambiguous = sum(1 for r in results if r.status == "ambiguous")
        catchall_skipped = sum(1 for r in results if r.status == "catchall_skipped")
        print(f"\n{applied} {'would be fixed' if args.dry_run else 'fixed'}, "
              f"{ambiguous} reported (ambiguous/unknown, left alone), "
              f"{catchall_skipped} reported (catch-all sub_sector, left alone).")
        print("\n--dry-run: nothing written." if args.dry_run else "\nDone.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
