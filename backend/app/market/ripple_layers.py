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
import json

from sqlalchemy.orm import Session

from app.companies.branding import logo_url
from app.config import settings
from app.companies.descriptions import sourced_description
from app.companies.fundamentals import fundamentals_payload
from app.market.alert_measurement import _intensity_for_company_move
from app.market.breadth import compute_breadth_score
from app.market.cap_tier import cap_tier_map
from app.market.event_volatility import lookup_range, ranges_for_category
from app.market.measure import classify_reaction
from app.market.liquidity import compute_liquidity_tier
from app.market.ripple_templates import RowContext, assign_to_template, template_layers_for
from app.models import Alert, AlertRippleLayer, ImpactEdge, MarketMove
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

# Display names for the per-sector fallback split (see the DIRECT-bucket
# handling below) -- sentence case per spec §11.
_SECTOR_LABELS = {
    "oil_gas": "oil & gas", "banking": "banking & finance", "auto": "autos",
    "it": "IT services", "pharma": "pharma", "fmcg": "consumer staples",
    "metals": "metals", "telecom": "telecom", "infra": "infrastructure",
    "railways_transport": "transport & logistics",
    "construction_realestate": "real estate", "defense": "defense",
    "agriculture": "agriculture", "consumer_durables": "consumer durables",
    "media_entertainment": "media", "chemicals": "chemicals",
    "textiles": "textiles", "other": "other companies",
}


# Controlled taxonomy labels for strict-mode sections (spec §23): keyed by
# the causal parent node the gate validated. Fallback prettifies the node
# id -- deterministic either way, never LLM-authored.
_TAXONOMY_LABELS = {
    "crude_price": "crude-linked",
    "tyre_input_cost": "tyre input costs",
    "aviation_fuel_cost": "aviation fuel costs",
    "paint_input_cost": "paint input costs",
    "refining_margin": "refining & marketing",
    "repo_rate": "rate-sensitive",
    "inr_depreciation": "currency-exposed",
    "road_freight_fuel_cost": "freight fuel costs",
}

_EFFECT_PREFIX = {
    "positive": "Positive", "negative": "Negative",
    "mixed": "Mixed", "uncertain": "Uncertain", "neutral": "Neutral",
}
_EFFECT_ICON = {"positive": "win", "negative": "lose"}
_DIRECTION_TO_EFFECT = {"bullish": "positive", "bearish": "negative"}


