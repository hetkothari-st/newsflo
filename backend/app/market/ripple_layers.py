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
import logging
import os

from sqlalchemy.orm import Session

from app.analysis.impact_graph.knowledge import MECHANISMS, section_label_for
from app.analysis.impact_graph.normalize import normalize_node_id
from app.analysis.impact_graph.publication_gate import (
    TIER_MACRO_CONTEXT, TIER_PRIMARY, is_displayable_tier, is_gated,
    is_secondary_tier, materiality_grade,
)
from app.analysis.refinement import divergence_line
from app.companies.branding import logo_url
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

logger = logging.getLogger(__name__)

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


# Controlled taxonomy labels for strict-mode sections (spec §23, corrective-
# v4 Task 12): keyed by the causal parent node the gate validated -- the
# archetype-mapping path (app.analysis.impact_graph.engine._archetype_mapping)
# always sets that node id to normalize_node_id(mechanism_id), so every key
# below is normalize_node_id() applied to a MECHANISMS id in
# app.analysis.impact_graph.knowledge (test_all_42_mechanisms_have_labels
# pins full coverage). The first entries predate the 42-mechanism registry
# -- top-level trigger-variable node ids observed on production rows, not
# mechanism ids themselves -- and stay for backward compatibility (M3,
# review round 2: the provably-unreachable "repo_rate" entry among them was
# deleted -- see the inline comment at its old position below).
# Unknown parent ids (a novel/LLM-authored node, or a dynamic-discovery
# node with no archetype mechanism behind it) get OTHER_LABEL: raw LLM/
# engine node ids must never reach the UI verbatim (INV: controlled
# taxonomy only). This dict backs ONLY the default (non-sector, non-company)
# causal_parent_type branch of _strict_sections' _label_for -- "sector" and
# "company" parents resolve through _SECTOR_LABELS and a "linked to <name>"
# rule instead (I5, review round 2).
_TAXONOMY_LABELS = {
    "crude_price": "crude-linked",
    "tyre_input_cost": "tyre input costs",
    "aviation_fuel_cost": "aviation fuel costs",
    "paint_input_cost": "paint input costs",
    "refining_margin": "refining & marketing",
    # "repo_rate" deleted (M3, review round 2): normalize_node_id() rewrites
    # every reachable canonical form of this trigger to "interest_rate_up"
    # (see normalize.py's repo_rate phrase-merge rule), so the bare string
    # "repo_rate" can never actually be produced as a causal_parent_id --
    # provably dead.
    "inr_depreciation": "currency-exposed",
    "road_freight_fuel_cost": "freight fuel costs",
    # -- crude oil family --
    "upstream_realization": "upstream oil producers",
    "refiner_marketing_margin": "refining & marketing",
    "lubricant_base_oil_cost": "lubricant input costs",
    "petrochemical_feedstock": "petrochemical feedstock costs",
    "cement_energy_freight": "cement energy & freight costs",
    "auto_fuel_demand": "auto fuel-cost demand drag",
    "two_wheeler_fuel_demand": "two-wheeler fuel-cost demand drag",
    "ev_relative_advantage": "EV relative advantage",
    "vehicle_financier_stress": "vehicle-financier asset stress",
    "crude_inflation_pressure": "crude-led inflation pressure",
    "oil_import_bill_currency": "oil import bill & currency",
    # -- rates family --
    "bank_nim_repricing": "bank margin repricing",
    "nbfc_financing_cost": "NBFC funding costs",
    "housing_demand_rate": "housing demand & rates",
    "durable_financing_demand": "durables financing demand",
    "auto_financing_demand": "auto financing demand",
    "corporate_capex_rate": "corporate capex & rates",
    # -- inflation family --
    "staple_volume_pressure": "staples volume pressure",
    "discretionary_demand_squeeze": "discretionary demand squeeze",
    "rate_expectation_shift": "rate expectation shift",
    # -- currency family --
    "it_export_realization": "IT export realization",
    "pharma_export_realization": "pharma export realization",
    "textile_export_competitiveness": "textile export competitiveness",
    "import_cost_inflation": "import cost inflation",
    "electronic_import_cost": "electronics import costs",
    # -- government spending family --
    "cement_demand_infra": "cement demand from infrastructure",
    "epc_order_book": "EPC order books",
    "steel_demand_infra": "steel demand from infrastructure",
    "capital_good_order": "capital goods orders",
    "infra_logistics_volume": "infrastructure logistics volume",
    # -- trade/tariff family --
    "domestic_producer_protection": "domestic producer protection",
    "downstream_input_cost_tariff": "downstream input costs (tariff)",
    # -- geopolitical supply disruption --
    "freight_rate_up": "freight rate spikes",
    "defense_procurement_sentiment": "defense procurement sentiment",
    # -- monsoon/rural family --
    "rural_income_agri": "rural agri income",
    "rural_fmcg_demand": "rural FMCG demand",
    "rural_two_wheeler_demand": "rural two-wheeler demand",
    "agrochemical_volume": "agrochemical volume",
}

