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
import sys
from datetime import timedelta

from app.config import settings
from app.db import SessionLocal, init_db
from app.models import Alert, AlertCompany, Article, Company, ImpactEdge, MarketMove, TimelineEffect, utcnow

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
    (
        # UNCONFIRMED verdict path (spec v2 §4.3): rumor/denial alert --
        # Alert.is_unconfirmed is set to 1 for this row below.
        "IDEA.NS", "Vodafone Idea", "telecom", "^NSEI",
        2.3, 0.4, 1.9, 2.1,
        "Report claims promoter stake sale; company denies", "Unverified stake-sale report; treat with caution",
        "The move rests on an unconfirmed report the company has denied.", "bullish",
    ),
]

# Per-ticker signal extras for DEMO_ROWS' MarketMove (spec v2 §4.2 inputs):
# (delivery_pct, vol_normalized, materiality, avg_traded_value)
DEMO_ROW_SIGNALS = {
    "RELIANCE.NS": (61.0, 2.4, 0.004, 1_200_000_000.0),
    "TCS.NS": (72.0, 0.4, 0.001, 900_000_000.0),
    "SOMETEXTILE.NS": (44.0, 1.9, 0.03, 30_000_000.0),
    "ONGC.NS": (68.0, 0.3, 0.001, 700_000_000.0),
    "IDEA.NS": (44.0, 1.2, 0.008, 90_000_000.0),
}

# Ripple companions + timeline, attached to DEMO_ROWS[0] (RELIANCE.NS) only --
# one company per relationship-mapping family (see app.reasoning.
# ripple_relationship._RELATION_TO_RIPPLE_RELATIONSHIP), plus one with NO
# MarketMove row at all to demonstrate the exposure-only path.
RIPPLE_COMPANIONS = [
    # (ticker, name, sector, relation, direction, excess, has_market_move,
    #  market_cap, delivery_pct, avg_traded_value)
    ("BPCL.NS", "Bharat Petroleum Corporation", "oil_gas", "commodity", "bullish", 3.0, True,
     120000.0, 63.0, 900_000_000.0),
    ("IOC.NS", "Indian Oil Corporation", "oil_gas", "input_cost", "bearish", -1.5, True,
     180000.0, 55.0, 800_000_000.0),
    ("HPCL.NS", "Hindustan Petroleum Corporation", "oil_gas", "competitor", "bearish", -0.8, True,
     80000.0, 58.0, 600_000_000.0),
    ("GAIL.NS", "GAIL India", "oil_gas", "supplier", "bearish", None, False,
     90000.0, None, None),
    # MICRO cap (below config.MICRO_CAP_FLOOR) with low delivery + thin
    # trading -- exercises every small/micro risk cue at once (spec v2 §6):
    # liquidity LOW tag, <50% delivery warning, thin-trading note, and the
    # materiality-ranked discovery tab.
    ("CHENNPETRO.NS", "Chennai Petroleum Corporation", "oil_gas", "commodity", "bullish", 4.7, True,
     400.0, 38.0, 20_000_000.0),
    # Fill out the spec §5 commodity-archetype sections on the crude card:
    # a producer (upstream), a by-product (paints), a heavy user (airline).
    ("OILINDIA.NS", "Oil India", "oil_gas", "commodity", "bearish", -3.1, True,
     45000.0, 61.0, 300_000_000.0),
    ("ASIANPAINT.NS", "Asian Paints", "chemicals", "input_cost", "bullish", 1.2, True,
     280000.0, 66.0, 700_000_000.0),
    ("INDIGO.NS", "InterGlobe Aviation", "railways_transport", "input_cost", "bullish", 2.1, True,
     160000.0, 59.0, 500_000_000.0),
]

# Sub-sector per seeded ticker (app/companies/sub_sectors.py vocabulary) --
# drives the spec §5 commodity template's producer/refiner split.
SUB_SECTORS = {
    "RELIANCE.NS": "refining_marketing",
    "ONGC.NS": "upstream_exploration",
    "BPCL.NS": "refining_marketing",
    "IOC.NS": "refining_marketing",
    "HPCL.NS": "refining_marketing",
    "CHENNPETRO.NS": "refining_marketing",
    "GAIL.NS": "gas_distribution",
    "OILINDIA.NS": "upstream_exploration",
    "ASIANPAINT.NS": "paints",
    "INDIGO.NS": "aviation",
}

TIMELINE_ENTRIES = [
    ("TODAY", "Markets react immediately to the supply disruption."),
    ("WEEKS", "Refining margins stay pressured while crude prices remain elevated."),
    ("QUARTERS", "Refiners may pass costs to consumers if the disruption persists."),
]

