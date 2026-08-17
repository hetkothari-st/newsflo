"""Blueprint §11/§12/§21: every mechanism carries a controlled relation,
directness, and section label; no raw ids can leak as labels."""
import pytest

from app.analysis.impact_graph import knowledge

EDGE_RELATIONS = {
    "REVENUE_REALIZATION", "INPUT_COST", "OPERATING_MARGIN", "REFINING_SPREAD",
    "MARKETING_MARGIN", "DEMAND", "PRICING_POWER", "CURRENCY_TRANSLATION",
    "VALUATION_MULTIPLE", "CAPEX", "SUPPLY", "COMPETITIVE", "REGULATORY",
    "FINANCING", "OTHER",
}


def test_every_mechanism_has_relation_directness_and_label():
    for mid, spec in knowledge.MECHANISMS.items():
        assert spec["relation"] in EDGE_RELATIONS, mid
        assert spec["directness"] in ("DIRECT", "INDIRECT", "REMOTE"), mid
        label = spec["section_label"]
        assert label and label != mid and "_" not in label, mid  # human words, not a node id


def test_normative_directness_examples():
    assert knowledge.MECHANISMS["upstream_realization"]["directness"] == "DIRECT"
    assert knowledge.MECHANISMS["aviation_fuel_cost"]["directness"] == "DIRECT"
    assert knowledge.MECHANISMS["paints_input_cost"]["directness"] == "INDIRECT"


def test_normative_relation_examples():
    assert knowledge.MECHANISMS["upstream_realization"]["relation"] == "REVENUE_REALIZATION"
    assert knowledge.MECHANISMS["aviation_fuel_cost"]["relation"] == "INPUT_COST"
    assert knowledge.MECHANISMS["refiner_marketing_margin"]["relation"] == "MARKETING_MARGIN"
    # §21's driving defect: realization/input-cost mechanisms must no longer say demand
    assert knowledge.MECHANISMS["upstream_realization"]["relation"] != "DEMAND"


def test_mechanism_meta_and_section_label_helpers():
    meta = knowledge.mechanism_meta("upstream_realization")
    assert meta["section_label"] == "Upstream oil producers"
    assert knowledge.mechanism_meta("nonexistent_xyz") is None
    assert knowledge.section_label_for("economic_node", "upstream_realization") == "Upstream oil producers"
    assert knowledge.section_label_for("economic_node", "nonexistent_xyz") is None


def test_registry_version_bumped():
    assert knowledge.KNOWLEDGE_REGISTRY_VERSION == "kg-3"


def test_fix_round_1_disputed_entries():
    """Review round 3 audit (fix round 1): four entries were misclassified
    on the first pass. Locked here so a future edit can't silently regress
    them back to the wrong label.
    """
    # Credit-quality contagion (borrower distress -> lender asset quality)
    # is not the financier's own funding-cost repricing -- no EDGE_RELATIONS
    # member covers contagion specifically, so OTHER is the honest label,
    # never a wrong specific one (e.g. FINANCING, which bank_nim_repricing/
    # nbfc_funding_cost correctly reserve for the company's own cost of
    # capital).
    assert knowledge.MECHANISMS["vehicle_financier_stress"]["relation"] == "OTHER"

    # Imported-input repricing is INPUT_COST, matching the structurally
    # identical oil_import_bill_currency -- CURRENCY_TRANSLATION is reserved
    # for translation of foreign-currency revenue/earnings (the IT/pharma
    # export shape), not the cost side of an import.
    assert knowledge.MECHANISMS["import_cost_inflation"]["relation"] == "INPUT_COST"
    assert knowledge.MECHANISMS["electronics_import_cost"]["relation"] == "INPUT_COST"

    # Relative price-competitiveness framing matches ev_relative_advantage's
    # COMPETITIVE/INDIRECT shape, not a currency-translation mechanism.
    assert knowledge.MECHANISMS["textile_export_competitiveness"]["relation"] == "COMPETITIVE"
    assert knowledge.MECHANISMS["textile_export_competitiveness"]["directness"] == "INDIRECT"

    # Monsoon -> farmer purchase-behavior -> agrochemical volume is
    # behavior-mediated demand, same shape as auto_fuel_demand/
    # housing_demand_rates -- not a direct physical effect.
    assert knowledge.MECHANISMS["agrochemical_volume"]["directness"] == "INDIRECT"
    assert knowledge.MECHANISMS["agrochemical_volume"]["relation"] == "DEMAND"


# --- canonical id resolution (node-id consolidation, P0) --------------------
#
# `normalize_node_id` is the canonical WRITER transform, but 9 of the 42
# MECHANISMS keys change under it, so a persisted `causal_parent_id` speaks a
# different dialect from the registry's own keys. These accessors are the ONE
# place the two dialects meet; every alias map in the tree collapses onto them.

def _drifting():
    from app.analysis.impact_graph.normalize import normalize_node_id

    return {mid: normalize_node_id(mid) for mid in knowledge.MECHANISMS
            if normalize_node_id(mid) != mid}


def test_the_drift_set_is_exactly_the_nine_ids_the_sweep_measured():
    """The blast radius, pinned. A normalize.py rule change or a registry
    rename that grows this set has to be looked at, not discovered later."""
    assert _drifting() == {
        "paints_input_cost": "paint_input_cost",
        "nbfc_funding_cost": "nbfc_financing_cost",
        "housing_demand_rates": "housing_demand_rate",
        "durables_financing_demand": "durable_financing_demand",
        "corporate_capex_rates": "corporate_capex_rate",
        "staples_volume_pressure": "staple_volume_pressure",
        "electronics_import_cost": "electronic_import_cost",
        "capital_goods_orders": "capital_good_order",
        "freight_rate_spike": "freight_rate_up",
    }