# Controlled fallback for a causal_parent_id with no taxonomy entry (a novel
# node an LLM named, or a dynamic-discovery node with no archetype
# mechanism behind it) -- never the raw node id itself.
OTHER_LABEL = "other verified mechanisms"

# --- mechanism registry bridge (final blueprint §12, T1 interface) --------
# `knowledge.section_label_for` is the AUTHORITY on a mechanism's controlled
# section label; `_TAXONOMY_LABELS` above survives only as the fallback for
# ids the registry does not own (top-level trigger variables like
# "crude_price"/"inr_depreciation" that engine.py can set as a causal parent,
# and anything persisted before the registry existed).
#
# The indirection below exists because the two speak slightly different id
# dialects: the registry is keyed by RAW MECHANISMS ids, while a persisted
# `causal_parent_id` is `normalize_node_id(mechanism_id)` -- and 9 of the 42
# registry ids change under that rewrite ("paints_input_cost" ->
# "paint_input_cost", "capital_goods_orders" -> "capital_good_order", ...).
# A direct `section_label_for(parent_type, parent_id)` therefore MISSES those
# nine on real rows and would silently drop them to the legacy table, so the
# normalized index is consulted second. Values still come from
# `section_label_for` itself -- this module never restates a label.
_REGISTRY_LABEL_BY_NORMALIZED_ID = {
    normalize_node_id(mechanism_id): section_label_for("economic_node", mechanism_id)
    for mechanism_id in MECHANISMS
}
# Curated per-mechanism explanation (§14): deterministic, human-written, and
# true of EVERY member of a section built on that mechanism -- unlike a
# single company's LLM rationale, which is only ever true of that company.
_REGISTRY_NOTE_BY_NORMALIZED_ID = {
    normalize_node_id(mechanism_id): spec["mechanism"]
    for mechanism_id, spec in MECHANISMS.items()
}
# Each mechanism's CANONICAL trigger effect, indexed the same way. The
# registry writes every sentence for one direction of its trigger variable
# (`crude_price_up`); `knowledge.oriented_mechanisms` flips the EFFECT for
# an inverted event but never rewrites the prose. Serving the note without
# checking this publishes "margins compress quickly" over a section of
# POSITIVE-effect rows -- see _registry_note.
_REGISTRY_EFFECT_BY_NORMALIZED_ID = {
    normalize_node_id(mechanism_id): spec["effect"]
    for mechanism_id, spec in MECHANISMS.items()
}
# Parent types ripple_layers resolves ITSELF (T1's ownership split): "sector"
# through _SECTOR_LABELS, "company" through a "linked to <name>" rule. Every
# other parent type is registry-owned.
_LOCALLY_OWNED_PARENT_TYPES = ("sector", "company")


def _registry_label(parent_type: str | None, parent_id: str) -> str | None:
    """T1's controlled section label for a persisted causal parent, or None
    when the registry does not own this parent type / does not know this id
    (caller then falls back to _TAXONOMY_LABELS, then OTHER_LABEL -- never
    the raw id)."""
    if parent_type in _LOCALLY_OWNED_PARENT_TYPES:
        return None
    # Direct T1 call first: correct for a raw, un-normalized mechanism id.
    label = section_label_for(parent_type or "", parent_id)
    if label is not None:
        return label
    return _REGISTRY_LABEL_BY_NORMALIZED_ID.get(parent_id)


