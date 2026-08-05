"""Prints the taxonomy rows a human should eyeball, highest-leverage first.

NIFTY50 rows matter most: app.companies.resolution._TIER_RANK ranks NIFTY50
first, so a mis-tagged NIFTY50 company is the one the sector fan-out reaches
for before anything else. That is exactly how ETERNAL.NS (food delivery,
tagged fmcg/personal_care) ended up on a crude-oil story.

Read-only. Prints; never writes.
"""
from app.companies.integrity import check_sub_sectors
from app.db import SessionLocal
from app.models import Company


def main() -> None:
    session = SessionLocal()
    try:
        violations = check_sub_sectors(session)
        print(f"=== sub_sector violations ({len(violations)}) ===")
        for v in violations:
            suggestion = f" -> should be sector={v.correct_sector!r}" if v.correct_sector else " -> unknown sub_sector"
            print(f"  {v.ticker:18} {v.name[:34]:36} {v.sector}/{v.sub_sector}{suggestion}")

        print("\n=== NIFTY50 rows (review these by hand) ===")
        rows = (
            session.query(Company)
            .filter_by(index_tier="NIFTY50")
            .order_by(Company.sector.asc(), Company.ticker.asc())
            .all()
        )
        for c in rows:
            print(f"  {c.ticker:18} {c.name[:34]:36} {c.sector}/{c.sub_sector}")
        print(f"\n{len(rows)} NIFTY50 rows.")

        missing = session.query(Company).filter(Company.sub_sector.is_(None)).count()
        other = session.query(Company).filter_by(sector="other").count()
        print(f"\nunclassified sub_sector: {missing}    sector='other': {other}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
