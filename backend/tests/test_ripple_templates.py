from app.market.ripple_templates import (
    RowContext,
    assign_to_template,
    template_layers_for,
)


def _ctx(sector, sub_sector=None, relation="", direction="bullish", impact_level="indirect_l1"):
    return RowContext(
        sector=sector, sub_sector=sub_sector, relation=relation,
        direction=direction, impact_level=impact_level,
    )


def test_uncovered_event_types_have_no_template():
    assert template_layers_for(None) is None
    assert template_layers_for("earnings") is None
    assert template_layers_for("merger_acquisition") is None


def test_commodity_template_sections_match_the_spec_archetype():
    layers = template_layers_for("crude_oil")
    labels = [layer.label for layer in layers]
    assert labels == ["producers", "refiners & marketers", "by-products", "heavy users"]

    contexts = [
        _ctx("oil_gas", "upstream_exploration", direction="bearish"),  # ONGC-like
        _ctx("oil_gas", "refining_marketing"),                          # BPCL-like
        _ctx("chemicals", "paints"),                                    # Asian Paints-like
        _ctx("railways_transport", "aviation"),                         # IndiGo-like
        _ctx("it", "it_services_large_cap"),                            # no section -> fallback
    ]
    assigned, unmatched = assign_to_template(layers, contexts)
    assert assigned == {0: [0], 1: [1], 2: [2], 3: [3]}
    assert unmatched == [4]


def test_macro_template_keeps_banks_and_nbfcs_in_one_direct_layer():
    layers = template_layers_for("repo_rate_change")
    contexts = [
        _ctx("banking", "private_bank", direction="bullish", impact_level="direct"),
        _ctx("banking", "nbfc", direction="bearish", impact_level="direct"),
        _ctx("construction_realestate", "residential_developer", direction="bearish"),
        _ctx("fmcg", "staples_food", direction="bullish"),
    ]
    assigned, unmatched = assign_to_template(layers, contexts)
    # Banks AND NBFCs land in the same first layer (spec §5 B: "same
    # layer, opposite directions"); its title is fixed.
    assert assigned[0] == [0, 1]
    assert layers[0].fixed_title == "Direct — banks vs NBFCs"
    assert assigned[1] == [2]
    assert assigned[3] == [3]  # defensive rotation
    assert layers[3].fixed_title == "Defensive rotation"
    assert unmatched == []


def test_supply_chain_template_covers_protected_exposed_supplier_substitute():
    layers = template_layers_for("trade_policy")
    contexts = [
        _ctx("metals", "steel", direction="bullish", impact_level="direct"),   # protected
        _ctx("auto", "passenger_vehicle", relation="input_cost", direction="bearish"),  # exposed
        _ctx("metals", "mining_coal", relation="supplier", direction="bullish"),  # supplier
        _ctx("metals", "non_ferrous", relation="competitor", direction="bullish"),  # substitute
    ]
    assigned, unmatched = assign_to_template(layers, contexts)
    assert assigned == {0: [0], 1: [1], 2: [2], 3: [3]}
    assert unmatched == []
