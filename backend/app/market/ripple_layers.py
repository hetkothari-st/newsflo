"""Card-back ripple LAYERS (spec v2 §2 "Card back", §5, §7): every affected
company of an alert -- direct AND cascade, peak included -- grouped into
ordered layers by relationship type, each layer carrying a direction icon,
a one-line "why this layer" note, and its stock rows sorted by intensity
descending ("the ordering is itself the discovery signal", spec §7).

Direction is derived per-news from each AlertCompany's own analyzed
direction, never stored as a fixed per-stock attribute (spec §11). A
company with no real measured move renders as a flagged exposure row --
no number, no score, never fabricated.
"""
from sqlalchemy.orm import Session

from app.companies.branding import logo_url
from app.market.alert_measurement import _intensity_for_company_move
from app.market.breadth import compute_breadth_score
from app.market.cap_tier import compute_cap_tiers
from app.market.liquidity import compute_liquidity_tier
from app.models import Alert, Company, ImpactEdge, MarketMove
from app.reasoning.ripple_relationship import is_exposure_only, relation_to_ripple_relationship

# Layer-title label per relationship bucket (sentence case, jargon-free --
# spec §11). DIRECT is special-cased in _layer_title.
_RELATIONSHIP_LABELS = {
    "DIRECT": "directly affected",
    "SUPPLIER": "suppliers upstream",
    "CUSTOMER_INPUT_COST": "input-cost users",
    "BENEFICIARY": "demand beneficiaries",
    "COMPETITOR": "competitors",
    "SUBSTITUTE": "substitutes",
    "SECTOR_WIDE": "sector-wide spillover",
}

# Deterministic layer ordering: the direct layer always leads (it IS the
# story); spillover buckets follow in fixed relationship order so the same
# alert always renders the same way.
_LAYER_ORDER = ["DIRECT", "SUPPLIER", "CUSTOMER_INPUT_COST", "BENEFICIARY", "COMPETITOR", "SUBSTITUTE", "SECTOR_WIDE"]


def _layer_icon(rows: list[dict]) -> str:
    """win when every row is bullish, lose when every row is bearish,
    side for a mixed layer (spec §5 archetype B: "same layer, opposite
    directions")."""
    directions = {row["direction"] for row in rows}
    if directions == {"bullish"}:
        return "win"
    if directions == {"bearish"}:
        return "lose"
    return "side"


def _layer_title(relationship: str, icon: str) -> str:
    label = _RELATIONSHIP_LABELS.get(relationship, "related companies")
    if relationship == "DIRECT":
        return "Directly affected" if icon != "side" else "Direct — winners & losers"
    if icon == "win":
        return f"Winners — {label}"
    if icon == "lose":
        return f"Losers — {label}"
    return f"Mixed — {label}"


def _layer_note(edges: list[ImpactEdge], relationship: str) -> str | None:
    """One-line "why this layer": the first ImpactEdge note whose relation
    maps into this relationship bucket -- real analyzed text, or None
    (frontend hides the line) rather than boilerplate."""
    for edge in edges:
        if relation_to_ripple_relationship(edge.relation) == relationship and edge.note:
            return edge.note
    return None


def compute_ripple_layers(session: Session, alert: Alert, held_company_ids: set[int]) -> list[dict]:
    """Ordered layers for one alert's card back. Each layer:
    {title, relationship, icon ('win'|'lose'|'side'), note (str|None),
    rows: [...]} -- rows carry ticker, name, sector, cap_tier,
    liquidity_tier, delivery_pct, direction, excess_move_pct,
    intensity, is_exposure_only, in_my_holdings, why, business_desc,
    logo_url. Every affected company appears exactly once (peak included
    -- the card back is the complete who's-affected view, spec §2)."""
    moves_by_company_id = {
        m.company_id: m for m in session.query(MarketMove).filter_by(alert_id=alert.id).all()
    }
    ok_excess_values = [
        m.excess_move_pct for m in moves_by_company_id.values() if m.measurement_status == "ok"
    ]
    breadth_score = compute_breadth_score(ok_excess_values)

    cap_rows = (
        session.query(Company.ticker, Company.market_cap).filter(Company.market_cap.isnot(None)).all()
    )
    cap_tiers = compute_cap_tiers([(t, c) for t, c in cap_rows])

    edges = session.query(ImpactEdge).filter_by(alert_id=alert.id).all()
    relation_by_company_id: dict[int, str] = {}
    for edge in edges:
        for company_id in (edge.to_company_id, edge.from_company_id):
            if company_id is not None and company_id not in relation_by_company_id:
                relation_by_company_id[company_id] = edge.relation

    grouped: dict[str, list[dict]] = {}
    for alert_company in alert.companies:
        company = alert_company.company
        move = moves_by_company_id.get(alert_company.company_id)
        status = move.measurement_status if move else None
        exposure_only = is_exposure_only(status)

        if alert_company.impact_level == "direct":
            relationship = "DIRECT"
        else:
            relationship = relation_to_ripple_relationship(
                relation_by_company_id.get(alert_company.company_id, "")
            )

        row = {
            # For serve-time overlays keyed to the AlertCompany row (e.g.
            # translated `why`, routers/feed_v2.py) -- not shown in the UI.
            "alert_company_id": alert_company.id,
            "ticker": company.ticker,
            "name": company.name,
            "sector": company.sector,
            "cap_tier": cap_tiers.get(company.ticker),
            "liquidity_tier": compute_liquidity_tier(move.avg_traded_value if move else None),
            "delivery_pct": move.delivery_pct if move else None,
            "business_desc": company.business_desc,
            "direction": alert_company.direction,
            "excess_move_pct": None,
            "intensity": None,
            "is_exposure_only": exposure_only,
            "in_my_holdings": alert_company.company_id in held_company_ids,
            "why": alert_company.why,
            "logo_url": logo_url(company),
        }
        if not exposure_only and move is not None and move.excess_move_pct is not None:
            row["excess_move_pct"] = move.excess_move_pct
            row["intensity"] = _intensity_for_company_move(session, company, move, breadth_score)
        grouped.setdefault(relationship, []).append(row)

    layers = []
    for relationship in _LAYER_ORDER:
        rows = grouped.pop(relationship, None)
        if not rows:
            continue
        rows.sort(key=lambda r: r["intensity"]["score"] if r["intensity"] else -1, reverse=True)
        icon = _layer_icon(rows)
        layers.append({
            "title": _layer_title(relationship, icon),
            "relationship": relationship,
            "icon": icon,
            "note": _layer_note(edges, relationship),
            "rows": rows,
        })
    return layers