def _registry_note(parent_type: str | None, parent_id: str,
                   section_effect: str | None) -> str | None:
    """The registry's curated mechanism sentence for a causal parent (§14),
    or None.

    DIRECTION GUARD (blueprint §24; review round 1, I1). The registry's
    prose is written for each mechanism's CANONICAL trigger direction, so
    it is only true of a section whose fundamental effect matches. On a
    crude-DECLINE event the airline section's effect is `positive` while
    `aviation_fuel_cost`'s sentence still reads "...so margins compress
    quickly" -- serving it there contradicts every row underneath it.

    Task 8 put exactly this check on the per-ROW display text
    (`evidence._registry_text_for_entry`); without the same check here the
    guard was defeated one level up, and the worst case was the sentence
    blanked from the row and reprinted, unchanged, as the section note
    directly above it.

    A `mixed` canonical effect is compatible with anything: those sentences
    explicitly take no side ("never automatically bullish or bearish").
    `section_effect` is None when the section's members do not share one
    effect (macro sections group on label alone, so they can be
    heterogeneous) -- no single effect to check against means no borrow."""
    if parent_type in _LOCALLY_OWNED_PARENT_TYPES:
        return None
    spec = MECHANISMS.get(parent_id)          # raw, un-normalized id
    if spec is not None:
        note, canonical = spec["mechanism"], spec["effect"]
    else:
        note = _REGISTRY_NOTE_BY_NORMALIZED_ID.get(parent_id)
        canonical = _REGISTRY_EFFECT_BY_NORMALIZED_ID.get(parent_id)
    if note is None:
        return None
    if canonical == "mixed" or canonical == section_effect:
        return note
    logger.info(
        "registry note for %s withheld: canonical effect %s contradicts "
        "section effect %s", parent_id, canonical, section_effect)
    return None

_EFFECT_PREFIX = {
    "positive": "Positive", "negative": "Negative",
    "mixed": "Mixed", "uncertain": "Uncertain",
    "no_material_impact": "No material impact",
}
# Tier membership is READ through the publication gate's own helpers
# (`is_displayable_tier` / `is_secondary_tier`), which are the ONE place
# read-compat for the dead spellings ("secondary_deep_dive",
# "secondary") lives. This module used to keep its own DISPLAYABLE_TIERS
# tuple; after §3's three-tier rewrite that name COLLIDED with
# publication_gate.DISPLAYABLE_TIERS while listing a different set (five
# spellings vs the three canonical tiers), so an importer could get either
# meaning depending on which module it reached for. Exactly one importable
# `DISPLAYABLE_TIERS` now exists (the gate's); ripple_layers keeps no tier
# tuple at all.

_EFFECT_ICON = {"positive": "win", "negative": "lose"}
_DIRECTION_TO_EFFECT = {"bullish": "positive", "bearish": "negative"}

# Section-kind prefixes on `relationship` (final blueprint §12/§15). The
# prefix is the machine-readable kind; the suffix is the controlled label.
#   MECH:<label>   primary rows, grouped by (effect, mechanism taxonomy)
#   RIPPLE:<label> secondary_ripple rows, SAME grain, rendered after
#   MACRO:<label>  macro_context rows, one trailing section per label
# The pre-blueprint single-bucket "SECONDARY" relationship (and its
# "Secondary — indirect exposure" title) is DELETED: flattening every
# indirect row into one anonymous blob threw away the very mechanism the
# gate validated to admit it.
_KIND_PRIMARY = "MECH"
_KIND_RIPPLE = "RIPPLE"
_KIND_MACRO = "MACRO"


