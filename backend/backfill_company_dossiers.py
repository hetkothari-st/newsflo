"""One-off: build sourced company profiles (recent-years history +
recent developments) for the Directory's dossier page -- Stage B of
app.companies.descriptions.

Rides Stage A's proof end to end: iterates the latest pages snapshot,
resolves each article exactly the way apply_pages does (parse_refs ->
resolve_company), and for every article that resolves, fetches the FULL
plaintext extract (one request per title, throttled) and applies the
deterministic history/developments extraction. No LLM, no invented text
-- every stored fragment traces to the article whose identifiers proved
the match, and the source URL travels with it.

Usage (from backend/, against whichever DATABASE_URL is active):
    python backfill_company_dossiers.py               # fetch + load
    python backfill_company_dossiers.py --no-fetch    # load what's on disk
    python backfill_company_dossiers.py --dry-run     # report, write nothing
    python backfill_company_dossiers.py --limit 50    # bound the fetch pass
"""
import argparse
import json
import sys
from datetime import date

from app.companies.descriptions import extract, fetchers, loader, snapshot
from app.db import SessionLocal, init_db
from app.models import Company


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=snapshot.DEFAULT_ROOT)
    parser.add_argument("--no-fetch", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    init_db()
    day = snapshot.latest_snapshot_day(args.root)
    if day is None:
        print("No descriptions snapshot on disk -- run backfill_descriptions.py first.")
        return 1

    session = SessionLocal()
    try:
        # Stage A resolution, replayed read-only: article title -> Company.
        resolved: dict[str, Company] = {}
        claimed: set[int] = set()
        for title in sorted(snapshot.fetched_titles(args.root, day)):
            try:
                page = json.loads(snapshot.page_path(args.root, day, title).read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            wikitext = page.get("wikitext") or ""
            if extract.is_disambiguation(wikitext):
                continue
            refs = extract.parse_refs(wikitext)
            if not refs:
                continue
            company = loader.resolve_company(session, refs)
            if company is None or company.id in claimed:
                continue
            claimed.add(company.id)
            resolved[title] = company
        print(f"Snapshot {day}: {len(resolved)} articles resolve to companies.")

        titles = sorted(resolved)
        if args.limit is not None:
            titles = titles[: args.limit]

        if not args.no_fetch:
            written = fetchers.fetch_full_extracts(
                args.root, day, titles,
                progress=lambda done, total: print(f"  full extracts {done}/{total}"),
            )
            print(f"Fetched {written} new full extracts.")

        counts = {"written": 0, "unchanged": 0, "empty": 0, "missing": 0}
        for title in titles:
            path = snapshot.full_path(args.root, day, title)
            if not path.is_file():
                counts["missing"] += 1
                continue
            try:
                full_page = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                counts["missing"] += 1
                continue
            if args.dry_run:
                section_map = extract.sections(full_page.get("extract") or "")
                has_history = extract.find_section(section_map, extract._HISTORY_HEADINGS) is not None
                counts["written" if has_history else "empty"] += 1
                continue
            outcome = loader.apply_profile(session, resolved[title], full_page, as_of=date.today())
            counts[outcome] += 1
        print(f"Profiles: {counts}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
