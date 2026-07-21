"""Deterministic financial reasoning rules injected into the analysis prompt
as static reference context. All rules are always present in the prompt
(not selected per-article) -- the content is compact enough that always-on
beats building event-classification infrastructure to select a subset. See
docs/superpowers/specs/2026-07-15-reasoning-engine-upgrade-design.md and the
"Deviation from the design spec" note in this plan's implementation doc.

Each rule has a stable id the analysis model is instructed to cite verbatim
in a company's `evidence_refs` when the rule actually applies -- that
citation is what lets app.reasoning.confidence detect a rulebook match
deterministically, without re-parsing free text.
"""

RULES: dict[str, str] = {
    "RULE_REPO_RATE_CUT": (
        "Repo rate cut: borrowing costs decrease, credit demand may increase. "
        "Likely positive: private banks, housing finance, real estate, consumer "
        "lending, auto financing. Risks: margin compression, deposit repricing, "
        "inflation persistence. Second-order: housing up -> cement up -> steel "
        "up -> construction up."
    ),
    "RULE_REPO_RATE_HIKE": (
        "Repo rate hike: credit demand weakens, borrowing becomes more "
        "expensive. Likely negative: banks (loan growth), housing, auto "
        "demand, consumer discretionary. Potential positive: deposit growth, "
        "net interest margins (context dependent)."
    ),
    "RULE_INFLATION_RISE": (
        "Higher inflation: consumer spending pressure, margin compression, "
        "rate hike probability increases. Beneficiaries may include commodity "
        "producers and select energy companies. Losers may include consumer "
        "discretionary and other rate-sensitive sectors."
    ),
    "RULE_CRUDE_OIL_UP": (
        "Oil price increase: beneficiaries are upstream producers and oil "
        "exploration companies. Potentially negative: airlines, paints, "
        "chemicals, logistics, fuel-intensive manufacturing. Always verify "
        "which specific role a company plays (upstream vs refiner vs "
        "distributor) before applying this -- do not assume every company in "
        "the sector plays the same role."
    ),
    "RULE_CURRENCY_INR_WEAKENS": (
        "INR weakens: possible beneficiaries are IT exporters and pharma "
        "exporters. Potentially negative: heavy importers and oil marketing "
        "companies. INR strengthens: generally the opposite effects."
    ),
    "RULE_GOVERNMENT_CAPEX": (
        "Infrastructure capex increase: likely beneficiaries are cement, "
        "steel, EPC, capital goods, and infrastructure developers. "
        "Propagation: government spending -> projects -> materials -> "
        "logistics."
    ),
    "RULE_EARNINGS": (
        "Earnings beat/miss: direct impact on the reporting company first. "
        "Only reason about competitors if there is specific evidence for "
        "them -- do not assume a peer moves the same way. Always consider "
        "revenue, margins, guidance, order book, and cash flow -- not just "
        "the headline beat/miss number."
    ),
    "RULE_MERGER_ACQUISITION": (
        "Mergers/acquisitions: evaluate acquirer, target, competitors, "
        "suppliers, customers, and regulatory risk separately. Do not assume "
        "a merger is automatically positive for the acquirer -- integration "
        "risk and overpayment risk cut against that."
    ),
    "RULE_BANKING_METRICS": (
        "Banking-specific metrics (credit growth, deposit growth, CASA, NIM, "
        "asset quality, capital adequacy) must be evaluated independently of "
        "each other -- a strong CASA franchise does not imply strong asset "
        "quality, and vice versa."
    ),
}

RULEBOOK_TEXT = "\n".join(f"- {rule_id}: {text}" for rule_id, text in RULES.items())


def get_rule(rule_id: str) -> str | None:
    """Look up a rule's text by its stable id -- used by
    app.reasoning.confidence to detect whether a company's evidence_refs cite
    a real, known rule (vs. an unsupported claim)."""
    return RULES.get(rule_id)


