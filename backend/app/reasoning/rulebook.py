"""Structured financial reasoning rulebook. One data structure (RULES) is the
single source of truth; the prompt text (RULEBOOK_TEXT), the stage-2 sector
digest (RULEBOOK_DIGEST), the chart transmission chains (CHAINS), and the
confidence-engine lookup (get_rule) are all rendered from it -- nothing is
hand-maintained twice. See docs/superpowers/specs/
2026-07-27-structured-rulebook-expansion-design.md.

Each rule has a stable id the analysis model is instructed to cite verbatim
in a company's `evidence_refs` when the rule actually applies -- that
citation is what lets app.reasoning.confidence detect a rulebook match
deterministically, without re-parsing free text. The 9 pre-expansion ids
(RULE_REPO_RATE_CUT etc.) are persisted in production evidence_refs and must
never be renamed.

Deliberately NOT imported here: app.companies.sub_sectors (would create a
reasoning->companies dependency). Branch sub_sector values are validated
against SUB_SECTOR_TAXONOMY by tests/test_rulebook.py instead.
"""

EDGE_RELATIONS = [
    "input_cost", "credit_cost", "demand", "supplier", "customer",
    "competitor", "commodity", "regulation", "currency", "correlation",
]
NODE_MECHANISM = "mechanism"
NODE_SECTOR = "sector"

# Event types whose news is company-specific by nature: no fixed
# transmission chain exists (the graph for these is built purely from the
# LLM cascade's own per-company parent edges), and get_chain returns None.
CHAIN_EXCLUDED_EVENT_TYPES = frozenset({
    "earnings", "merger_acquisition", "banking_metrics",
    "order_win_contract", "corporate_action", "other",
})


def _b(sector, sub_sector, direction, relation, mechanism, *,
       order=1, condition=None, via=None, parent_sector=None):
    """One rule branch: this news moves `sector` (optionally narrowed to
    `sub_sector`) in `direction` because `mechanism`. order=2 marks a
    second-order ripple (must name `via`; may name `parent_sector` for the
    chart edge). `condition` states when the branch applies at all."""
    return {
        "sector": sector, "sub_sector": sub_sector, "direction": direction,
        "relation": relation, "mechanism": mechanism, "order": order,
        "condition": condition, "via": via, "parent_sector": parent_sector,
    }


def _rule(trigger, event_type, branches, *, label=None, caveats=None):
    return {
        "trigger": trigger, "event_type": event_type, "branches": branches,
        "label": label, "caveats": caveats,
    }