def test_normalize_never_collides_two_mechanisms_onto_one_persisted_id():
    """The alias map is only well-defined while the transform is injective
    over the registry -- two mechanisms sharing one persisted id would make
    `resolve_mechanism_id` pick arbitrarily."""
    from app.analysis.impact_graph.normalize import normalize_node_id

    persisted = [normalize_node_id(mid) for mid in knowledge.MECHANISMS]
    assert len(set(persisted)) == len(persisted)


def test_resolve_mechanism_id_answers_in_either_dialect():
    for raw, persisted in _drifting().items():
        assert knowledge.resolve_mechanism_id(raw) == raw
        assert knowledge.resolve_mechanism_id(persisted) == raw
    # a stable id is its own answer in both dialects (they are one string)
    assert knowledge.resolve_mechanism_id("aviation_fuel_cost") == "aviation_fuel_cost"


def test_resolve_mechanism_id_owns_nothing_it_does_not_know():
    assert knowledge.resolve_mechanism_id("not_a_mechanism_xyz") is None
    assert knowledge.resolve_mechanism_id("") is None
    assert knowledge.resolve_mechanism_id(None) is None


def test_mechanism_meta_for_node_reads_the_persisted_dialect():
    for raw, persisted in _drifting().items():
        assert knowledge.mechanism_meta_for_node(persisted) == knowledge.mechanism_meta(raw)
    assert knowledge.mechanism_meta_for_node("not_a_mechanism_xyz") is None


def test_section_label_for_node_reads_the_persisted_dialect():
    for raw, persisted in _drifting().items():
        assert (knowledge.section_label_for_node("economic_node", persisted)
                == knowledge.section_label_for("economic_node", raw))
    # the registry does not own sector/company parents -- the caller keeps
    # its own controlled OTHER label rather than borrowing a mechanism's
    assert knowledge.section_label_for_node("sector", "paint_input_cost") is None
    assert knowledge.section_label_for_node("company", "paint_input_cost") is None
    # an id-only caller (parent_type "") is still served: pipeline and the
    # publication gate both tolerate the bare id
    assert (knowledge.section_label_for_node("", "paint_input_cost")
            == knowledge.section_label_for("economic_node", "paints_input_cost"))


def test_the_alias_map_is_derived_never_restated():
    """Structural: the index is built FROM normalize_node_id, so a registry
    rename cannot orphan a mechanism behind a hand-written table."""
    from app.analysis.impact_graph.normalize import normalize_node_id

    for mid in knowledge.MECHANISMS:
        assert knowledge.resolve_mechanism_id(normalize_node_id(mid)) == mid


# --- the 33 non-drifting mechanisms behave byte-identically (R6) -----------
#
# The consolidation must be a NO-OP for every mechanism `normalize_node_id`
# leaves alone: raw and persisted are one string there, so the new accessors,
# the old raw-keyed primitives, the V5 taxonomy and the publication gate must
# all agree, on every one of them, at every distance. Recorded before/after
# over all four resolution paths: diff EMPTY.

def _stable_mechanism_ids():
    from app.analysis.impact_graph.normalize import normalize_node_id

    return sorted(mid for mid in knowledge.MECHANISMS
                  if normalize_node_id(mid) == mid)


def test_the_stable_set_is_the_other_thirty_three():
    assert len(_stable_mechanism_ids()) == 33
    assert len(_stable_mechanism_ids()) + len(_drifting()) == len(knowledge.MECHANISMS)


@pytest.mark.parametrize("mechanism_id", _stable_mechanism_ids())
def test_a_stable_mechanism_resolves_identically_through_every_path(mechanism_id):
    """Raw-key lookup and node lookup are the SAME answer here -- raw ==
    normalized -- so any divergence would be a regression introduced by the
    accessors themselves rather than a correction."""
    from app.output.section_config import load_section_taxonomy

    assert knowledge.resolve_mechanism_id(mechanism_id) == mechanism_id
    # the new accessor and the raw-keyed primitive it wraps
    assert (knowledge.mechanism_meta_for_node(mechanism_id)
            == knowledge.mechanism_meta(mechanism_id))
    assert (knowledge.section_label_for_node("economic_node", mechanism_id)
            == knowledge.section_label_for("economic_node", mechanism_id))
    # the V5 taxonomy names it -- never the UNCLASSIFIED fallback
    taxonomy = load_section_taxonomy()
    label = taxonomy.mechanism_label(mechanism_id)
    assert taxonomy.unknown_label_word not in label
    assert label == taxonomy.labels[mechanism_id]


@pytest.mark.parametrize("mechanism_id", _stable_mechanism_ids())
@pytest.mark.parametrize("distance", (1, 2, 3))
def test_a_stable_mechanism_gets_its_registry_directness_at_every_distance(
        mechanism_id, distance):
    from app.analysis.impact_graph.publication_gate import derive_directness

    class _Candidate:
        causal_parent_id = mechanism_id
        causal_parent_type = "economic_node"
        causal_distance = distance
        causal_directness = None

    assert (derive_directness(_Candidate())
            == knowledge.MECHANISMS[mechanism_id]["directness"])