# Structured transmission chains derived from the prose RULES above, for the
# sector-cascade graph (see docs/superpowers/plans/2026-07-21-impact-charts-
# phase1-reliability.md and the Phase 2+ plans that follow it). Every edge
# below is traced to the literal wording of its source RULES entry -- see
# each edge's `note` and the comment above each chain. Pure data: nothing in
# the live pipeline consumes CHAINS/get_chain yet (that's Phase 3).
EDGE_RELATIONS = [
    "input_cost", "credit_cost", "demand", "supplier", "customer",
    "competitor", "commodity", "regulation", "currency", "correlation",
]
NODE_MECHANISM = "mechanism"
NODE_SECTOR = "sector"


def _mech(label: str) -> dict:
    return {"kind": NODE_MECHANISM, "label": label}


def _sector(label: str) -> dict:
    return {"kind": NODE_SECTOR, "label": label}


# From RULE_REPO_RATE_CUT: "Repo rate cut: borrowing costs decrease, credit
# demand may increase. Likely positive: private banks, housing finance, real
# estate, consumer lending, auto financing. ... Second-order: housing up ->
# cement up -> steel up -> construction up." NOTE: this chain is derived
# ONLY from the CUT rule (bullish-framed) -- a real repo rate HIKE would need
# the opposite directions, which this fixed-per-event_type structure cannot
# represent. See this plan's Global Constraints.
_REPO_RATE_CHANGE_CHAIN = [
    {
        "from": _mech("Repo Rate ↓"), "to": _mech("Borrowing Costs ↓"),
        "relation": "credit_cost", "direction": "bullish",
        "note": "A repo rate cut mechanically lowers the cost of new borrowing.",
    },
    {
        "from": _mech("Borrowing Costs ↓"), "to": _sector("banking"),
        "relation": "credit_cost", "direction": "bullish",
        "note": "Lower rates raise credit demand for private banks and housing finance.",
    },
    {
        "from": _mech("Borrowing Costs ↓"), "to": _sector("construction_realestate"),
        "relation": "credit_cost", "direction": "bullish",
        "note": "Cheaper mortgages and home loans lift real estate demand.",
    },
    {
        "from": _mech("Borrowing Costs ↓"), "to": _sector("auto"),
        "relation": "credit_cost", "direction": "bullish",
        "note": "Cheaper auto financing lifts vehicle demand.",
    },
    {
        "from": _sector("construction_realestate"), "to": _sector("infra"),
        "relation": "demand", "direction": "bullish",
        "note": "Housing demand up drives construction/EPC activity (rule's second-order chain: housing -> cement -> steel -> construction).",
    },
    {
        "from": _sector("infra"), "to": _sector("metals"),
        "relation": "demand", "direction": "bullish",
        "note": "Construction activity up drives steel/cement demand (rule's second-order chain).",
    },
]

# From RULE_CRUDE_OIL_UP: "Oil price increase: beneficiaries are upstream
# producers and oil exploration companies. Potentially negative: airlines,
# paints, chemicals, logistics, fuel-intensive manufacturing." "Fuel-
# intensive manufacturing" is too generic to license naming a specific
# sector without guessing -- intentionally NOT mapped to auto or fmcg (see
# this plan's Global Constraints for why).
_CRUDE_OIL_CHAIN = [
    {
        "from": _mech("Crude Oil ↑"), "to": _sector("oil_gas"),
        "relation": "commodity", "direction": "bullish",
        "note": "Upstream producers and exploration companies benefit from higher crude prices -- refiners/marketers within oil_gas may not; verify the specific company's role at the company stage.",
    },
    {
        "from": _mech("Crude Oil ↑"), "to": _sector("railways_transport"),
        "relation": "input_cost", "direction": "bearish",
        "note": "Higher fuel costs hit airlines and logistics operators directly.",
    },
    {
        "from": _mech("Crude Oil ↑"), "to": _sector("chemicals"),
        "relation": "input_cost", "direction": "bearish",
        "note": "Crude is a feedstock for paints and chemicals manufacturing.",
    },
]

