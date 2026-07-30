"""RippleTemplates (spec v2 §5 -- "the analytical heart"): reusable
per-archetype layer maps that turn an alert's affected companies into the
named, curated card-back sections -- "Losers — producers", "Winners —
refiners & marketers", "Winners — by-products", "Winners — heavy users",
the banks-vs-NBFCs direct split, defensive rotation, protected/exposed
makers -- instead of raw relationship buckets.

A template DEFINES layers (title label, spec relationship type, one-line
note, matcher); companies are matched into layers from their real
analyzed attributes (sector, sub-sector, engine relation, direction,
impact level). Direction is never stored per stock -- each layer's
Winners/Losers prefix derives from its rows' own analyzed directions
(spec §5: "direction rule, not a fixed direction"). Companies no template
layer claims fall back to the generic relationship buckets, appended
after the template layers -- omit-from-template rather than force a
wrong section.

Adding a news category = adding a template here, not rewriting the
engine (spec §5).
"""
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class RowContext:
    """The real analyzed attributes a matcher may use."""
    sector: str
    sub_sector: str | None
    relation: str  # engine EDGE_RELATIONS value ("" for direct companies)
    direction: str  # bullish | bearish
    impact_level: str  # direct | indirect_l1 | indirect_l2


@dataclass
class LayerDef:
    label: str  # "producers", "refiners & marketers", ... (sentence case per spec §11)
    relationship: str  # spec vocabulary: SELLER / USER / BYPRODUCT / ...
    note: str
    match: Callable[[RowContext], bool]
    # Fixed title (e.g. "Direct — banks vs NBFCs", "Defensive rotation")
    # instead of the computed Winners/Losers prefix.
    fixed_title: str | None = field(default=None)


# --- Archetype A: commodity-price shape (spec §5 A) -----------------------

# Matchers trust sub_sector independently of sector -- production sector
# classifications drift (an airline filed under "other", a paints maker
# under "fmcg", both observed live), while the sub-sector label is the
# more specific and more reliable signal when present.
_COMMODITY_LAYERS = [
    LayerDef(
        label="producers",
        relationship="SELLER",
        note="They sell the commodity; a price move hits realisations directly.",
        match=lambda c: (
            c.sub_sector in ("upstream_exploration", "mining_coal")
            or (c.sector == "oil_gas" and c.sub_sector is None)
            or c.sector == "metals"
            or (c.sector == "agriculture" and c.sub_sector != "fertilizers")
        ),
    ),
    LayerDef(
        label="refiners & marketers",
        relationship="USER",
        note="They buy the commodity as input; margins move opposite to its price.",
        match=lambda c: c.sub_sector == "refining_marketing",
    ),
    LayerDef(
        label="by-products",
        relationship="BYPRODUCT",
        note="Derivatives — paints, tyres, plastics, specialty chem — feel the feedstock move.",
        match=lambda c: (
            c.sub_sector in ("paints", "specialty_chemicals", "commodity_chemicals", "auto_component")
            or c.sector in ("chemicals", "textiles")
        ),
    ),
    LayerDef(
        label="heavy users",
        relationship="USER",
        note="The commodity is a major cost line — fuel for airlines, logistics, cement.",
        match=lambda c: (
            c.sub_sector in ("aviation", "logistics_roadways", "ports_shipping", "cement", "power_utilities")
            or c.sector == "railways_transport"
        ),
    ),
]

# --- Archetype B: macro / policy shape (spec §5 B) ------------------------

_MACRO_POLICY_LAYERS = [
    LayerDef(
        label="banks vs NBFCs",
        relationship="RATE_SENSITIVE",
        note="Same layer, opposite signs: banks reprice lending first; NBFCs pay more to borrow.",
        match=lambda c: c.sector == "banking",
        fixed_title="Direct — banks vs NBFCs",
    ),
    LayerDef(
        label="rate-sensitive demand",
        relationship="RATE_SENSITIVE",
        note="Financing costs steer real-estate demand directly.",
        match=lambda c: c.sector == "construction_realestate",
    ),
    LayerDef(
        label="big-ticket purchases",
        relationship="RATE_SENSITIVE",
        note="EMI-financed purchases — autos, durables — track borrowing costs.",
        match=lambda c: c.sector in ("auto", "consumer_durables"),
    ),
    LayerDef(
        label="defensive rotation",
        relationship="DEFENSIVE_ROTATION",
        note="Investors rotate toward low-debt staples and utilities — bought because of the event, not hit by it.",
        match=lambda c: (
            c.sector == "fmcg"
            or (c.sector == "infra" and c.sub_sector == "power_utilities")
        ),
        fixed_title="Defensive rotation",
    ),
]

