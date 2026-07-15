from app.companies.kite_instruments import fetch_kite_instruments, match_instrument_tokens
from app.db import SessionLocal, init_db

if __name__ == "__main__":
    init_db()
    session = SessionLocal()
    try:
        rows = fetch_kite_instruments()
        updated = match_instrument_tokens(session, rows)
        print(f"Matched instrument_token for {updated} companies out of {len(rows)} Kite equity rows")
    finally:
        session.close()
