"""Export the real article->company links already in the DB as a matcher
regression corpus.

The 881 alert_companies rows are genuine production resolutions. Replaying
company NAMES through the new matcher and asserting it never returns a
DIFFERENT company is a far stronger check than any synthetic fixture.

Run:  python export_match_corpus.py
Writes tests/fixtures/matching/regression_corpus.json
"""
import json
from pathlib import Path

from app.db import SessionLocal
from app.models import AlertCompany, Company

OUTPUT = Path("tests/fixtures/matching/regression_corpus.json")


def main() -> None:
    session = SessionLocal()
    try:
        linked_ids = {
            company_id for company_id, in
            session.query(AlertCompany.company_id).distinct().all()
        }
        companies = (
            session.query(Company).filter(Company.id.in_(linked_ids)).all()
            if linked_ids else []
        )
        payload = {
            "companies": [
                {"ticker": c.ticker, "name": c.name, "sector": c.sector}
                for c in companies
            ],
            "cases": [
                {"mention": c.name, "expect": c.ticker} for c in companies
            ],
        }
    finally:
        session.close()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {len(payload['cases'])} cases to {OUTPUT}")


if __name__ == "__main__":
    main()
