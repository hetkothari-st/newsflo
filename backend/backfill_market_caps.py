"""Backfill: fetch a live market cap for companies that have none (or for
the recent-alert working set with --recent) -- the input to the cap-tier
ranking behind every LARGE/MID/SMALL/MICRO tag and the feed's cap filter
(spec v2 §4.5). Without caps, every tag renders "—" and the L/M/S/µ
filter matches nothing.

Not part of the test suite and not imported by the app. Safe to re-run --
commits per company.

Usage (from the backend/ directory, so `app` is importable):
    .venv/Scripts/python backfill_market_caps.py            # all companies missing a cap
    .venv/Scripts/python backfill_market_caps.py --recent   # only companies on recent alerts
"""
import argparse
import time

from app.companies.market_caps import alert_referenced_tickers, fetch_market_cap
from app.db import SessionLocal, init_db
from app.models import Company

DELAY_BETWEEN_FETCHES_SECONDS = 0.3


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recent", action="store_true", help="only companies attached to alerts in the last 7 days")
    args = parser.parse_args()

    init_db()
    session = SessionLocal()
    try:
        if args.recent:
            tickers = alert_referenced_tickers(session, days=7)
        else:
            tickers = [
                t for (t,) in session.query(Company.ticker).filter(Company.market_cap.is_(None)).all()
            ]
        print(f"{len(tickers)} companies to fetch.")

        updated = 0
        for i, ticker in enumerate(tickers, start=1):
            cap = fetch_market_cap(ticker)
            if cap is not None:
                company = session.query(Company).filter_by(ticker=ticker).one()
                company.market_cap = cap
                session.commit()
                updated += 1
            if i % 50 == 0:
                print(f"[{i}/{len(tickers)}] {updated} updated so far")
            time.sleep(DELAY_BETWEEN_FETCHES_SECONDS)

        print(f"Done. {updated}/{len(tickers)} companies now carry a market cap.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
