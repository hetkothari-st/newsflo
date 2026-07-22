"""One-time enrichment: generate a plain-language business description
plus supply-chain suppliers/customers for every existing Company missing
one (docs/NEWS_IMPACT_APP_SPEC.md §3.1). Reused forever after --
Company.business_desc/supply_chain_*_json are read at API-serialization
time, never written by the per-article analysis pipeline.

Safe to re-run: only targets companies where business_desc IS NULL,
commits per-batch so an interrupted run keeps whatever progress it made.

Usage (from the backend/ directory, so `app` is importable):
    .venv/Scripts/python backfill_business_profiles.py
"""
import json

from app.analysis.claude_client import build_client
from app.companies.business_profile import generate_business_profiles_batch
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
        pending = session.query(Company).filter_by(business_desc=None).all()
        print(f"{len(pending)} companies to enrich")
        for i in range(0, len(pending), BATCH_SIZE):
            batch = pending[i : i + BATCH_SIZE]
            profiles = generate_business_profiles_batch(client, [(c.ticker, c.name, c.sector) for c in batch])
            for company in batch:
                profile = profiles.get(company.ticker)
                if profile:
                    company.business_desc = profile["business_desc"]
                    company.supply_chain_suppliers_json = json.dumps(profile["suppliers"])
                    company.supply_chain_customers_json = json.dumps(profile["customers"])
                    total += 1
            session.commit()
            print(f"  batch {i // BATCH_SIZE + 1} done ({len(batch)} companies)")
    finally:
        session.close()

    print(f"Business profile backfill complete: {total} companies enriched.")


if __name__ == "__main__":
    main()
