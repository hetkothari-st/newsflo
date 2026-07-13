from app.companies.nifty_loader import load_nifty_indices
from app.db import SessionLocal, init_db

if __name__ == "__main__":
    init_db()
    session = SessionLocal()
    try:
        result = load_nifty_indices(session)
        print(f"Upserted {result['companies']} companies, {result['memberships']} index memberships")
    finally:
        session.close()
