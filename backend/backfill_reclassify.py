"""Re-derive Company.sector from the official classification already stored.

Needed because sector_map was keyed on BSE's Sector level while its table was
built from IndustryNew names, leaving 3,113 of 4,814 Indian companies as
"other" in production (2,971 of them despite having a valid classification).
Task 1 fixes the mapping; this applies it to rows already in the database.

No fetching: official_sector and official_industry are already stored.

    python backfill_reclassify.py --dry-run
    python backfill_reclassify.py

RUN ORDER HAZARD: this script must run BEFORE any hand-authored, per-company
sector/sub_sector repair pass -- master's apply_taxonomy_repairs.py, which
hardcodes specific companies' sector and sub_sector, is exactly such a pass.
reclassify() recomputes sector purely from official_sector/official_industry
and clears any sub_sector that no longer coheres with the recomputed sector,
with no awareness of a hand-authored override that intentionally disagrees
with the derived mapping -- running this script AFTER a hand-authored repair
pass can silently revert it. --dry-run's report (including sub_sector_cleared
below) is always safe to run first to see what would change, even on a
database that already carries hand-authored repairs.
"""
import argparse
from collections import Counter

from sqlalchemy.orm import Session

from app.companies.sub_sectors import is_valid_sub_sector
from app.companies.universe.sector_map import map_sector
from app.db import SessionLocal
from app.models import Company


def reclassify(session: Session, dry_run: bool = False) -> dict:
    """Recompute sector for every company that has an official classification.

    A company with no official_sector is left alone -- its sector came from
    somewhere else (the curated global seed, or the legacy keyword map) and
    this function has nothing better to offer.

    dry_run's honesty does NOT rest on a session.rollback() undoing a write:
    `company.sector` is only ever assigned in the `not dry_run` branch below,
    so in dry-run mode nothing is ever mutated on the ORM objects in the
    first place. That means there is nothing pending for autoflush to leak
    into the transaction, and nothing that a rollback would need to catch --
    dry-run mode never even calls session.commit()/rollback(), so it also
    can't discard unrelated pending changes a caller happens to have on the
    session already. See tests/test_backfill_reclassify.py::
    test_dry_run_leaves_no_pending_or_committed_state, which forces an
    autoflush-triggering query immediately after a dry run and then checks
    the row from a second, independent session to prove nothing escaped.
    """
    changed = unchanged = sub_sector_cleared = 0
    transitions: Counter = Counter()

    companies = session.query(Company).filter(Company.official_sector.isnot(None)).all()
    for company in companies:
        derived = map_sector(company.official_sector, company.official_industry)
        if derived == company.sector:
            unchanged += 1
            continue
        transitions[f"{company.sector} -> {derived}"] += 1
        changed += 1

        # Coherence guard, same rule as app.companies.universe.loader: a
        # sub_sector belonging to the OLD sector must not survive a sector
        # change. Checked against `derived` (the sector about to be written),
        # via SUB_SECTOR_TAXONOMY membership (is_valid_sub_sector) -- never
        # hardcoded. This is the standalone equivalent of the same incoherence
        # app.companies.integrity.check_sub_sectors (master) flags; without
        # it, this script can manufacture it at scale across every company it
        # reclassifies.
        if company.sub_sector is not None and not is_valid_sub_sector(derived, company.sub_sector):
            sub_sector_cleared += 1
            if not dry_run:
                company.sub_sector = None

        if not dry_run:
            company.sector = derived

    if not dry_run:
        session.commit()

    return {
        "changed": changed, "unchanged": unchanged,
        "sub_sector_cleared": sub_sector_cleared,
        "by_transition": dict(transitions),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run", action="store_true",
        help=(
            "print every sector transition AND every sub_sector clear that "
            "WOULD happen, and write nothing"
        ),
    )
    args = parser.parse_args()

    session = SessionLocal()
    try:
        result = reclassify(session, dry_run=args.dry_run)
        print("DRY RUN -- reporting every would-be change, writing nothing"
              if args.dry_run else "APPLIED")
        print(f"  changed          : {result['changed']}")
        print(f"  unchanged        : {result['unchanged']}")
        print(f"  sub_sector_cleared: {result['sub_sector_cleared']}")
        for transition, count in sorted(result["by_transition"].items(), key=lambda kv: -kv[1]):
            print(f"    {transition:44s} {count}")
        print("DRY RUN complete -- nothing was written" if args.dry_run else "done")
    finally:
        session.close()


if __name__ == "__main__":
    main()