def _strict_sections(alert: Alert, rows_flat: list[dict]) -> list[dict] | None:
    """Deterministic section assembly for gate-validated alerts (spec
    §23-§26): direction comes from economic_effect, membership from the
    publication gate's tier, labels from the controlled taxonomy. Returns
    None for legacy alerts (no gate output) so the 3-tier path renders
    them unchanged -- and the 3-tier code itself is never touched."""
    gated = [
        (alert_company, rows_flat[i])
        for i, alert_company in enumerate(alert.companies)
        if alert_company.display_tier in ("primary", "secondary")
    ]
    if not gated:
        return None

    def _effect(alert_company) -> str:
        return (alert_company.economic_effect
                or _DIRECTION_TO_EFFECT.get(alert_company.direction, "mixed"))

    def _row_sort_key(pair):
        alert_company, row = pair
        return (-(alert_company.materiality or 0.0), row["ticker"])

    sections: dict[tuple[str, str], list] = {}
    secondary: list = []
    for alert_company, row in gated:
        if alert_company.display_tier == "secondary":
            secondary.append((alert_company, row))
        else:
            key = (_effect(alert_company), alert_company.causal_parent_id or "event")
            sections.setdefault(key, []).append((alert_company, row))

    layers = []
    ordered = sorted(
        sections.items(),
        key=lambda kv: -max((ac.materiality or 0.0) for ac, _ in kv[1]),
    )
    for (effect, parent_id), members in ordered:
        members = sorted(members, key=_row_sort_key)
        label = _TAXONOMY_LABELS.get(parent_id, parent_id.replace("_", " "))
        top_mechanism = members[0][0].mechanism
        layers.append({
            "title": f"{_EFFECT_PREFIX.get(effect, 'Mixed')} — {label}",
            "relationship": f"MECH:{parent_id}",
            "icon": _EFFECT_ICON.get(effect, "side"),
            "note": top_mechanism,
            "rows": [row for _, row in members],
        })
    if secondary:
        members = sorted(secondary, key=_row_sort_key)
        layers.append({
            "title": "Secondary — indirect exposure",
            "relationship": "SECONDARY",
            "icon": "side",
            "note": None,
            "rows": [row for _, row in members],
        })
    return layers


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
    fundamentals, volatility_range, logo_url. Every affected company appears exactly once (peak included
    -- the card back is the complete who's-affected view, spec §2)."""
    moves_by_company_id = {
        m.company_id: m for m in session.query(MarketMove).filter_by(alert_id=alert.id).all()
    }
    ok_excess_values = [
        m.excess_move_pct for m in moves_by_company_id.values() if m.measurement_status == "ok"
    ]
    breadth_score = compute_breadth_score(ok_excess_values)

    cap_tiers = cap_tier_map(session)

    # One query for the whole card back, not one per row (spec §6).
    vol_by_company, vol_by_sector = ranges_for_category(session, alert.category)

    edges = session.query(ImpactEdge).filter_by(alert_id=alert.id).all()
    relation_by_company_id: dict[int, str] = {}
    for edge in edges:
        for company_id in (edge.to_company_id, edge.from_company_id):
            if company_id is not None and company_id not in relation_by_company_id:
                relation_by_company_id[company_id] = edge.relation

    rows_flat: list[dict] = []
    contexts: list[RowContext] = []
    bucket_keys: list[str] = []
    # True only for deterministic sector-wide fan-out rows (basis ==
    # "sector_inference") -- the actual condition "is not a fan-out row",
    # never a proxy. bucket_keys[i] == "SECTOR_WIDE" is NOT equivalent to
    # this: relation_to_ripple_relationship returns SECTOR_WIDE for several
    # genuinely-analyzed relations (credit_cost/regulation/currency/
    # correlation) AND as its default for an unrecognized/empty relation --
    # which engine_relation always is for a company with no ImpactEdge at
    # all. Using bucket_keys as the fan-out proxy barred every such
    # genuinely-analyzed indirect_l1/indirect_l2 row from tiers 1
    # (generated layers) and 2 (static template), even though it was
    # legitimately offered to refinement's generate_ripple_layers and may
    # have been grouped into a section there -- silently dropping it at
    # read time instead.
    is_fanout: list[bool] = []
    for alert_company in alert.companies:
        company = alert_company.company
        move = moves_by_company_id.get(alert_company.company_id)
        status = move.measurement_status if move else None
        exposure_only = is_exposure_only(status)

        engine_relation = relation_by_company_id.get(alert_company.company_id, "")
        # basis, not impact_level, decides the bucket. A sector-inference row
        # is deterministic fan-out (app.analysis.cascade._sector_fanout_mentions
        # -> app.companies.resolution's top-N-by-tier expansion) with no
        # article-specific reasoning behind it, and it carries
        # impact_level="direct" for a PRIMARY sector -- so dispatching on
        # impact_level rendered it identically to a genuinely analyzed
        # company. Confirmed live: ETERNAL.NS (food delivery) shown as
        # "directly affected" by a crude-oil supply shock. Sector exposure is
        # still shown, but only ever in the SECTOR_WIDE bucket.
        if alert_company.basis == "sector_inference":
            relationship = "SECTOR_WIDE"
        elif alert_company.impact_level == "direct":
            relationship = "DIRECT"
        else:
            relationship = relation_to_ripple_relationship(engine_relation)

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
            # Sourced descriptions only -- the legacy LLM-invented values
            # stay withheld. The URL is the CC BY-SA attribution and must
            # travel with the text.
            "business_desc": (_desc := sourced_description(company))[0],
            "business_desc_source_url": _desc[1],
            "fundamentals": fundamentals_payload(company),
            # Empirical reaction range for this news category (subsystem D).
            # None below the sample thresholds -- omit, never fabricate.
            "volatility_range": lookup_range(vol_by_company, vol_by_sector, company),
            "direction": alert_company.direction,
            "excess_move_pct": None,
            "intensity": None,
            "is_exposure_only": exposure_only,
            "in_my_holdings": alert_company.company_id in held_company_ids,
            "why": alert_company.why,
            "logo_url": logo_url(company),
            # Two separate truths per row (spec §37/§38): the fundamental
            # analysis (economic_effect + gate tier) and the observed
            # market reaction (dead-zone-classified). Additive fields --
            # legacy consumers ignore them; NULL on pre-gate rows.
            "economic_effect": alert_company.economic_effect,
            "display_tier": alert_company.display_tier,
            "reaction_direction": classify_reaction(
                move.excess_move_pct if (not exposure_only and move is not None) else None),
        }
        if not exposure_only and move is not None and move.excess_move_pct is not None:
            row["excess_move_pct"] = move.excess_move_pct
            row["intensity"] = _intensity_for_company_move(session, company, move, breadth_score)
        rows_flat.append(row)
        bucket_keys.append(relationship)
        is_fanout.append(alert_company.basis == "sector_inference")
        contexts.append(RowContext(
            sector=company.sector,
            sub_sector=company.sub_sector,
            relation=engine_relation,
            direction=alert_company.direction,
            impact_level=alert_company.impact_level,
        ))

    # V4 strict (spec §23): gate-validated alerts render deterministic
    # taxonomy sections; legacy alerts (None) fall through to the 3-tier
    # path below, which stays byte-identical for flag-off rendering.
    if settings.impact_engine_v4_strict:
        strict_layers = _strict_sections(alert, rows_flat)
        if strict_layers is not None:
            return strict_layers

    def _sorted(rows: list[dict]) -> list[dict]:
        return sorted(rows, key=lambda r: r["intensity"]["score"] if r["intensity"] else -1, reverse=True)

    layers = []
    remaining_indices = list(range(len(rows_flat)))

    # 1) Story-adaptive sections generated per alert by the LLM refinement
    # layer (spec §5: the app adapts sections to the news -- reusing
    # archetype shapes when they fit, inventing new ones when they don't).
    # Zero persisted rows -> fall through to the static archetype template.
    generated = (
        session.query(AlertRippleLayer)
        .filter_by(alert_id=alert.id)
        .order_by(AlertRippleLayer.position.asc())
        .all()
    )
    if generated:
        # Only analyzed rows are claimable by a generated (tier-1) layer.
        # A sector-inference row is deterministic fan-out with no
        # article-specific reasoning; letting a story-specific section claim
        # it would bypass the SECTOR_WIDE routing above and reintroduce the
        # exact misrepresentation that routing exists to prevent. Tested on
        # is_fanout (basis == "sector_inference"), NOT bucket_keys ==
        # "SECTOR_WIDE" -- a genuinely analyzed row can also land in the
        # SECTOR_WIDE bucket (e.g. no ImpactEdge at all, or a
        # credit_cost/regulation/currency/correlation relation), and must
        # still be claimable here.
        index_by_ticker = {
            rows_flat[i]["ticker"]: i
            for i in remaining_indices
            if not is_fanout[i]
        }
        claimed: set[int] = set()
        for gen_layer in generated:
            row_indices = [
                index_by_ticker[t]
                for t in json.loads(gen_layer.tickers_json)
                if t in index_by_ticker and index_by_ticker[t] not in claimed
            ]
            if not row_indices:
                continue
            claimed.update(row_indices)
            rows = _sorted([rows_flat[i] for i in row_indices])
            layers.append({
                "title": gen_layer.title,
                "relationship": gen_layer.relationship,
                "icon": _layer_icon(rows),
                "note": gen_layer.note,
                "rows": rows,
            })
        remaining_indices = [i for i in remaining_indices if i not in claimed]
        # Anything the generated sections didn't claim falls through to the
        # generic buckets below -- never dropped. The static template is
        # skipped: mixing two section systems on one card reads as noise.
        template = None
    else:
        # 2) Static archetype template (spec §5): named sections like
        # "Losers — producers" / "Winners — refiners & marketers" for the
        # news categories a template covers; companies the template doesn't
        # claim fall through to the generic relationship buckets below.
        template = template_layers_for(alert.event_type)
    if template is not None:
        assigned, unmatched = assign_to_template(template, contexts)
        # RowContext carries no `basis`, so a template matcher keyed on
        # sector or impact_level alone (MACRO_POLICY's "banks vs NBFCs",
        # SUPPLY_CHAIN's "protected makers") will happily claim a
        # deterministic fan-out row into a DIRECT-family layer -- the same
        # misrepresentation the bucket routing above exists to prevent, one
        # tier up. Rather than teach every matcher about basis (and reshape
        # RowContext for it), pull fan-out rows back out of whatever they
        # were assigned to and let them fall through to the generic buckets,
        # where the routing already sends them to SECTOR_WIDE. Filtering
        # `contexts` before the call is NOT an option: assigned/unmatched are
        # indices into that list. Tested on is_fanout, not bucket_keys ==
        # "SECTOR_WIDE" -- see the is_fanout comment above; the same
        # over-broad proxy would otherwise pull genuinely-analyzed rows back
        # out of a template layer they were correctly assigned to.
        reclaimed = []
        for layer_index, row_indices in list(assigned.items()):
            kept = [i for i in row_indices if not is_fanout[i]]
            reclaimed.extend(i for i in row_indices if is_fanout[i])
            if kept:
                assigned[layer_index] = kept
            else:
                del assigned[layer_index]
        unmatched = sorted(set(unmatched) | set(reclaimed))
        for layer_index, layer_def in enumerate(template):
            row_indices = assigned.get(layer_index)
            if not row_indices:
                continue
            rows = _sorted([rows_flat[i] for i in row_indices])
            icon = _layer_icon(rows)
            if layer_def.fixed_title is not None:
                title = layer_def.fixed_title
            elif icon == "win":
                title = f"Winners — {layer_def.label}"
            elif icon == "lose":
                title = f"Losers — {layer_def.label}"
            else:
                title = f"Mixed — {layer_def.label}"
            layers.append({
                "title": title,
                "relationship": layer_def.relationship,
                "icon": icon,
                "note": layer_def.note,
                "rows": rows,
            })
        remaining_indices = unmatched

    grouped: dict[str, list[dict]] = {}
    for row_index in remaining_indices:
        grouped.setdefault(bucket_keys[row_index], []).append(rows_flat[row_index])

    for relationship in _LAYER_ORDER:
        rows = grouped.pop(relationship, None)
        if not rows:
            continue
        # A multi-sector DIRECT bucket splits into one section per sector --
        # a broad event (war, macro shock) marks its whole fan-out "direct",
        # and one flat all-companies list loses the card back's entire
        # sectioned structure (confirmed live: geopolitics alerts rendered a
        # single 10-row DIRECT blob). Per-sector sections keep the layered
        # reading without inventing relationships that were never analyzed.
        if relationship == "DIRECT" and len({r["sector"] for r in rows}) > 1:
            by_sector: dict[str, list[dict]] = {}
            for row in rows:
                by_sector.setdefault(row["sector"], []).append(row)
            sector_groups = sorted(
                by_sector.items(),
                key=lambda kv: max((r["intensity"]["score"] if r["intensity"] else -1) for r in kv[1]),
                reverse=True,
            )
            for sector, sector_rows in sector_groups:
                sector_rows = _sorted(sector_rows)
                icon = _layer_icon(sector_rows)
                label = _SECTOR_LABELS.get(sector, sector.replace("_", " "))
                if icon == "win":
                    title = f"Winners — {label}"
                elif icon == "lose":
                    title = f"Losers — {label}"
                else:
                    title = f"Mixed — {label}"
                layers.append({
                    "title": title,
                    "relationship": "DIRECT",
                    "icon": icon,
                    "note": _layer_note(edges, relationship),
                    "rows": sector_rows,
                })
            continue
        rows = _sorted(rows)
        icon = _layer_icon(rows)
        layers.append({
            "title": _layer_title(relationship, icon),
            "relationship": relationship,
            "icon": icon,
            "note": _layer_note(edges, relationship),
            "rows": rows,
        })
    return layers
