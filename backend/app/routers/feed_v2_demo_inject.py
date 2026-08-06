"""Preview-only demo stories for the feed, injected IN MEMORY.

The newsflo-v2 preview service shares the production database, so demo
stories must never be written as rows -- they would surface in the real
app (seed_feed_v2_demo.py refuses Postgres for exactly that reason).
Instead, when ALLOW_DEMO_FEED=true (set only on the preview service),
the feed-v2 endpoints append these payloads built from the seed
script's own data definitions. Nothing touches the database; the main
service never sets the flag and (on master) never carries this module.

Demo alerts use NEGATIVE ids (-1..-5) so they can never collide with a
real Alert row.
"""
from datetime import timedelta

from sqlalchemy.orm import Session

import seed_feed_v2_demo as seed
from app.companies.branding import logo_url
from app.market.cap_tier import cap_tier_map
from app.models import Company, utcnow

_VERDICTS = {
    "RELIANCE.NS": "SECTOR_WIDE",
    "TCS.NS": "SECTOR_WIDE",
    "SOMETEXTILE.NS": "COMPANY_SPECIFIC",
    "ONGC.NS": "SECTOR_WIDE",
    "IDEA.NS": "UNCONFIRMED",
}

# Static intensity per demo peak -- honest-looking, clearly derived from
# the excess magnitudes in seed.DEMO_ROWS.
_INTENSITY = {
    "RELIANCE.NS": (78, "High"),
    "TCS.NS": (22, "Low"),
    "SOMETEXTILE.NS": (64, "Moderate"),
    "ONGC.NS": (18, "Low"),
    "IDEA.NS": (55, "Moderate"),
}


def _company(db: Session, ticker: str) -> Company | None:
    return db.query(Company).filter_by(ticker=ticker).first()


def _logo(db: Session, ticker: str) -> str | None:
    company = _company(db, ticker)
    return logo_url(company) if company else None


def _intensity(ticker: str) -> dict:
    score, band = _INTENSITY.get(ticker, (40, "Moderate"))
    return {"score": score, "band": band, "components": []}


def _row_intensity(excess: float | None) -> dict:
    if excess is None:
        return {"score": 20, "band": "Low", "components": []}
    magnitude = abs(excess)
    score = min(95, int(20 + magnitude * 16))
    band = "High" if score >= 70 else "Moderate" if score >= 40 else "Low"
    return {"score": score, "band": band, "components": []}


def _layer_row(db: Session, ticker: str, name: str, sector: str, direction: str,
               excess: float | None, cap_tiers: dict[str, str], *,
               delivery_pct: float | None = 60.0, liquidity: str | None = "HIGH",
               exposure_only: bool = False, why: str | None = None) -> dict:
    return {
        "ticker": ticker,
        "name": name,
        "sector": sector,
        "cap_tier": cap_tiers.get(ticker),
        "liquidity_tier": liquidity,
        "delivery_pct": delivery_pct,
        "business_desc": seed.BUSINESS_DESCRIPTIONS.get(ticker),
        "business_desc_source_url": None,
        "fundamentals": None,
        "volatility_range": None,
        "direction": direction,
        "excess_move_pct": excess,
        "intensity": None if exposure_only else _row_intensity(excess),
        "is_exposure_only": exposure_only,
        "in_my_holdings": False,
        "why": why,
        "logo_url": _logo(db, ticker),
    }


def _list_row(db: Session, index: int, row: tuple, cap_tiers: dict[str, str]) -> dict:
    (ticker, name, sector, benchmark, raw, sector_move, excess,
     volume_mult, headline, summary_short, why, direction) = row
    now = utcnow()
    created = now - timedelta(minutes=5 * index)
    return {
        "id": -(index + 1),
        "category": sector,
        "category_label": None,
        "created_at": created.isoformat(),
        "summary_short": summary_short,
        "summary_long": why,
        "article": {
            "id": -(index + 1),
            "image_url": f"https://picsum.photos/seed/newsflo-demo-{index}/800/400",
            "title": f"{headline} (demo)",
            "url": f"{seed.URL_MARKER}{index}",
            "source": "demo",
            "published_at": (created - timedelta(minutes=2)).isoformat(),
        },
        "in_my_holdings": False,
        "excess_move_pct": excess,
        "direction": direction,
        "raw_move_pct": raw,
        "sector_move_pct": sector_move,
        "volume_multiple": volume_mult,
        "benchmark_ticker": benchmark,
        "is_fallback_benchmark": False,
        "peak_ticker": ticker,
        "peak_company_name": name,
        "peak_cap_tier": cap_tiers.get(ticker),
        "verdict": _VERDICTS.get(ticker, "COMPANY_SPECIFIC"),
        "intensity": _intensity(ticker),
        "breadth_score": 45,
        "cap_tiers": sorted({tier for tier in [cap_tiers.get(ticker)] if tier}),
    }