def _assert_section_invariants(layers: list[dict]) -> None:
    """Final blueprint §13: the three membership rules a rendered section
    set must satisfy, checked on the FINAL layer list rather than trusted
    from the grouping code that produced it.

    1. **Same effect within a mechanism section.** MECH:/RIPPLE: sections
       are grouped on (economic_effect, taxonomy label), so a section
       holding two different effects means a company is being shown under a
       thesis that is not its own. A MIXED-effect section is the one
       exemption -- "mixed" is itself the claim (an integrated refiner is
       genuinely both), not an accident of grouping.
    2. **No ticker in two sections.** The card back is a partition, not an
       overlapping tag cloud (INV-010).
    3. **Tier compatibility.** A primary row never renders inside a
       RIPPLE:/MACRO: section and a secondary/macro row never inside a
       MECH: one -- the section kind IS a publication-tier claim, and
       mislabelling it launders a weaker claim into a stronger frame.

    Raises under pytest (PYTEST_CURRENT_TEST is set by pytest itself, so no
    test has to opt in) and logs a warning in production: a serving path
    must degrade to "shown, and loudly recorded" rather than 500 the whole
    card back over a layout defect.
    """
    violations: list[str] = []
    section_by_ticker: dict[str, str] = {}
    for layer in layers:
        kind = (layer.get("relationship") or "").split(":")[0]
        title = layer.get("title") or "?"
        rows = layer.get("rows") or []
        effects = {row.get("economic_effect") for row in rows if row.get("economic_effect")}
        if (kind in (_KIND_PRIMARY, _KIND_RIPPLE) and len(effects) > 1
                and not title.startswith(_EFFECT_PREFIX["mixed"])):
            violations.append(
                f"{title!r} mixes economic_effect {sorted(effects)} in one mechanism section")
        for row in rows:
            ticker = row.get("ticker")
            previous = section_by_ticker.get(ticker)
            if previous is not None:
                violations.append(
                    f"{ticker} appears in two sections ({previous!r} and {title!r})")
            else:
                section_by_ticker[ticker] = title
            if "display_tier" not in row:
                # The row dict does not carry the field at all -- a caller
                # probing _strict_sections with synthetic rows, not a real
                # compute_ripple_layers payload (which always sets it). A
                # missing KEY is "not asserted"; a present key holding NULL
                # is still a violation, so this cannot hide a real one.
                continue
            tier = row["display_tier"]
            if kind == _KIND_PRIMARY and tier != TIER_PRIMARY:
                violations.append(
                    f"{title!r} is a primary section but holds {ticker} at tier {tier!r}")
            elif kind == _KIND_RIPPLE and not is_secondary_tier(tier):
                violations.append(
                    f"{title!r} is a ripple section but holds {ticker} at tier {tier!r}")
            elif kind == _KIND_MACRO and tier != TIER_MACRO_CONTEXT:
                violations.append(
                    f"{title!r} is a macro section but holds {ticker} at tier {tier!r}")
    if not violations:
        return
    message = "section invariant violation: " + "; ".join(violations)
    if os.environ.get("PYTEST_CURRENT_TEST"):
        raise AssertionError(message)
    logger.warning(message)


