# backend/migrate_precision.py
"""One-off migration bringing existing alerts in line with the precision
fixes (docs/superpowers/specs/2026-08-03-impact-analysis-precision-design.md
Section 10). Zero LLM calls.

Three changes, all to already-persisted AlertCompany rows:
1. Clear the template rationale on every sector_inference row -- it reads as
   per-company analysis but was built from the sector's one-line mechanism.
2. Drop rows below CONFIDENCE_FLOOR.
3. Drop rows pointing at a demo company that no longer exists.

Bucket routing needs no migration: app.market.ripple_layers dispatches on
basis at READ time, so every existing sector_inference row moves to
SECTOR_WIDE the moment Task 4 ships.

Reporting-only, fourth check: rows whose company_id matches no row in
`companies` at all, not just a still-resolvable demo ticker. This class of
problem was found the hard way -- Task 2 deleted the demo company but left
its alert_companies/market_moves rows dangling, and the demo-row check
above is structurally unable to catch it (it resolves DEMO_TICKERS ->
companies.id, and once that company row is gone there is nothing left to
resolve to, so it always reports 0 regardless of how many orphans remain).
This script does NOT delete these rows -- that is
cleanup_orphan_company_refs.py's job, kept separate on purpose. This check
only makes sure a future run surfaces the problem instead of silently
reporting a clean zero.

Deleting an AlertCompany row (steps 2/3 above) must delete its own
dependents first -- CalibrationSample, CarOutcome, EmailNotification, and
AlertCompanyTranslation all reference alert_companies.id, and SQLite's
default (off) FK enforcement will not catch a row left dangling. This is
the same class of bug Task 2 introduced against `companies` (fixed in
app.companies.integrity.delete_demo_companies) and a first, buggy version
of this script introduced against `alert_companies` itself -- confirmed
live: deleting sub-floor rows left 8 alert_company_translations and 4
calibration_samples rows orphaned. _ALERT_COMPANY_DEPENDENTS is imported
from cleanup_orphan_company_refs.py rather than redefined here, since both
scripts must agree on exactly which tables reference alert_companies.

Idempotent: re-running changes nothing further. Pass --dry-run to see counts
without writing.
"""
import argparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.companies.integrity import DEMO_TICKERS
from app.db import SessionLocal
from app.models import AlertCompany, Company
from app.pipeline import CONFIDENCE_FLOOR
from cleanup_orphan_company_refs import _ALERT_COMPANY_DEPENDENTS


def run_migration(session: Session, dry_run: bool = False) -> None:
    template_rows = (
        session.query(AlertCompany)
        .filter(AlertCompany.basis == "sector_inference")
        .filter(AlertCompany.rationale.isnot(None))
        .all()
    )
    low_rows = (
        session.query(AlertCompany)
        .filter(AlertCompany.confidence_score < CONFIDENCE_FLOOR)
        .all()
    )
    demo_company_ids = [
        c.id for c in session.query(Company).filter(Company.ticker.in_(DEMO_TICKERS)).all()
    ]
    demo_rows = (
        session.query(AlertCompany)
        .filter(AlertCompany.company_id.in_(demo_company_ids))
        .all()
    ) if demo_company_ids else []
    # Reporting only -- see the module docstring. Any company_id with no
    # matching companies.id row, regardless of which (possibly already-
    # deleted) company it used to point at.
    orphan_rows = (
        session.query(AlertCompany)
        .filter(~AlertCompany.company_id.in_(select(Company.id)))
        .all()
    )

    print(f"sector_inference rows with a template rationale: {len(template_rows)}")
    print(f"rows below confidence floor {CONFIDENCE_FLOOR}:         {len(low_rows)}")
    print(f"rows pointing at a demo company:                  {len(demo_rows)}")
    print(f"rows pointing at NO existing company (orphaned):  {len(orphan_rows)}"
          + ("  <-- run cleanup_orphan_company_refs.py" if orphan_rows else ""))

    if dry_run:
        print("\n--dry-run: nothing written.")
        return

    for row in template_rows:
        row.rationale = None
        row.key_points_json = "[]"

    # Delete after the rationale pass so a row that is both gets counted
    # in both totals above but deleted once.
    rows_to_delete = list({id(r): r for r in (low_rows + demo_rows)}.values())
    rows_to_delete_ids = [r.id for r in rows_to_delete]

    # Dependents of the alert_companies rows we're about to delete, gone
    # first -- or they become new orphans the moment those rows disappear.
    if rows_to_delete_ids:
        for model in _ALERT_COMPANY_DEPENDENTS:
            session.query(model).filter(
                model.alert_company_id.in_(rows_to_delete_ids)
            ).delete(synchronize_session=False)

    for row in rows_to_delete:
        session.delete(row)
    session.commit()
    print("\nDone.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        run_migration(session, dry_run=args.dry_run)
    finally:
        session.close()


if __name__ == "__main__":
    main()
