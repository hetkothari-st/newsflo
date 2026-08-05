# backend/cleanup_orphan_company_refs.py
"""One-off cleanup for three DISTINCT orphan classes, all caused by
deleting a parent row without deleting the rows that reference it (SQLite
leaves foreign-key enforcement OFF by default, so all three are invisible
in normal operation and only surface when something runs
`PRAGMA foreign_key_check`):

1. A `companies` row deleted with its dependents left dangling. Task 2
   deleted the demo company (SOMETEXTILE.NS) but left its own
   alert_companies/market_moves rows pointing at a company_id that no
   longer exists: alert_companies 858 (alert 9017, direct_mention) and 887
   (alert 9020, sector_inference); market_moves 21 and 50. Also cascades
   into alert_company_translations/calibration_samples/car_outcomes/
   email_notifications rows that reference those specific alert_companies
   rows (confirmed live: 7 alert_company_translations rows referenced
   alert_company_id 858).

   migrate_precision.py's demo-row branch cannot clean this up itself: it
   resolves DEMO_TICKERS -> companies.id, and that company row is already
   gone, so it can never match -- see the orphan count added to that
   script's reporting.

2. An `alert_companies` row deleted with ITS dependents left dangling --
   the same bug, one level down, reproduced by a first, buggy version of
   migrate_precision.py's own sub-floor/demo-row deletion (confirmed live:
   8 alert_company_translations rows + 4 calibration_samples rows pointing
   at alert_company_ids that migrate_precision.py had already deleted).
   Fixed at the root in migrate_precision.py (it now deletes
   ALERT_COMPANY_DEPENDENTS rows before the alert_companies row itself),
   but this script still needs to find and clean up whatever was left
   behind by the buggy version that already ran.

3. A `market_moves` row left behind by an `alert_companies` row deletion
   that did NOT also delete the matching MarketMove. MarketMove references
   alert_id/company_id directly, not alert_company_id, so it is NOT in
   ALERT_COMPANY_DEPENDENTS and neither case 1 nor case 2's cleanup (nor
   the dependents loops in migrate_precision.py / reanalyze_cascade.py
   themselves, before their own fixes) ever touched it. Distinct from case
   1's orphan_market_moves: case 1 catches a MarketMove whose company_id
   points at a company that no longer exists at all; case 3 catches a
   MarketMove whose company still exists, but the specific (alert_id,
   company_id) pairing has no surviving alert_companies row -- i.e. this
   alert's own analysis moved on (or was reanalyzed, or lost a sub-floor
   row) without that measurement being cleaned up. This exact shape
   crashed app.market.alert_measurement.compute_alert_measurement's bare
   next() with StopIteration -- a 500 on GET /api/feed-v2 -- and is now
   fixed at the root in both reanalyze_cascade.py and migrate_precision.py;
   this case exists to sweep up whatever either left behind before those
   fixes landed (confirmed present in the dev database from an earlier
   migrate_precision.py run).

Reported and cleaned up separately (case 1's counts vs. case 2's vs. case
3's) so the causes stay distinguishable -- they are unrelated bugs that
happen to produce the same symptom in the same tables.

ALERT_COMPANY_DEPENDENTS itself lives in app.companies.integrity (not
redefined here, and not in migrate_precision.py either) -- a second copy of
that list is exactly the failure mode this task fixed three times over:
see app.companies.integrity's module comment and
test_integrity.py::test_alert_company_dependents_covers_every_referencing_model.

Separate, single-purpose script: fixes a different problem than either
repair_rationale_nullable.py (schema) or migrate_precision.py (presentation
of already-valid rows). Idempotent: a second run finds zero rows
everywhere. Pass --dry-run to see counts without deleting.
"""
import argparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.companies.integrity import ALERT_COMPANY_DEPENDENTS
from app.db import SessionLocal
from app.models import AlertCompany, Company, MarketMove


