"""Full-universe ingest runbook (spec §4).

    python ingest_universe.py            # fetch a fresh snapshot, then load
    python ingest_universe.py --no-fetch # load the latest snapshot on disk

The BSE detail pass is ~5,000 throttled requests (30-40 minutes) and is
resumable: rerunning after an interruption skips whatever is already on
disk. The masters are 2 requests and are cheap to refetch daily.
"""
import argparse
from datetime import date

from sqlalchemy.orm import Session

from app.companies.matching import aliases
from app.companies.universe import fetchers, loader, normalize, snapshot
from app.db import SessionLocal


def run_ingest(root: str, day: date, session: Session, fetch: bool = True, opener=None) -> dict:
    if fetch:
        fetchers.fetch_nse_equity_list(root, day, opener=opener)
        fetchers.fetch_bse_scrip_list(root, day, opener=opener)

    nse_path = snapshot.master_path(root, day, "nse_equity_l.csv")
    bse_path = snapshot.master_path(root, day, "bse_scrips.json")
    if not nse_path.exists() or not bse_path.exists():
        raise FileNotFoundError(f"snapshot for {day.isoformat()} is incomplete under {root}")

    nse_rows = normalize.parse_nse_rows(nse_path.read_text(encoding="utf-8"))
    bse_rows = normalize.parse_bse_rows(bse_path.read_text(encoding="utf-8"))

    if fetch:
        scrip_codes = [(r.get("SCRIP_CD") or "").strip() for r in bse_rows]
        detail_result = fetchers.fetch_bse_details(
            root, day, [c for c in scrip_codes if c], opener=opener,
        )
        print(
            f"detail: fetched={detail_result['fetched']} "
            f"skipped={detail_result['skipped']} failed={len(detail_result['failed'])}"
        )
        if detail_result["failed"]:
            # Never silent: these companies land with NULL classification.
            print(f"  no classification for {len(detail_result['failed'])} scrips")

    detail_dir = snapshot.snapshot_dir(root, day) / snapshot.DETAIL_DIRNAME
    details = {
        p.stem: normalize.parse_bse_detail(p.read_text(encoding="utf-8"))
        for p in detail_dir.glob("*.json")
    } if detail_dir.is_dir() else {}

    records = normalize.build_records(nse_rows, bse_rows, details, day)
    result = loader.upsert_records(session, records)
    result["aliases"] = aliases.rebuild_aliases(session)
    result["records"] = len(records)
    if result["skipped"]:
        print(f"skipped {len(result['skipped'])} records: {result['skipped'][:10]}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-fetch", action="store_true", help="load the latest snapshot on disk")
    args = parser.parse_args()

    root = snapshot.DEFAULT_ROOT
    day = snapshot.latest_snapshot_day(root) if args.no_fetch else date.today()
    if day is None:
        raise SystemExit(f"no snapshot found under {root}")

    session = SessionLocal()
    try:
        print(run_ingest(root, day, session, fetch=not args.no_fetch))
    finally:
        session.close()


if __name__ == "__main__":
    main()
