"""One-time re-classification: re-tag every existing Company's top-level
sector using the expanded SECTORS taxonomy (see app/analysis/schemas.py).
Needed because the taxonomy grew 8 new sectors (railways_transport,
construction_realestate, defense, agriculture, consumer_durables,
media_entertainment, chemicals, textiles) that no existing company is
tagged into yet -- without this, sector-cascade reasoning
(app/analysis/cascade.py) can name real companies in these sectors but
app.companies.resolution will never find a matching Company row for them.

Safe to re-run: re-classifies every company (not just companies currently
in "other", since some may be mistagged into an existing sector too),
commits per-batch so an interrupted run keeps whatever progress it made. A
ticker the model omits from its response is left untouched and picked up
again next run (see app.companies.sector_classification.classify_sector_batch).

Usage (from the backend/ directory, so `app` is importable):
    .venv/Scripts/python backfill_sectors.py
"""
from app.analysis.claude_client import build_client
from app.companies.sector_classification import classify_sector_batch
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
        companies = session.query(Company).all()
        num_batches = (len(companies) + BATCH_SIZE - 1) // BATCH_SIZE
        for i in range(0, len(companies), BATCH_SIZE):
            batch = companies[i : i + BATCH_SIZE]
            assignments = classify_sector_batch(client, [(c.ticker, c.name) for c in batch])
            for company in batch:
                sector = assignments.get(company.ticker)
                if sector and sector != company.sector:
                    company.sector = sector
                    total += 1
            session.commit()
            print(f"batch {i // BATCH_SIZE + 1}/{num_batches} done ({len(batch)} companies)")
    finally:
        session.close()

    print(f"Sector backfill complete: {total} companies re-tagged.")


if __name__ == "__main__":
    main()
