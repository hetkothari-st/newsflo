"""Sourced-description backfill runbook.

    python backfill_descriptions.py             # fetch a fresh snapshot, then load
    python backfill_descriptions.py --no-fetch  # load the latest snapshot on disk
    python backfill_descriptions.py --dry-run   # fetch/parse, report, write nothing

The fetch is ~50 batched requests over ~900 candidate articles (a couple of
minutes) and is resumable: rerunning after an interruption skips whatever is
already on disk.

Safe to rerun. It never clears a description it cannot re-derive, and it
only ever writes text that is traceable to a named Wikipedia article.
"""
import argparse
import json
import sys
from datetime import date

from app.companies.descriptions import extract, fetchers, loader, snapshot
from app.db import SessionLocal
from app.models import Company


def load_pages(root: str, day: date) -> list[dict]:
    directory = snapshot.pages_dir(root, day)
    if not directory.is_dir():
        raise FileNotFoundError(f"no snapshot pages under {directory}")
    pages = []
    for path in sorted(directory.glob("*.json")):
        try:
            pages.append(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, OSError) as exc:
            # One unreadable file must not abort a 900-article load.
            print(f"  skipping unreadable {path.name}: {exc}", file=sys.stderr)
    return pages


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-fetch", action="store_true",
                        help="load the latest snapshot on disk instead of fetching")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be written, write nothing")
    parser.add_argument("--search", action="store_true",
                        help="also search Wikipedia by name for Indian companies that "
                             "still have no sourced description (~1 req/company, slow)")
    args = parser.parse_args()

    # Relative, like the universe snapshots: the process runs from /app in
    # production, where data/ is the mounted volume.
    root = snapshot.DEFAULT_ROOT
    day = date.today()

    if args.no_fetch:
        found = snapshot.latest_snapshot_day(root)
        if found is None:
            print(f"no snapshot under {root}; run without --no-fetch first", file=sys.stderr)
            return 1
        day = found
        print(f"using snapshot {day.isoformat()} under {root}")
    else:
        print("fetching candidate titles from the listing categories...")
        titles = fetchers.candidate_titles()
        print(f"  {len(titles)} candidate articles")
        already = len(snapshot.fetched_titles(root, day))
        if already:
            print(f"  {already} already on disk, resuming")

        def progress(done: int, total: int) -> None:
            print(f"  fetched {done}/{total}", flush=True)

        written = fetchers.fetch_pages(root, day, titles, progress=progress)
        print(f"  {written} pages written to {snapshot.pages_dir(root, day)}")

        if args.search:
            session = SessionLocal()
            try:
                # Only Indian companies: the proof is an NSE/BSE code, which a
                # global company does not have, so searching for one can only
                # ever produce a candidate that gets correctly discarded.
                pending = (
                    session.query(Company.ticker, Company.name)
                    .filter(Company.market == "INDIA")
                    .filter(Company.business_desc_source_url.is_(None))
                    .order_by(Company.ticker.asc())
                    .all()
                )
            finally:
                session.close()
            print(f"\nsearching Wikipedia for {len(pending)} companies without a "
                  f"sourced description (~{len(pending) // 60} min)...")

            def search_progress(done: int, total: int) -> None:
                print(f"  searched {done}/{total}", flush=True)

            found = fetchers.search_for_companies(
                root, day, [(t, n) for t, n in pending], progress=search_progress,
            )
            new_titles = [t for t in found if t not in set(titles)]
            print(f"  {len(found)} candidate titles, {len(new_titles)} not already fetched")
            extra = fetchers.fetch_pages(root, day, new_titles, progress=progress)
            print(f"  {extra} further pages written")

    pages = load_pages(root, day)
    print(f"parsed {len(pages)} snapshot pages")

    session = SessionLocal()
    try:
        if args.dry_run:
            resolved = 0
            samples = []
            for page in pages:
                wikitext = page.get("wikitext") or ""
                if extract.is_disambiguation(wikitext):
                    continue
                refs = extract.parse_refs(wikitext)
                company = loader.resolve_company(session, refs) if refs else None
                if company is None:
                    continue
                text = extract.summarize(page.get("extract") or "")
                if text is None:
                    continue
                resolved += 1
                if len(samples) < 10:
                    samples.append((company.ticker, page["title"], text[:110]))
            print(f"\nDRY RUN -- would write {resolved} descriptions")
            for ticker, title, text in samples:
                print(f"  {ticker:16s} <- {title}\n      {text}...")
            return 0

        stats = loader.apply_pages(session, pages, as_of=day)
        print("\nresults:")
        for key in ("pages", "written", "unchanged", "no_refs",
                    "unresolved", "no_text", "disambiguation"):
            print(f"  {key:16s} {stats[key]}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
