"""Re-derive Company.sector from the official classification already stored.

Needed because sector_map was keyed on BSE's Sector level while its table was
built from IndustryNew names, leaving 3,113 of 4,814 Indian companies as
"other" in production (2,971 of them despite having a valid classification).
Task 1 fixes the mapping; this applies it to rows already in the database.

No fetching: official_sector and official_industry are already stored.

    python backfill_reclassify.py --dry-run
    python backfill_reclassify.py
"""
import argparse
from collections import Counter

from sqlalchemy.orm import Session

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
    changed = unchanged = 0
    transitions: Counter = Counter()

    companies = session.query(Company).filter(Company.official_sector.isnot(None)).all()
    for company in companies:
        derived = map_sector(company.official_sector, company.official_industry)
        if derived == company.sector:
            unchanged += 1
            continue
        transitions[f"{company.sector} -> {derived}"] += 1
        changed += 1
        if not dry_run:
            company.sector = derived

    if not dry_run:
        session.commit()

    return {"changed": changed, "unchanged": unchanged, "by_transition": dict(transitions)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run", action="store_true",
        help="print every sector transition that WOULD happen, and write nothing",
    )
    args = parser.parse_args()

    session = SessionLocal()
    try:
        result = reclassify(session, dry_run=args.dry_run)
        print("DRY RUN -- reporting every would-be change, writing nothing"
              if args.dry_run else "APPLIED")
        print(f"  changed  : {result['changed']}")
        print(f"  unchanged: {result['unchanged']}")
        for transition, count in sorted(result["by_transition"].items(), key=lambda kv: -kv[1]):
            print(f"    {transition:44s} {count}")
        print("DRY RUN complete -- nothing was written" if args.dry_run else "done")
    finally:
        session.close()


if __name__ == "__main__":
    main()