def _strict_sections(
    alert: Alert, rows_flat: list[dict], include_secondary: bool = True,
) -> list[dict] | None:
    """Deterministic section assembly for gate-validated alerts (spec
    §23-§26, final blueprint §12-§15): direction comes from economic_effect,
    membership from the publication gate's tier, labels from the controlled
    mechanism taxonomy. Returns None when no company clears a displayable
    tier (compute_ripple_layers' structural gate turns that into [], never a
    fall-through to the 3-tier path -- see corrective-v4 Task 12: gate_state
    != NULL makes the legacy generator structurally unreachable, not merely
    undesired).

    Three ordered families of sections come out, all on the SAME grouping
    grain -- (economic_effect, controlled taxonomy label):

      MECH:<label>   primary rows        "Positive — Upstream oil producers"
      RIPPLE:<label> secondary_ripple    "Secondary — Paints & chemicals"
      MACRO:<label>  macro_context       "Macro context — Imported inflation"

    Secondary rows used to be swept into ONE anonymous "Secondary —
    indirect exposure" bucket (final blueprint §12 deletes it): the gate had
    already validated exactly WHICH mechanism admitted each of those rows,
    and the flat bucket threw that away at the last step, leaving the reader
    a list of tickers with no stated reason to be there. They now group by
    the same taxonomy as primaries and simply render after them -- the tier
    difference is carried by the section kind and title, not by erasing the
    mechanism. Macro-context rows get their own trailing sections because
    §7 forbids presenting them as company-specific claims at all.

    ``include_secondary`` (corrective-v4 Task 16, owner decision): the main
    feed contract is PRIMARY only -- "/api/feed-v2 -> PRIMARY only ...
    SECONDARY_DEEP_DIVE should be a separate explicit retrieval path". False
    (the feed's setting) drops every secondary AND macro-context company
    from `gated` entirely -- not merely from a trailing section -- so they
    never shape a mixed primary section and no trailing section is
    appended. True (the deep-dive builder's setting) keeps them."""
    # Keyed on alert_company_id, not position: rows_flat and alert.companies
    # happen to share an order today, but a positional pairing is a latent
    # bug waiting for either list to be re-sorted or filtered independently.
    rows_by_alert_company_id = {row["alert_company_id"]: row for row in rows_flat}
    # Tier membership through the gate's own helpers, never a literal
    # compare: is_displayable_tier is the ONE place the dead spellings
    # ("secondary_deep_dive", "secondary") are still honoured.
    gated = [
        (alert_company, rows_by_alert_company_id[alert_company.id])
        for alert_company in alert.companies
        if (is_displayable_tier(alert_company.display_tier) if include_secondary
            else alert_company.display_tier == TIER_PRIMARY)
    ]
    if not gated:
        return None

    def _effect(alert_company) -> str:
        return (alert_company.economic_effect
                or _DIRECTION_TO_EFFECT.get(alert_company.direction, "mixed"))

    def _row_sort_key(pair):
        alert_company, row = pair
        return (-(alert_company.materiality or 0.0), row["ticker"])

    # Company-parent label resolution (I5, review round 2): engine.py sets
    # causal_parent_id to the PARENT's ticker when causal_parent_type ==
    # "company" (GraphCompany.parent_id), and that parent is frequently
    # itself another company IN this same alert (e.g. a distance-2 "linked
    # to the direct company" row) -- so its display name is usually
    # resolvable from the alert's own companies, no extra DB query needed.
    name_by_company_id = {ac.company_id: ac.company.name for ac in alert.companies}

    def _label_for(alert_company) -> str:
        """Controlled label, never a raw node id. Resolution order: the
        locally-owned parent types first (sector / company), then T1's
        mechanism registry, then this module's legacy taxonomy table (for
        trigger-variable parents like "crude_price" that the registry does
        not own), then OTHER_LABEL."""
        parent_type = alert_company.causal_parent_type
        parent_id = alert_company.causal_parent_id or "event"
        if parent_type == "sector":
            return _SECTOR_LABELS.get(parent_id, OTHER_LABEL)
        if parent_type == "company":
            parent_name = name_by_company_id.get(alert_company.parent_company_id)
            return f"linked to {parent_name or parent_id}"
        registry_label = _registry_label(parent_type, parent_id)
        if registry_label is not None:
            return registry_label
        return _TAXONOMY_LABELS.get(parent_id, OTHER_LABEL)

    def _note_for(members) -> str | None:
        """The "why this layer" line (§14). The registry's curated mechanism
        sentence wins whenever every member shares one registry-known causal
        parent: it is deterministic and true of the whole section by
        construction, where a company's LLM rationale is only ever true of
        that company. Otherwise the pre-existing rule stands -- a note only
        when every member carries an IDENTICAL mechanism string (I6),
        computed on the FINAL post-merge member list so a merged section
        (two distinct unknown parents) still gets no single-company note.

        The registry sentence additionally has to AGREE with the section's
        fundamental effect (review round 1, I1 -- see _registry_note): the
        effect is read off the members here rather than off the section key
        because macro sections are keyed on the label alone and may hold
        rows with different effects."""
        parents = {(ac.causal_parent_type, ac.causal_parent_id) for ac, _ in members}
        if len(parents) == 1:
            parent_type, parent_id = next(iter(parents))
            effects = {_effect(ac) for ac, _ in members}
            registry_note = _registry_note(
                parent_type, parent_id or "event",
                next(iter(effects)) if len(effects) == 1 else None)
            if registry_note is not None:
                return registry_note
        mechanisms = {alert_company.mechanism for alert_company, _ in members}
        return members[0][0].mechanism if len(mechanisms) == 1 else None

    def _assemble(pairs: list, kind: str) -> list[dict]:
        """Two passes, shared by all three section kinds.

        Pass 1 groups by (effect, EXACT parent) -- keyed on parent_type too
        so a "company" ticker string can never collide with a "sector" /
        economic-node id that happens to share text. Pass 2 merges groups
        whose RESOLVED (effect, label) collide (I5): two different unknown
        parents both falling back to OTHER_LABEL must render as ONE section,
        not duplicate-titled ones.

        MACRO sections group on the label alone -- they are context, not a
        directional company claim (§7), so splitting them by effect would
        manufacture exactly the per-company verdict the tier exists to
        avoid.
        """
        by_exact_parent: dict[tuple[str, str, str], list] = {}
        for alert_company, row in pairs:
            key = (
                "" if kind == _KIND_MACRO else _effect(alert_company),
                alert_company.causal_parent_type or "",
                alert_company.causal_parent_id or "event",
            )
            by_exact_parent.setdefault(key, []).append((alert_company, row))

        merged: dict[tuple[str, str], list] = {}
        for (effect, _parent_type, _parent_id), members in by_exact_parent.items():
            merged.setdefault((effect, _label_for(members[0][0])), []).extend(members)

        assembled = []
        ordered = sorted(
            merged.items(),
            key=lambda kv: -max((ac.materiality or 0.0) for ac, _ in kv[1]),
        )
        for (effect, label), members in ordered:
            members = sorted(members, key=_row_sort_key)
            if kind == _KIND_MACRO:
                # No effect prefix and a deliberately neutral icon: macro
                # context is never rendered as a win/lose call on a company.
                title, icon = f"Macro context — {label}", "side"
            elif kind == _KIND_RIPPLE:
                # "Secondary" replaces the effect word in the title (the
                # tier is the headline fact for these rows) but the icon
                # still carries the effect -- the grouping grain is
                # (effect, label), so it is homogeneous and honest.
                title, icon = f"Secondary — {label}", _EFFECT_ICON.get(effect, "side")
            else:
                title = f"{_EFFECT_PREFIX.get(effect, 'Mixed')} — {label}"
                icon = _EFFECT_ICON.get(effect, "side")
            assembled.append({
                "title": title,
                "relationship": f"{kind}:{label}",
                "icon": icon,
                "note": _note_for(members),
                "rows": [row for _, row in members],
            })
        return assembled

    primary_pairs, ripple_pairs, macro_pairs = [], [], []
    for alert_company, row in gated:
        tier = alert_company.display_tier
        if tier == TIER_MACRO_CONTEXT:
            macro_pairs.append((alert_company, row))
        elif is_secondary_tier(tier):
            ripple_pairs.append((alert_company, row))
        else:
            primary_pairs.append((alert_company, row))

    # Fixed inter-family order: primaries first regardless of materiality (a
    # high-materiality SECONDARY row must never outrank the alert's actual
    # thesis), then ripples, then macro context.
    layers = (_assemble(primary_pairs, _KIND_PRIMARY)
              + _assemble(ripple_pairs, _KIND_RIPPLE)
              + _assemble(macro_pairs, _KIND_MACRO))
    _assert_section_invariants(layers)
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


