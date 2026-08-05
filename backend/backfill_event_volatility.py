"""One-time subsystem-D bootstrap + rerunnable rebuild.

    python backfill_event_volatility.py

1. Copies alerts.category into market_moves.category where NULL (historical
   rows predate the column; a recategorized alert's backfilled value is
   today's category -- accepted, spec §3.2).
2. Rebuilds event_volatility_ranges from all usable measurements.

Idempotent; safe to rerun. The nightly scheduler job does step 2 forever
after; this script exists for the initial run and for step 1.
"""
from datetime import date

from sqlalchemy import text

from app.db import SessionLocal, init_db
from app.market.event_volatility import rebuild


def main() -> None:
    init_db()
    session = SessionLocal()
    try:
        stamped = session.execute(text(
            "UPDATE market_moves SET category = ("
            "  SELECT alerts.category FROM alerts"
            "  WHERE alerts.id = market_moves.alert_id"
            ") WHERE category IS NULL AND alert_id IS NOT NULL"
        )).rowcount
        session.commit()
        print(f"backfilled category on {stamped} market_moves rows")

        result = rebuild(session, date.today())
        print(f"rebuild: facts={result['facts']} "
              f"deleted={result['deleted']} inserted={result['inserted']}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