def run_cleanup(session: Session, dry_run: bool = False) -> dict[str, int]:
    """Finds (and, unless dry_run, deletes) all three orphan classes
    described in the module docstring. Returns a dict of the counts found
    -- same keys regardless of dry_run -- so a caller (main() below, or a
    test) can assert on exactly what this run found/removed without
    re-parsing printed output."""
    existing_company_ids = select(Company.id)
    existing_alert_company_ids = select(AlertCompany.id)

    # Case 1: a company was deleted, its own alert_companies/
    # market_moves rows are left dangling.
    orphan_alert_companies = (
        session.query(AlertCompany)
        .filter(~AlertCompany.company_id.in_(existing_company_ids))
        .all()
    )
    orphan_market_moves = (
        session.query(MarketMove)
        .filter(~MarketMove.company_id.in_(existing_company_ids))
        .all()
    )
    orphan_alert_company_ids = [row.id for row in orphan_alert_companies]

    case1_dependent_rows = []
    if orphan_alert_company_ids:
        for model in ALERT_COMPANY_DEPENDENTS:
            case1_dependent_rows.extend(
                session.query(model)
                .filter(model.alert_company_id.in_(orphan_alert_company_ids))
                .all()
            )

    # Case 2: an alert_companies row was deleted (for any reason --
    # e.g. migrate_precision.py's confidence-floor/demo-row deletion,
    # nothing to do with a company being deleted), its own dependents
    # in the four tables above are left dangling. Distinct from case 1:
    # the alert_companies row here is ALREADY gone, not merely about to
    # be deleted in this run.
    case2_dependent_rows = []
    for model in ALERT_COMPANY_DEPENDENTS:
        case2_dependent_rows.extend(
            session.query(model)
            .filter(~model.alert_company_id.in_(existing_alert_company_ids))
            .all()
        )

    # Case 3: a market_moves row whose company still exists, but no
    # alert_companies row survives for this specific (alert_id,
    # company_id) pair. Filtered in Python rather than a SQL row-value
    # IN (SELECT ...) -- this is a one-off, low-frequency cleanup
    # script, not a hot path, and a plain set lookup avoids relying on
    # SQLite's row-value comparison support. Restricted to company_id IN
    # existing_company_ids so a row already counted in orphan_market_moves
    # (case 1) is never double-counted here.
    existing_pairs = {
        (row.alert_id, row.company_id)
        for row in session.query(AlertCompany.alert_id, AlertCompany.company_id).all()
    }
    case3_orphan_market_moves = [
        mm for mm in (
            session.query(MarketMove)
            .filter(MarketMove.company_id.in_(existing_company_ids))
            .all()
        )
        if (mm.alert_id, mm.company_id) not in existing_pairs
    ]

    print(f"[case 1: orphaned by a deleted company]")
    print(f"  alert_companies rows with no matching company:              {len(orphan_alert_companies)}")
    print(f"  market_moves rows with no matching company:                 {len(orphan_market_moves)}")
    print(f"  dependent rows referencing those alert_companies rows"
          f" (calibration/outcome/notification/translation): {len(case1_dependent_rows)}")
    print(f"[case 2: orphaned by a deleted alert_companies row, company unrelated]")
    print(f"  dependent rows referencing an alert_companies row that no longer exists"
          f" (calibration/outcome/notification/translation): {len(case2_dependent_rows)}")
    print(f"[case 3: market_moves left behind by an alert_companies deletion]")
    print(f"  market_moves rows whose (alert_id, company_id) has no surviving alert_companies row: "
          f"{len(case3_orphan_market_moves)}")

    counts = {
        "orphan_alert_companies": len(orphan_alert_companies),
        "orphan_market_moves": len(orphan_market_moves),
        "case1_dependent_rows": len(case1_dependent_rows),
        "case2_dependent_rows": len(case2_dependent_rows),
        "case3_orphan_market_moves": len(case3_orphan_market_moves),
    }

    if dry_run:
        print("\n--dry-run: nothing deleted.")
        return counts

    # Dependents first, then the alert_companies rows they reference,
    # then the standalone market_moves orphans (case 1 and case 3
    # alike -- both are leaf deletes, nothing references market_moves
    # rows). Case 2's rows are also leaf deletes -- nothing references
    # calibration_samples/car_outcomes/email_notifications/
    # alert_company_translations rows themselves.
    for row in case1_dependent_rows:
        session.delete(row)
    for row in case2_dependent_rows:
        session.delete(row)
    for row in orphan_alert_companies:
        session.delete(row)
    for row in orphan_market_moves:
        session.delete(row)
    for row in case3_orphan_market_moves:
        session.delete(row)
    session.commit()
    print("\nDone.")
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        run_cleanup(session, dry_run=args.dry_run)
    finally:
        session.close()


if __name__ == "__main__":
    main()