def compute_ripple_layers(
    session: Session, alert: Alert, held_company_ids: set[int], include_secondary: bool = False,
) -> list[dict]:
    """Ordered layers for one alert's card back. Each layer:
    {title, relationship, icon ('win'|'lose'|'side'), note (str|None),
    rows: [...]} -- rows carry ticker, name, sector, cap_tier,
    liquidity_tier, delivery_pct, direction, excess_move_pct,
    intensity, is_exposure_only, in_my_holdings, why, business_desc,
    fundamentals, volatility_range, logo_url. Every affected company appears exactly once (peak included
    -- the card back is the complete who's-affected view, spec §2).

    ``include_secondary`` (corrective-v4 Task 16) only affects gate-
    validated (is_gated) alerts -- the legacy 3-tier path below always
    renders every company regardless of this flag, unchanged. Default False
    is the main feed's contract (spec §52, owner decision: "/api/feed-v2 ->
    PRIMARY only"); app.routers.feed_v2's card-back route passes it
    unchanged. app.routers.stock_deep_dive's internal analysis surface
    passes True to keep seeing secondary/deep-dive companies -- that
    endpoint isn't the public "normal feed" the owner's ruling targets."""
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

    # Computed once, reused both for row-level field gating (below) and the
    # structural gate at the bottom of this function -- a single evaluation
    # so the two can never observe different alert_company snapshots.
    alert_is_gated = is_gated(alert.companies)

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
        if alert_is_gated:
            # Authoritative gate-derived fields (corrective-v4 Task 16) --
            # gated rows only, so a legacy (ungated) row's dict stays
            # byte-identical to its pre-Task-16 shape.
            row["mechanism"] = alert_company.mechanism
            # The COMPOSITE grade the gate evaluated, read straight off the
            # row (final-review finding I3, column added by migration 0007).
            #
            # This used to be `materiality_grade(alert_company.materiality)`
            # -- the NAKED-FLOAT grade -- under a comment claiming that was
            # what the gate stored. It was not: the gate evaluates
            # app.analysis.impact_graph.materiality.materiality_grade's
            # COMPOSITE (the float capped by the company's exposure ordinal
            # and the evidence tier), so a candidate the gate capped to
            # MEDIUM was served to the reader as HIGH -- a grade no gate
            # decision ever accepted. The composite is not recoverable from
            # the float, hence the column.
            #
            # The naked-float fallback survives for LEGACY gated rows
            # persisted before 0007 (materiality_grade NULL): the same value
            # they have always been served, never worse. Still not read from
            # CompanyDecisionRecord -- that audit row can be absent (non-
            # strict analysis paths never write one) and is keyed by ticker,
            # not alert_company_id, so it is not a reliable per-row source.
            row["materiality_grade"] = (
                alert_company.materiality_grade
                if alert_company.materiality_grade is not None
                else materiality_grade(alert_company.materiality)
            )
            row["confidence_band"] = alert_company.confidence_band
            row["impact_type"] = (
                None if alert_company.causal_distance is None
                else "direct" if alert_company.causal_distance == 1
                else "indirect"
            )
            row["expected_market_sensitivity"] = alert_company.expected_market_sensitivity
            # Task 13 template: states outright when the fundamental thesis
            # and the observed reaction point opposite ways; None otherwise
            # (both truths already ride on the row, never overwritten).
            row["divergence"] = divergence_line(alert_company.economic_effect, row["reaction_direction"])
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

    # V4 structural gate (owner-locked invariant, corrective-v4 Task 12,
    # review round 2 / I1): ANY AlertCompany.gate_state OR display_tier !=
    # NULL makes the legacy 3-tier generator STRUCTURALLY unreachable for
    # this alert -- not merely "we prefer not to call it" (see
    # app.analysis.impact_graph.publication_gate.is_gated's docstring for
    # why it's an OR, not gate_state alone). This deliberately does NOT
    # read settings.impact_engine_v4_strict: the flag controls whether NEW
    # alerts get gated at analysis time, but once gate data is persisted on
    # a row, flipping the flag back off must never resurrect the legacy
    # renderer for it. _strict_sections returning None (no company cleared
    # DISPLAYABLE_TIERS) still returns [] here, never a fall-through.
    # The 3-tier path below runs ONLY when the alert is not gated at all,
    # and stays byte-identical for those alerts (existing tests pin it).
    if alert_is_gated:
        return _strict_sections(alert, rows_flat, include_secondary) or []

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
