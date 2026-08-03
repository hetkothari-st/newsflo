# backend/cleanup_orphan_company_refs.py
"""One-off cleanup for two DISTINCT orphan classes, both caused by deleting
a parent row without deleting the rows that reference it (SQLite leaves
foreign-key enforcement OFF by default, so both are invisible in normal
operation and only surface when something runs `PRAGMA foreign_key_check`):

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
   _ALERT_COMPANY_DEPENDENTS rows before the alert_companies row itself,
   reusing the same list this script exports), but this script still needs
   to find and clean up whatever was left behind by the buggy version that
   already ran.

Reported and cleaned up separately (case 1's counts vs. case 2's) so the
two causes stay distinguishable -- they are unrelated bugs that happen to
produce the same symptom in the same four tables.

Separate, single-purpose script: fixes a different problem than either
repair_rationale_nullable.py (schema) or migrate_precision.py (presentation
of already-valid rows). Idempotent: a second run finds zero rows
everywhere. Pass --dry-run to see counts without deleting.
"""
import argparse

from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    AlertCompany,
    AlertCompanyTranslation,
    CalibrationSample,
    CarOutcome,
    Company,
    EmailNotification,
    MarketMove,
)

# Tables that reference alert_companies.id via alert_company_id -- must be
# cleared before an alert_companies row (orphaned or otherwise) is deleted.
# Imported by migrate_precision.py too, so both scripts agree on exactly
# which tables reference alert_companies.
_ALERT_COMPANY_DEPENDENTS = (CalibrationSample, CarOutcome, EmailNotification, AlertCompanyTranslation)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    session = SessionLocal()
    try:
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
            for model in _ALERT_COMPANY_DEPENDENTS:
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
        for model in _ALERT_COMPANY_DEPENDENTS:
            case2_dependent_rows.extend(
                session.query(model)
                .filter(~model.alert_company_id.in_(existing_alert_company_ids))
                .all()
            )

        print(f"[case 1: orphaned by a deleted company]")
        print(f"  alert_companies rows with no matching company:              {len(orphan_alert_companies)}")
        print(f"  market_moves rows with no matching company:                 {len(orphan_market_moves)}")
        print(f"  dependent rows referencing those alert_companies rows"
              f" (calibration/outcome/notification/translation): {len(case1_dependent_rows)}")
        print(f"[case 2: orphaned by a deleted alert_companies row, company unrelated]")
        print(f"  dependent rows referencing an alert_companies row that no longer exists"
              f" (calibration/outcome/notification/translation): {len(case2_dependent_rows)}")

        if args.dry_run:
            print("\n--dry-run: nothing deleted.")
            return

        # Dependents first, then the alert_companies rows they reference,
        # then the standalone market_moves orphans. Case 2's rows are leaf
        # deletes -- nothing references calibration_samples/car_outcomes/
        # email_notifications/alert_company_translations rows themselves.
        for row in case1_dependent_rows:
            session.delete(row)
        for row in case2_dependent_rows:
            session.delete(row)
        for row in orphan_alert_companies:
            session.delete(row)
        for row in orphan_market_moves:
            session.delete(row)
        session.commit()
        print("\nDone.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