RULES: dict[str, dict] = {
    # ------------------------------------------------------------------
    # Macro -- interest rates
    # ------------------------------------------------------------------
    "RULE_REPO_RATE_CUT": _rule(
        "RBI cuts the repo rate (or clearly signals imminent easing)",
        "repo_rate_change",
        [
            _b("banking", "private_bank", "bullish", "credit_cost",
               "Cheaper funding lifts loan demand, and private banks convert rate cycles into loan growth fastest"),
            _b("banking", "housing_finance", "bullish", "credit_cost",
               "Home-loan EMIs fall, so more households can afford mortgages and volumes rise"),
            _b("banking", "nbfc", "bullish", "credit_cost",
               "NBFCs borrow wholesale, so their funding costs drop quickly while lending rates fall slower, widening their margin"),
            _b("construction_realestate", "residential_developer", "bullish", "demand",
               "Cheaper mortgages improve affordability, lifting new-home bookings"),
            _b("auto", None, "bullish", "demand",
               "Most vehicles in India are bought on loans -- lower EMIs lift showroom demand"),
            _b("consumer_durables", None, "bullish", "demand",
               "Appliances and electronics are widely bought on financing -- cheaper EMIs lift volumes"),
            _b("infra", "cement", "bullish", "demand", order=2, via="housing construction",
               parent_sector="construction_realestate",
               mechanism="More housing starts consume more cement"),
            _b("metals", "steel", "bullish", "demand", order=2, via="construction demand",
               parent_sector="construction_realestate",
               mechanism="Housing and project construction consume more steel"),
        ],
        label="Repo Rate ↓",
        caveats=("A bank's own lending margin can shrink if its loan rates fall faster than its deposit "
                 "costs -- the direction for a specific bank depends on its deposit mix"),
    ),
    "RULE_REPO_RATE_HIKE": _rule(
        "RBI hikes the repo rate (or signals further tightening)",
        "repo_rate_change",
        [
            _b("banking", "housing_finance", "bearish", "credit_cost",
               "Higher EMIs price marginal home buyers out, slowing loan growth"),
            _b("banking", "nbfc", "bearish", "credit_cost",
               "NBFCs fund themselves wholesale -- their borrowing costs jump immediately while loan books reprice slowly"),
            _b("construction_realestate", "residential_developer", "bearish", "demand",
               "Costlier mortgages hurt affordability and delay purchase decisions"),
            _b("auto", None, "bearish", "demand",
               "Higher loan EMIs make cars and two-wheelers more expensive to own, cutting demand"),
            _b("consumer_durables", None, "bearish", "demand",
               "Financed purchases of appliances and electronics fall as EMIs rise"),
            _b("infra", "cement", "bearish", "demand", order=2, via="housing slowdown",
               parent_sector="construction_realestate",
               mechanism="Fewer housing starts mean less cement demand"),
        ],
        label="Repo Rate ↑",
        caveats=("Banks with a large share of low-cost current/savings deposits can gain initially -- their "
                 "lending rates rise faster than their deposit costs"),
    ),
    # ------------------------------------------------------------------
    # Macro -- inflation, growth, fiscal, monsoon: added in Task 4
    # ------------------------------------------------------------------
    "RULE_INFLATION_RISE": _rule(
        "CPI/WPI inflation comes in higher than expected or accelerates",
        "inflation",
        [
            _b("fmcg", None, "bearish", "input_cost",
               "Households cut back discretionary purchases, and rising input costs squeeze margins where price hikes lag"),
            _b("consumer_durables", None, "bearish", "demand",
               "Big-ticket discretionary purchases are the first thing households postpone when budgets tighten"),
            _b("metals", None, "bullish", "commodity",
               "Commodity producers sell their output at the higher prices driving the inflation"),
            _b("banking", None, "bearish", "credit_cost", order=2, via="RBI rate-hike response",
               mechanism="Persistent inflation raises the odds of RBI hikes, which slow loan growth"),
        ],
        label="Inflation ↑",
        caveats="Companies with strong pricing power pass costs through and are hurt far less",
    ),
    "RULE_CRUDE_OIL_UP": _rule(
        "Crude (Brent/WTI) rises materially -- a sustained >3-5% move or a supply-shock headline",
        "crude_oil",
        [
            _b("oil_gas", "upstream_exploration", "bullish", "commodity",
               "Producers sell each barrel at the higher price -- revenue flows straight through"),
            _b("oil_gas", "refining_marketing", "bearish", "input_cost",
               condition="pass-through to pump prices is politically restricted",
               mechanism="Fuel retailers pay more for crude but cannot fully raise pump prices, squeezing marketing margins"),
            _b("railways_transport", "aviation", "bearish", "input_cost",
               "Jet fuel is roughly 40% of an airline's operating cost -- fares cannot rise fast enough to cover a spike"),
            _b("chemicals", "paints", "bearish", "input_cost",
               "Crude derivatives are the main raw material for paints -- costs rise ahead of any price hikes"),
            _b("chemicals", None, "bearish", "input_cost",
               "Petrochemical feedstock costs rise across the chemicals chain"),
            _b("fmcg", None, "bearish", "input_cost", order=2, via="packaging and freight",
               mechanism="Packaging plastics and freight both track crude, squeezing consumer-goods margins"),
        ],
        label="Crude Oil ↑",
        caveats=("Always verify which role a company actually plays -- upstream producer, refiner, or fuel "
                 "retailer -- before applying this; they move differently on the same crude move"),
    ),
    "RULE_CURRENCY_INR_WEAKENS": _rule(
        "The rupee weakens materially against the dollar",
        "currency_move",
        [
            _b("it", None, "bullish", "currency",
               "IT firms bill clients in dollars but pay salaries in rupees -- each dollar of revenue converts to more rupees"),
            _b("pharma", "generics_formulations", "bullish", "currency",
               "US generics sales are dollar-denominated -- rupee revenue and margins improve"),
            _b("textiles", "apparel_garments", "bullish", "currency",
               "A weaker rupee makes Indian garment exports more price-competitive abroad"),
            _b("oil_gas", "refining_marketing", "bearish", "currency",
               "Crude imports are priced in dollars -- the same barrel costs more rupees"),
            _b("railways_transport", "aviation", "bearish", "currency",
               "Fuel, aircraft leases, and maintenance are dollar costs while ticket revenue is mostly rupees"),
            _b("consumer_durables", None, "bearish", "currency",
               "Imported components and finished electronics cost more in rupee terms"),
        ],
        label="INR ↓",
        caveats="Companies with large hedges or natural dollar costs are less affected either way",
    ),
    "RULE_GOVERNMENT_CAPEX": _rule(
        "Government announces or accelerates infrastructure capital spending",
        "government_spending",
        [
            _b("infra", "construction_engineering", "bullish", "demand",
               "Engineering and construction contractors win the project orders directly"),
            _b("infra", "capital_goods", "bullish", "demand",
               "Projects need machinery and equipment, filling capital-goods order books"),
            _b("infra", "cement", "bullish", "demand",
               "Roads, bridges, and buildings consume cement in volume"),
            _b("metals", "steel", "bullish", "demand", order=2, via="project materials",
               parent_sector="infra",
               mechanism="Infrastructure projects consume steel by the tonne"),
            _b("railways_transport", "logistics_roadways", "bullish", "demand", order=2,
               via="materials movement", parent_sector="metals",
               mechanism="Moving cement and steel to project sites lifts freight volumes"),
        ],
        label="Govt Capex ↑",
        caveats="Order-to-revenue lag is long -- winners book revenue over years, not the next quarter",
    ),
    # ------------------------------------------------------------------
    # Company-scoped rules (no fixed sector branches -- reasoning guidance
    # only; excluded from chains and the stage-2 digest)
    # ------------------------------------------------------------------
    "RULE_EARNINGS": _rule(
        "A company reports quarterly results or revises guidance",
        "earnings",
        [],
        caveats=("Direct impact on the reporting company first. Only reason about competitors with specific "
                 "evidence -- do not assume a peer moves the same way. Always consider revenue, margins, "
                 "guidance, order book, and cash flow -- not just the headline beat/miss number"),
    ),
    "RULE_MERGER_ACQUISITION": _rule(
        "A merger, acquisition, or major stake purchase is announced",
        "merger_acquisition",
        [],
        caveats=("Evaluate acquirer, target, competitors, suppliers, customers, and regulatory risk "
                 "separately. Do not assume a merger is automatically positive for the acquirer -- "
                 "integration risk and overpayment risk cut against that"),
    ),
    "RULE_BANKING_METRICS": _rule(
        "A bank or lender reports operating metrics",
        "banking_metrics",
        [],
        caveats=("Banking metrics (credit growth, deposit growth, CASA, NIM, asset quality, capital "
                 "adequacy) must each be evaluated independently -- a strong low-cost deposit base does "
                 "not imply clean loans, and vice versa"),
    ),
}