# --- Archetype C: supply-chain shape (spec §5 C) --------------------------

_SUPPLY_CHAIN_LAYERS = [
    LayerDef(
        label="protected makers",
        relationship="PROTECTED",
        note="Domestic producers the measure shields from imports.",
        match=lambda c: c.impact_level == "direct" and c.direction == "bullish",
    ),
    LayerDef(
        label="exposed users",
        relationship="EXPOSED",
        note="They consume the protected good; their input costs move with the duty.",
        match=lambda c: c.relation in ("input_cost", "customer") or (
            c.impact_level == "direct" and c.direction == "bearish"
        ),
    ),
    LayerDef(
        label="suppliers upstream",
        relationship="SUPPLIER",
        note="Upstream inputs to the protected industry follow its fortunes.",
        match=lambda c: c.relation == "supplier",
    ),
    LayerDef(
        label="substitutes",
        relationship="SUBSTITUTE",
        note="Alternatives to the protected good move sideways as demand shifts.",
        match=lambda c: c.relation == "competitor",
    ),
]

_ARCHETYPE_LAYERS = {
    "COMMODITY": _COMMODITY_LAYERS,
    "MACRO_POLICY": _MACRO_POLICY_LAYERS,
    "SUPPLY_CHAIN": _SUPPLY_CHAIN_LAYERS,
}

# Alert.event_type -> archetype (spec §3.1 NewsEvent.ripple_template).
# Event types not listed have no curated template (earnings, M&A, ...) --
# their card backs keep the generic relationship buckets.
_ARCHETYPE_BY_EVENT_TYPE = {
    "crude_oil": "COMMODITY",
    "commodity_price": "COMMODITY",
    "monsoon_weather": "COMMODITY",
    # Geopolitics stories that reach the feed are overwhelmingly energy-
    # supply-risk shaped (war/sanctions/shipping-route risk moving crude
    # and gas) -- the commodity archetype's producer/refiner/heavy-user
    # split is the right lens for their oil_gas + transport fan-out;
    # companies it can't place (e.g. defense names) fall through to the
    # per-sector fallback sections.
    "geopolitics": "COMMODITY",
    "repo_rate_change": "MACRO_POLICY",
    "inflation": "MACRO_POLICY",
    "global_rates": "MACRO_POLICY",
    "trade_policy": "SUPPLY_CHAIN",
}


def template_layers_for(event_type: str | None) -> list[LayerDef] | None:
    """The ordered template layers for an alert's event type, or None when
    no curated archetype covers it (generic buckets apply)."""
    if event_type is None:
        return None
    archetype = _ARCHETYPE_BY_EVENT_TYPE.get(event_type)
    if archetype is None:
        return None
    return _ARCHETYPE_LAYERS[archetype]


def assign_to_template(
    layers: list[LayerDef], contexts: list[RowContext]
) -> tuple[dict[int, list[int]], list[int]]:
    """Assign each context (by index) to the FIRST template layer whose
    matcher accepts it. Returns ({layer_index: [row_indices]},
    [unmatched_row_indices]) -- unmatched rows fall back to the caller's
    generic buckets, never a forced wrong section."""
    assigned: dict[int, list[int]] = {}
    unmatched: list[int] = []
    for row_index, context in enumerate(contexts):
        for layer_index, layer in enumerate(layers):
            if layer.match(context):
                assigned.setdefault(layer_index, []).append(row_index)
                break
        else:
            unmatched.append(row_index)
    return assigned, unmatched
