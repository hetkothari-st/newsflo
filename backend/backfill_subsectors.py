"""One-time enrichment: classify every existing Company into a sub-sector
within its already-assigned sector, using SUB_SECTOR_TAXONOMY as the closed
vocabulary (see app/companies/sub_sectors.py). Reused forever after --
Company.sub_sector is read at API-serialization time, never written by the
per-article analysis pipeline.

Safe to re-run: only targets companies where sub_sector IS NULL, commits
per-batch so an interrupted run keeps whatever progress it made. Companies
seeded later (nifty_loader.py / global_seed.py) start NULL and are picked up
next time this is (re-)run -- no pipeline change needed.

Usage (from the backend/ directory, so `app` is importable):
    .venv/Scripts/python backfill_subsectors.py
"""
from app.analysis.claude_client import build_client
from app.companies.sub_sectors import SUB_SECTOR_TAXONOMY, classify_batch
from app.config import settings
from app.db import SessionLocal, init_db
from app.models import Company

BATCH_SIZE = 25  # companies per LLM call -- keeps prompt/response small and each batch independently retriable


def main() -> None:
    init_db()
    session = SessionLocal()
    client = build_client(settings.groq_api_keys, settings.anthropic_api_key or None)
    total = 0
    try:
        for sector in SUB_SECTOR_TAXONOMY:
            pending = session.query(Company).filter_by(sector=sector, sub_sector=None).all()
            if not pending:
                continue
            print(f"{sector}: {len(pending)} companies to classify")
            for i in range(0, len(pending), BATCH_SIZE):
                batch = pending[i : i + BATCH_SIZE]
                assignments = classify_batch(client, sector, [(c.ticker, c.name) for c in batch])
                for company in batch:
                    sub_sector = assignments.get(company.ticker)
                    if sub_sector:
                        company.sub_sector = sub_sector
                        total += 1
                session.commit()
                print(f"  batch {i // BATCH_SIZE + 1} done ({len(batch)} companies)")
    finally:
        session.close()

    print(f"Sub-sector backfill complete: {total} companies classified.")


if __name__ == "__main__":
    main()