# ---------------------------------------------------------------------------
# Rendering -- everything below derives from RULES; never hand-edit output.
# ---------------------------------------------------------------------------

def _target_label(b):
    return b["sector"] if b["sub_sector"] is None else f"{b['sector']}/{b['sub_sector']}"


def _branch_prose(b):
    text = f"{_target_label(b)} {b['direction']}: {b['mechanism']}"
    if b["condition"]:
        text += f" (only if {b['condition']})"
    return text


def _render_rule(rule):
    parts = [f"Trigger: {rule['trigger']}."]
    first = [b for b in rule["branches"] if b["order"] == 1]
    second = [b for b in rule["branches"] if b["order"] == 2]
    if first:
        parts.append("First-order: " + " | ".join(_branch_prose(b) for b in first) + ".")
    if second:
        parts.append("Second-order: " + " | ".join(
            f"via {b['via']} -> {_branch_prose(b)}" for b in second) + ".")
    if rule["caveats"]:
        parts.append(f"Caveat: {rule['caveats']}.")
    return " ".join(parts)


_RENDERED: dict[str, str] = {rule_id: _render_rule(rule) for rule_id, rule in RULES.items()}

RULEBOOK_TEXT = "\n".join(f"- {rule_id}: {text}" for rule_id, text in _RENDERED.items())