# From RULE_GOVERNMENT_CAPEX: "Infrastructure capex increase: likely
# beneficiaries are cement, steel, EPC, capital goods, and infrastructure
# developers. Propagation: government spending -> projects -> materials ->
# logistics."
_GOVERNMENT_SPENDING_CHAIN = [
    {
        "from": _mech("Govt Capex ↑"), "to": _sector("infra"),
        "relation": "demand", "direction": "bullish",
        "note": "Infrastructure capex directly benefits EPC, capital goods, and infrastructure developers.",
    },
    {
        "from": _sector("infra"), "to": _sector("metals"),
        "relation": "demand", "direction": "bullish",
        "note": "Infrastructure projects consume steel and cement (rule's propagation: projects -> materials).",
    },
    {
        "from": _sector("metals"), "to": _sector("railways_transport"),
        "relation": "demand", "direction": "bullish",
        "note": "Materials shipments drive logistics volumes (rule's propagation: materials -> logistics).",
    },
]

# From RULE_CURRENCY_INR_WEAKENS: "INR weakens: possible beneficiaries are IT
# exporters and pharma exporters. Potentially negative: heavy importers and
# oil marketing companies."
_CURRENCY_MOVE_CHAIN = [
    {
        "from": _mech("INR ↓"), "to": _sector("it"),
        "relation": "currency", "direction": "bullish",
        "note": "A weaker rupee raises the rupee value of dollar-denominated IT export revenue.",
    },
    {
        "from": _mech("INR ↓"), "to": _sector("pharma"),
        "relation": "currency", "direction": "bullish",
        "note": "A weaker rupee raises the rupee value of dollar-denominated pharma export revenue.",
    },
    {
        "from": _mech("INR ↓"), "to": _sector("oil_gas"),
        "relation": "currency", "direction": "bearish",
        "note": "Oil marketing companies pay more rupees for dollar-priced crude imports.",
    },
    {
        "from": _mech("INR ↓"), "to": _sector("consumer_durables"),
        "relation": "currency", "direction": "bearish",
        "note": "Heavy importers of components and finished electronics pay more in rupee terms.",
    },
]

# From RULE_INFLATION_RISE: "Higher inflation: consumer spending pressure,
# margin compression, rate hike probability increases. Beneficiaries may
# include commodity producers and select energy companies. Losers may
# include consumer discretionary and other rate-sensitive sectors."
_INFLATION_CHAIN = [
    {
        "from": _mech("Inflation ↑"), "to": _sector("fmcg"),
        "relation": "input_cost", "direction": "bearish",
        "note": "Consumer spending pressure and margin compression hit FMCG/discretionary demand.",
    },
    {
        "from": _mech("Inflation ↑"), "to": _sector("consumer_durables"),
        "relation": "input_cost", "direction": "bearish",
        "note": "Consumer spending pressure hits rate-sensitive discretionary durables demand.",
    },
    {
        "from": _mech("Inflation ↑"), "to": _sector("metals"),
        "relation": "commodity", "direction": "bullish",
        "note": "Commodity producers benefit from rising prices.",
    },
]

# CHAINS[event_type] -> ordered list of edges (see each _*_CHAIN's own
# comment above for its source RULES entry). event_type values not present
# here (earnings, merger_acquisition, banking_metrics, other) are
# intentionally absent -- see RULE_EARNINGS/RULE_MERGER_ACQUISITION/
# RULE_BANKING_METRICS: these are company-specific by nature (get_chain
# returns None for them), and the graph for these events is built purely
# from the LLM cascade's own per-company parent edges (Phase 3+), not a
# rulebook chain. That is correct, not a gap.
CHAINS: dict[str, list[dict]] = {
    "repo_rate_change": _REPO_RATE_CHANGE_CHAIN,
    "crude_oil": _CRUDE_OIL_CHAIN,
    "government_spending": _GOVERNMENT_SPENDING_CHAIN,
    "currency_move": _CURRENCY_MOVE_CHAIN,
    "inflation": _INFLATION_CHAIN,
}


def get_chain(event_type: str | None) -> list[dict] | None:
    return CHAINS.get(event_type) if event_type else None


CHAINS_TEXT = "\n".join(
    f"- {et}: " + " ; ".join(
        f'{e["from"]["label"]} -[{e["relation"]}]-> {e["to"]["label"]} ({e["direction"]})'
        for e in edges
    )
    for et, edges in CHAINS.items()
)