# Plain-language "what they do" text for the Level 4 deep-dive's business
# section (docs/NEWS_IMPACT_APP_SPEC.md §3.1 Stock.business_desc) -- the real
# pipeline populates this via an LLM enrichment job (backend/
# backfill_business_profiles.py) that this demo-only seed script deliberately
# never calls (no LLM calls here, per the module docstring), so without this
# static map every demo company's deep-dive page would show the "not
# available" fallback instead of real content to screenshot-verify against.
BUSINESS_DESCRIPTIONS = {
    "RELIANCE.NS": "Refines crude oil and runs retail fuel, petrochemical, and telecom businesses.",
    "TCS.NS": "Provides IT consulting and outsourced software services to global clients.",
    "SOMETEXTILE.NS": "Manufactures and exports cotton textiles and apparel.",
    "ONGC.NS": "Explores and produces crude oil and natural gas.",
    "BPCL.NS": "Refines crude oil and distributes petroleum products through retail fuel outlets.",
    "IOC.NS": "India's largest oil refiner, also distributing fuel and petrochemicals.",
    "HPCL.NS": "Refines crude oil and markets petroleum products across India.",
    "GAIL.NS": "Transports and markets natural gas via pipeline infrastructure.",
    "IDEA.NS": "Operates a pan-India mobile telecom network for voice and data.",
    "CHENNPETRO.NS": "A standalone refiner turning crude into fuels; crude is its single biggest input cost.",
    "OILINDIA.NS": "Explores and produces crude oil and natural gas in India's northeast.",
    "ASIANPAINT.NS": "India's largest paints maker; crude-derived inputs are a major cost line.",
    "INDIGO.NS": "India's largest airline; jet fuel is its single biggest operating cost.",
}

# Alert.event_type per DEMO_ROWS ticker -- keys the spec §5 ripple template
# archetype (crude alert renders the curated producer/refiner/by-product/
# heavy-user sections).
EVENT_TYPES = {
    "RELIANCE.NS": "crude_oil",
    "TCS.NS": "earnings",
    "SOMETEXTILE.NS": "trade_policy",
    "ONGC.NS": "crude_oil",
    "IDEA.NS": "corporate_action",
}


