"""Deterministic demo data for locally viewing/screenshotting the CAR
review screen (docs/superpowers/plans/2026-07-23-measurement-first-
impact-phase8-car-review.md) -- inserts Alert/Article/Company/
AlertCompany/MarketMove/CarOutcome rows directly (no LLM calls, no live
market data -- CAR data only exists once real trading days have passed,
so there's no way to produce it live in a fresh dev DB). Covers all
three outcome labels (HELD, REVERSED, FLAT) and enough total rows to
unlock the aggregate summary (config.CAR_SUMMARY_SAMPLE_THRESHOLD).

Safe to re-run: clears its own previously-seeded rows (identified by a
fixed marker prefix on Article.url) before re-inserting.

Usage (from the backend/ directory, so `app` is importable):
    .venv/Scripts/python seed_car_review_demo.py
"""
import sys
from datetime import timedelta

from app.config import settings
from app.db import SessionLocal, init_db
from app.models import Alert, AlertCompany, Article, CarOutcome, Company, MarketMove, utcnow

URL_MARKER = "https://demo.car-review.local/"

# (ticker, name, category, benchmark, day0_excess, car_pct, headline)
DEMO_ROWS = [
    ("RELIANCE.NS", "Reliance Industries", "oil_gas", "^CNXENERGY", -4.2, -3.6, "Crude oil supply shock hits refiners"),
    ("TCS.NS", "Tata Consultancy Services", "it", "^CNXIT", 2.8, 3.4, "Large IT deal win announced"),
    ("HDFCBANK.NS", "HDFC Bank", "banking", "^NSEBANK", -3.1, 2.9, "Regulatory concern flagged, later cleared"),
    ("SUNPHARMA.NS", "Sun Pharmaceutical", "pharma", "^CNXPHARMA", 3.5, 0.2, "Drug approval news, muted follow-through"),
    ("TATASTEEL.NS", "Tata Steel", "metals", "^CNXMETAL", -2.6, -2.2, "Tariff announcement hits metal stocks"),
    ("MARUTI.NS", "Maruti Suzuki", "auto", "^CNXAUTO", 4.0, 3.1, "Strong monthly sales numbers"),
]


def main() -> None:
    if not settings.database_url.startswith("sqlite://"):
        print(
            f"ERROR: seed_car_review_demo.py refuses to run against a non-SQLite database.\n"
            f"DATABASE_URL is: {settings.database_url}\n"
            f"This safety guard exists because running this script against production\n"
            f"would inject demo CAR outcomes alongside real ones.\n"
            f"Only run this script against local SQLite dev databases.",
            file=sys.stderr,
        )
        sys.exit(1)

    init_db()
    session = SessionLocal()
    try:
        existing = session.query(Article).filter(Article.url.like(f"{URL_MARKER}%")).all()
        for article in existing:
            for alert in session.query(Alert).filter_by(article_id=article.id).all():
                for ac in session.query(AlertCompany).filter_by(alert_id=alert.id).all():
                    session.query(CarOutcome).filter_by(alert_company_id=ac.id).delete()
                session.query(MarketMove).filter_by(alert_id=alert.id).delete()
                session.query(AlertCompany).filter_by(alert_id=alert.id).delete()
                session.delete(alert)
            session.delete(article)
        session.commit()

        now = utcnow()
        for i, row in enumerate(DEMO_ROWS):
            ticker, name, category, benchmark, day0_excess, car_pct, headline = row

            company = session.query(Company).filter_by(ticker=ticker).one_or_none()
            if company is None:
                company = Company(ticker=ticker, name=name, sector=category, index_tier="NIFTY50", market_cap=50000.0)
                session.add(company)
                session.commit()

            article = Article(
                source="demo", url=f"{URL_MARKER}{i}", title=headline, content=headline,
                published_at=now - timedelta(days=10 + i),
            )
            session.add(article)
            session.commit()

            alert = Alert(
                article_id=article.id, category=category, created_at=now - timedelta(days=10 + i),
                summary_short=headline,
            )
            session.add(alert)
            session.flush()

            alert_company = AlertCompany(
                alert_id=alert.id, company_id=company.id, direction="bullish" if day0_excess >= 0 else "bearish",
                magnitude_low=1.0, magnitude_high=2.0, rationale=headline, basis="direct_mention",
            )
            session.add(alert_company)
            session.flush()

            session.add(MarketMove(
                alert_id=alert.id, company_id=company.id, benchmark_ticker=benchmark,
                raw_move_pct=day0_excess, sector_move_pct=0.0, excess_move_pct=day0_excess,
                volume=100.0, avg_volume_20d=100.0, volume_multiple=1.0,
                measurement_status="ok", measured_at=now - timedelta(days=10 + i),
            ))

            session.add(CarOutcome(
                alert_company_id=alert_company.id, company_id=company.id, category=category,
                day0_excess_move_pct=day0_excess, car_pct=car_pct,
            ))
            session.commit()

        print(f"Seeded {len(DEMO_ROWS)} demo CAR outcomes.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
