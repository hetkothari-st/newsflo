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
