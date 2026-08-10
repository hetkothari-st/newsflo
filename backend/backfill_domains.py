"""One-time enrichment: fetch each company's website domain from Yahoo
Finance profile data into Company.website_domain. The domain feeds the
frontend logo fallback chain (Brandfetch-by-domain, then the site's own
favicon) for the ~30% of names Brandfetch has no mark for -- mostly BSE
small/micro caps that today render as initials.

Safe to re-run: only targets companies where website_domain IS NULL,
commits per-batch so an interrupted run keeps its progress. Yahoo has no
website on file for some names -- those stay NULL and are retried on the
next run (cheap: one skipped .info call each).

Usage (from the backend/ directory, so `app` is importable):
    .venv/Scripts/python backfill_domains.py [--limit N] [--global-first]
"""
import argparse
import sys
import time
from urllib.parse import urlparse

import yfinance as yf

from app.db import SessionLocal, init_db
from app.models import Company

BATCH_COMMIT = 25
THROTTLE_SECONDS = 0.6  # stay far under Yahoo's informal rate ceiling


def domain_from_website(website: str | None) -> str | None:
    """'https://www.reliance.com/investors' -> 'reliance.com'. Bare host,
    no scheme/path, leading www. stripped -- the shape both Brandfetch's
    domain endpoint and favicon resolvers expect."""
    if not website:
        return None
    parsed = urlparse(website if "//" in website else f"https://{website}")
    host = (parsed.netloc or "").strip().lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def fetch_domain(ticker: str) -> str | None:
    try:
        info = yf.Ticker(ticker).info
    except Exception:
        return None
    return domain_from_website(info.get("website") if isinstance(info, dict) else None)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="max companies this run")
    parser.add_argument(
        "--global-first", action="store_true",
        help="process market=GLOBAL companies before Indian ones",
    )
    args = parser.parse_args()

    init_db()
    session = SessionLocal()
    query = session.query(Company).filter(Company.website_domain.is_(None))
    if args.global_first:
        query = query.order_by((Company.market != "GLOBAL").asc(), Company.ticker.asc())
    else:
        query = query.order_by(Company.ticker.asc())
    companies = query.all()
    if args.limit is not None:
        companies = companies[: args.limit]
    print(f"{len(companies)} companies without a website_domain", flush=True)

    filled = skipped = 0
    try:
        for index, company in enumerate(companies, start=1):
            domain = fetch_domain(company.ticker)
            if domain:
                company.website_domain = domain
                filled += 1
            else:
                skipped += 1
            if index % BATCH_COMMIT == 0:
                session.commit()
                print(f"  {index}/{len(companies)} (filled {filled}, no-site {skipped})", flush=True)
            time.sleep(THROTTLE_SECONDS)
        session.commit()
    finally:
        session.close()
    print(f"done: filled {filled}, no-site {skipped}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