def demo_feed_rows(db: Session) -> list[dict]:
    """The five demo stories as feed-v2 list rows (today's edition)."""
    cap_tiers = cap_tier_map(db)
    return [_list_row(db, i, row, cap_tiers) for i, row in enumerate(seed.DEMO_ROWS)]


def demo_alert_detail(db: Session, alert_id: int) -> dict | None:
    """Detail payload (layers + timeline) for a demo alert id, else None."""
    index = -alert_id - 1
    if index < 0 or index >= len(seed.DEMO_ROWS):
        return None
    cap_tiers = cap_tier_map(db)
    row = seed.DEMO_ROWS[index]
    (ticker, name, sector, _bench, _raw, _sector_move, excess,
     _vol, _headline, _summary, why, direction) = row
    base = _list_row(db, index, row, cap_tiers)

    if ticker == "RELIANCE.NS":
        # The full crude-oil ripple, grouped from the seed companions.
        winners = [c for c in seed.RIPPLE_COMPANIONS if c[4] == "bullish"]
        losers = [c for c in seed.RIPPLE_COMPANIONS if c[4] == "bearish" and c[6]]
        exposure = [c for c in seed.RIPPLE_COMPANIONS if not c[6]]
        direct = _layer_row(db, ticker, name, sector, direction, excess, cap_tiers,
                            delivery_pct=61.0, why=why)
        layers = [
            {
                "title": "Losers — directly affected",
                "relationship": "DIRECT",
                "icon": "lose",
                "note": "Higher crude squeezes refining margins.",
                "rows": [direct] + [
                    _layer_row(db, c[0], c[1], c[2], c[4], c[5], cap_tiers,
                               delivery_pct=c[8], liquidity="HIGH")
                    for c in losers
                ],
            },
            {
                "title": "Winners — beneficiaries",
                "relationship": "BENEFICIARY",
                "icon": "win",
                "note": "Cheaper feedstock or pricing tailwinds work in their favour.",
                "rows": [
                    _layer_row(db, c[0], c[1], c[2], c[4], c[5], cap_tiers,
                               delivery_pct=c[8],
                               liquidity="LOW" if c[0] == "CHENNPETRO.NS" else "HIGH")
                    for c in winners
                ],
            },
        ]
        if exposure:
            layers.append({
                "title": "Exposure — no measured move yet",
                "relationship": "SECTOR_WIDE",
                "icon": "side",
                "note": "Linked to the story but without a measurable reaction so far.",
                "rows": [
                    _layer_row(db, c[0], c[1], c[2], c[4], None, cap_tiers,
                               delivery_pct=None, liquidity=None, exposure_only=True)
                    for c in exposure
                ],
            })
        timeline = [
            {"horizon": horizon, "description": description}
            for horizon, description in seed.TIMELINE_ENTRIES
        ]
    else:
        layers = [
            {
                "title": "Directly affected",
                "relationship": "DIRECT",
                "icon": "lose" if direction == "bearish" else "win",
                "note": None,
                "rows": [_layer_row(db, ticker, name, sector, direction, excess,
                                    cap_tiers, why=why)],
            }
        ]
        timeline = []

    return {**base, "layers": layers, "timeline": timeline}


def demo_stock_context(db: Session, alert_id: int, ticker: str) -> dict | None:
    """Story context for the stock deep dive when opened from a demo
    story: the company's own demo row (excess/why/section) plus the other
    demo companies as peers. None when the id/ticker isn't demo."""
    detail = demo_alert_detail(db, alert_id)
    if detail is None:
        return None
    own = None
    section_title = None
    peers: list[dict] = []
    for layer in detail["layers"]:
        for row in layer["rows"]:
            if row["ticker"] == ticker:
                own = row
                section_title = layer["title"]
            else:
                peers.append(row)
    if own is None:
        return None
    return {
        "is_exposure_only": own["is_exposure_only"],
        "excess_move_pct": own["excess_move_pct"],
        "raw_move_pct": detail["raw_move_pct"] if ticker == detail["peak_ticker"] else own["excess_move_pct"],
        "sector_move_pct": detail["sector_move_pct"],
        "volume_multiple": detail["volume_multiple"] if ticker == detail["peak_ticker"] else None,
        "liquidity_tier": own["liquidity_tier"],
        "delivery_pct": own["delivery_pct"],
        "intensity": own["intensity"],
        "why": own["why"],
        "section_title": section_title,
        "peers": peers[:6],
    }
