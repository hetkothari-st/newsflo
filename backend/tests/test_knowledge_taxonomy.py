"""Blueprint §11/§12/§21: every mechanism carries a controlled relation,
directness, and section label; no raw ids can leak as labels."""
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
