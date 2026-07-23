"""Deterministic demo data for locally viewing/screenshotting the Level 0/1
feed-v2 UI (docs/superpowers/plans/2026-07-22-measurement-first-impact-
phase4-feed-summary-ui.md) -- inserts a handful of realistic Alert/Company/
MarketMove rows directly (no LLM calls, no live market data) covering a
spread of verdicts, intensity bands, and a held company, so the feed has
something meaningful to render without depending on the live scheduler.

Safe to re-run: clears its own previously-seeded rows (identified by a
fixed marker prefix on Article.url) before re-inserting.

Usage (from the backend/ directory, so `app` is importable):
    .venv/Scripts/python seed_feed_v2_demo.py
"""
from datetime import timedelta

from app.db import SessionLocal, init_db
from app.models import Alert, AlertCompany, Article, Company, MarketMove, utcnow

URL_MARKER = "https://demo.feed-v2.local/"

DEMO_ROWS = [
    # (ticker, name, sector, benchmark, raw, sector_move, excess, volume_mult, headline, summary_short, why, direction)
    (
        "RELIANCE.NS", "Reliance Industries", "oil_gas", "^CNXENERGY",
        -4.8, -0.6, -4.2, 3.1,
        "Crude oil supply shock hits refiners", "Oil supply shock lifts costs for refiners",
        "Higher crude prices squeeze refining margins for this company.", "bearish",
    ),
    (
        "TCS.NS", "Tata Consultancy Services", "it", "^CNXIT",
        1.2, 0.9, 0.3, 1.1,
        "IT services sector drifts with broader market", "IT stocks move with the wider market today",
        "This move tracks the sector, not company-specific news.", "bullish",
    ),
    (
        "SOMETEXTILE.NS", "Demo Textiles Ltd", "textiles", "^NSEI",
        2.5, 0.4, 2.1, 2.4,
        "Cotton export duty cut announced", "Export duty cut helps textile makers",
        "Lower export duty directly raises this company's overseas margins.", "bullish",
    ),
    (
        # Same sector as RELIANCE.NS but a much smaller excess move -- proves
        # the intensity peer group is genuinely cross-alert/sector-scoped
        # (see app.market.alert_measurement._sector_peer_moves): before the
        # fix both oil_gas rows would trivially score intensity.band "High"
        # since each was "the max of a group containing only itself".
        "ONGC.NS", "Oil and Natural Gas Corporation", "oil_gas", "^CNXENERGY",
        -0.5, -0.2, -0.3, 1.0,
        "Minor pullback in upstream oil stocks", "Small dip alongside broader energy sector",
        "This move is modest and largely tracks the sector, not a company-specific shock.", "bearish",
    ),
]


def main() -> None:
    init_db()
    session = SessionLocal()
    try:
        existing = session.query(Article).filter(Article.url.like(f"{URL_MARKER}%")).all()
        for article in existing:
            for alert in session.query(Alert).filter_by(article_id=article.id).all():
                session.query(MarketMove).filter_by(alert_id=alert.id).delete()
                session.query(AlertCompany).filter_by(alert_id=alert.id).delete()
                session.delete(alert)
            session.delete(article)
        session.commit()

        now = utcnow()
        for i, row in enumerate(DEMO_ROWS):
            ticker, name, sector, benchmark, raw, sector_move, excess, vol_mult, headline, summary_short, why, direction = row

            company = session.query(Company).filter_by(ticker=ticker).one_or_none()
            if company is None:
                company = Company(ticker=ticker, name=name, sector=sector, index_tier="NIFTY50", market_cap=50000.0)
                session.add(company)
                session.commit()

            article = Article(
                source="demo", url=f"{URL_MARKER}{i}", title=headline, content=headline,
                published_at=now - timedelta(minutes=5 * i),
            )
            session.add(article)
            session.commit()

            alert = Alert(
                article_id=article.id, category=sector if sector != "textiles" else "other",
                created_at=now - timedelta(minutes=5 * i), summary_short=summary_short,
                summary_long=f"{summary_short}. {why}",
            )
            session.add(alert)
            session.flush()

            alert_company = AlertCompany(
                alert_id=alert.id, company_id=company.id, direction=direction,
                magnitude_low=1.0, magnitude_high=2.0, rationale=why, basis="direct_mention",
                why=why,
            )
            session.add(alert_company)

            session.add(MarketMove(
                alert_id=alert.id, company_id=company.id, benchmark_ticker=benchmark,
                raw_move_pct=raw, sector_move_pct=sector_move, excess_move_pct=excess,
                volume=vol_mult * 100.0, avg_volume_20d=100.0, volume_multiple=vol_mult,
                measurement_status="ok", measured_at=now,
            ))
            session.commit()

        print(f"Seeded {len(DEMO_ROWS)} demo feed-v2 alerts.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