def get_rule(rule_id: str) -> str | None:
    """Rendered prose for a rule id -- used by app.reasoning.confidence via
    pipeline.py to detect whether a company's evidence_refs cite a real,
    known rule (vs. an unsupported claim)."""
    return _RENDERED.get(rule_id)


def _render_digest_line(rule_id, rule):
    bulls = [_target_label(b) for b in rule["branches"] if b["direction"] == "bullish"]
    bears = [_target_label(b) for b in rule["branches"] if b["direction"] == "bearish"]
    sides = []
    if bulls:
        sides.append("bullish: " + ", ".join(bulls))
    if bears:
        sides.append("bearish: " + ", ".join(bears))
    return f"- {rule_id}: {rule['trigger']} -> " + "; ".join(sides)


# Stage-2 sector-identification digest: only rules with sector branches --
# company-scoped rules carry no sector fan-out signal.
RULEBOOK_DIGEST = "\n".join(
    _render_digest_line(rule_id, rule)
    for rule_id, rule in RULES.items() if rule["branches"]
)


def _mech(label):
    return {"kind": NODE_MECHANISM, "label": label}


def _sector(label):
    return {"kind": NODE_SECTOR, "label": label}


def _build_chains() -> dict[str, list[dict]]:
    """CHAINS[event_type] -> chart edges, derived from the FIRST rule
    declared for each chain-bearing event_type (the canonical directional
    variant -- e.g. repo_rate_change renders the CUT rule's chain; the LLM
    verify step in cascade._generate_edges prunes edges a specific article
    contradicts). Sub-sector branches within one sector collapse to a single
    sector node (the chart stays sector-level); when collapsed branches
    disagree on direction, the first-declared branch wins the edge and the
    note flags the mix."""
    chains: dict[str, list[dict]] = {}
    for rule in RULES.values():
        event_type = rule["event_type"]
        if event_type in CHAIN_EXCLUDED_EVENT_TYPES or not rule["branches"] or event_type in chains:
            continue
        edges: list[dict] = []
        edge_by_sector: dict[str, dict] = {}
        mixed: set[str] = set()
        for b in rule["branches"]:
            existing = edge_by_sector.get(b["sector"])
            if existing is not None:
                if existing["direction"] != b["direction"]:
                    mixed.add(b["sector"])
                continue
            frm = _sector(b["parent_sector"]) if b["parent_sector"] else _mech(rule["label"])
            note = b["mechanism"]
            if b["condition"]:
                note += f" (only if {b['condition']})"
            edge = {
                "from": frm, "to": _sector(b["sector"]), "relation": b["relation"],
                "direction": b["direction"], "note": note,
            }
            edges.append(edge)
            edge_by_sector[b["sector"]] = edge
        for sector_label in mixed:
            edge_by_sector[sector_label]["note"] += (
                " (mixed within sector -- sub-sectors diverge, see rule text)"
            )
        chains[event_type] = edges
    return chains


CHAINS: dict[str, list[dict]] = _build_chains()


def get_chain(event_type: str | None) -> list[dict] | None:
    return CHAINS.get(event_type) if event_type else None


CHAINS_TEXT = "\n".join(
    f"- {et}: " + " ; ".join(
        f'{e["from"]["label"]} -[{e["relation"]}]-> {e["to"]["label"]} ({e["direction"]})'
        for e in edges
    )
    for et, edges in CHAINS.items()
)