def main() -> None:
    # SAFETY: Refuse to run against a production database. This script inserts
    # genuine Alert/Article rows that would leak into the production /api/alerts
    # feed if accidentally run against Postgres. Only allow this to run against
    # local SQLite dev databases (DATABASE_URL starts with "sqlite://").
    if not settings.database_url.startswith("sqlite://"):
        print(
            f"ERROR: seed_feed_v2_demo.py refuses to run against a non-SQLite database.\n"
            f"DATABASE_URL is: {settings.database_url}\n"
            f"This safety guard exists because running this script against production\n"
            f"would inject demo alerts into the real /api/alerts feed.\n"
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
                session.query(MarketMove).filter_by(alert_id=alert.id).delete()
                session.query(AlertCompany).filter_by(alert_id=alert.id).delete()
                session.query(ImpactEdge).filter_by(alert_id=alert.id).delete()
                session.query(TimelineEffect).filter_by(alert_id=alert.id).delete()
                session.delete(alert)
            session.delete(article)
        session.commit()

        now = utcnow()
        first_alert_id = None
        for i, row in enumerate(DEMO_ROWS):
            ticker, name, sector, benchmark, raw, sector_move, excess, vol_mult, headline, summary_short, why, direction = row

            company = session.query(Company).filter_by(ticker=ticker).one_or_none()
            if company is None:
                company = Company(
                    ticker=ticker, name=name, sector=sector, index_tier="NIFTY50", market_cap=50000.0,
                    business_desc=BUSINESS_DESCRIPTIONS.get(ticker),
                    sub_sector=SUB_SECTORS.get(ticker),
                )
                session.add(company)
                session.commit()
            else:
                # Backfill for a company row that pre-exists this script (or
                # was created by an earlier run before these fields existed)
                # -- re-running this script must be able to fix that, not
                # leave it stale. market_cap drives the cap-tier tag on
                # every stock row (spec v2 §4.5); sub_sector drives the
                # spec §5 template's producer/refiner split.
                if company.business_desc is None and ticker in BUSINESS_DESCRIPTIONS:
                    company.business_desc = BUSINESS_DESCRIPTIONS[ticker]
                if company.market_cap is None:
                    company.market_cap = 50000.0
                if ticker in SUB_SECTORS:
                    company.sub_sector = SUB_SECTORS[ticker]
                session.commit()

            article = Article(
                source="demo", url=f"{URL_MARKER}{i}", title=headline, content=headline,
                published_at=now - timedelta(minutes=5 * i),
                # Stable demo image (seeded picsum) so the card front's news
                # image renders locally -- production articles get a real
                # og:image via the ingestion scraper.
                image_url=f"https://picsum.photos/seed/newsflo-{i}/800/400",
            )
            session.add(article)
            session.commit()

            alert = Alert(
                article_id=article.id, category=sector if sector != "textiles" else "other",
                created_at=now - timedelta(minutes=5 * i), summary_short=summary_short,
                summary_long=f"{summary_short}. {why}",
                event_type=EVENT_TYPES.get(ticker),
                # Rumor/denial demo row -> UNCONFIRMED verdict (spec v2 §4.3).
                is_unconfirmed=1 if ticker == "IDEA.NS" else 0,
            )
            session.add(alert)
            session.flush()
            if i == 0:
                first_alert_id = alert.id

            alert_company = AlertCompany(
                alert_id=alert.id, company_id=company.id, direction=direction,
                magnitude_low=1.0, magnitude_high=2.0, rationale=why, basis="direct_mention",
                why=why,
            )
            session.add(alert_company)

            delivery_pct, vol_normalized, materiality, avg_traded_value = DEMO_ROW_SIGNALS.get(
                ticker, (None, None, None, None),
            )
            session.add(MarketMove(
                alert_id=alert.id, company_id=company.id, benchmark_ticker=benchmark,
                raw_move_pct=raw, sector_move_pct=sector_move, excess_move_pct=excess,
                volume=vol_mult * 100.0, avg_volume_20d=100.0, volume_multiple=vol_mult,
                delivery_pct=delivery_pct, vol_normalized=vol_normalized,
                materiality=materiality, avg_traded_value=avg_traded_value,
                measurement_status="ok", measured_at=now,
            ))
            session.commit()

        # Ripple companions + timeline, attached to DEMO_ROWS[0] (RELIANCE.NS) only.
        peak_company = session.query(Company).filter_by(ticker=DEMO_ROWS[0][0]).one()
        for ticker, name, sector, relation, direction, excess, has_market_move, market_cap, delivery_pct, avg_traded_value in RIPPLE_COMPANIONS:
            company = session.query(Company).filter_by(ticker=ticker).one_or_none()
            if company is None:
                company = Company(
                    ticker=ticker, name=name, sector=sector, index_tier="OTHER", market_cap=market_cap,
                    business_desc=BUSINESS_DESCRIPTIONS.get(ticker),
                    sub_sector=SUB_SECTORS.get(ticker),
                )
                session.add(company)
                session.commit()
            else:
                # Keep companion rows current on re-run (market_cap drives the
                # MICRO demo path; business_desc drives the (i) popup;
                # sub_sector drives the spec §5 template split).
                company.market_cap = market_cap
                if company.business_desc is None and ticker in BUSINESS_DESCRIPTIONS:
                    company.business_desc = BUSINESS_DESCRIPTIONS[ticker]
                if ticker in SUB_SECTORS:
                    company.sub_sector = SUB_SECTORS[ticker]
                session.commit()

            session.add(AlertCompany(
                alert_id=first_alert_id, company_id=company.id, direction=direction,
                magnitude_low=0.5, magnitude_high=1.5, rationale=f"Ripple effect via {relation}.",
                basis="direct_mention", impact_level="indirect_l1",
                parent_company_id=peak_company.id,
                why=f"Linked to the crude move as a {relation.replace('_', ' ')} of the refining chain."
                if has_market_move else None,
            ))

            if has_market_move:
                session.add(MarketMove(
                    alert_id=first_alert_id, company_id=company.id, benchmark_ticker="^CNXENERGY",
                    raw_move_pct=excess, sector_move_pct=0.0, excess_move_pct=excess,
                    volume=(410.0 if ticker == "CHENNPETRO.NS" else 100.0), avg_volume_20d=100.0,
                    volume_multiple=(4.1 if ticker == "CHENNPETRO.NS" else 1.0),
                    delivery_pct=delivery_pct,
                    vol_normalized=(3.1 if ticker == "CHENNPETRO.NS" else 0.8),
                    materiality=(0.09 if ticker == "CHENNPETRO.NS" else 0.002),
                    avg_traded_value=avg_traded_value,
                    measurement_status="ok", measured_at=now,
                ))
            else:
                session.add(MarketMove(
                    alert_id=first_alert_id, company_id=company.id, benchmark_ticker="^CNXENERGY",
                    measurement_status="no_data", measured_at=now,
                ))

            session.add(ImpactEdge(
                alert_id=first_alert_id, from_company_id=peak_company.id, from_node_kind="company",
                from_label=peak_company.ticker, to_company_id=company.id, to_node_kind="company",
                to_label=company.ticker, relation=relation, direction=direction,
                note=f"Demo ripple edge ({relation}).", source="llm_only",
            ))
            session.commit()

        for horizon, description in TIMELINE_ENTRIES:
            session.add(TimelineEffect(alert_id=first_alert_id, horizon=horizon, description=description))
        session.commit()

        print(f"Seeded {len(DEMO_ROWS)} demo feed-v2 alerts, {len(RIPPLE_COMPANIONS)} ripple companions, {len(TIMELINE_ENTRIES)} timeline entries.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
