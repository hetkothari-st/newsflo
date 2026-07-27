# Structured Rulebook Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the 9-rule prose rulebook into ~40 structured rules with sub-sector branches, auto-generating the prompt text, chart chains, stage-2 digest, and confidence lookup from one data structure.

**Architecture:** `rulebook.py` becomes structured data (`RULES: dict[str, dict]` with trigger/event_type/branches) plus pure rendering functions. `RULEBOOK_TEXT`, `RULEBOOK_DIGEST`, `CHAINS`, and `get_rule` are all derived — no hand-maintained duplicates. Taxonomy (`sub_sectors.py`) extends to all 17 sectors first so rule branches validate against it. Cascade stage 3 keeps the full rulebook; stage 2 gains a compact digest.

**Tech Stack:** Python 3.11, FastAPI backend, pytest. Pure static data + pure functions — no DB, no network in any of the touched reasoning modules.

**Spec:** `docs/superpowers/specs/2026-07-27-structured-rulebook-expansion-design.md`

## Global Constraints

- **NEVER `git push`.** Commit locally only — multiple concurrent sessions share origin/master (Railway auto-deploys). The user pushes.
- Never rename the 9 existing rule ids (`RULE_REPO_RATE_CUT`, `RULE_REPO_RATE_HIKE`, `RULE_INFLATION_RISE`, `RULE_CRUDE_OIL_UP`, `RULE_CURRENCY_INR_WEAKENS`, `RULE_GOVERNMENT_CAPEX`, `RULE_EARNINGS`, `RULE_MERGER_ACQUISITION`, `RULE_BANKING_METRICS`) — persisted `evidence_refs` in production cite them.
- Never remove or rename existing exports of `app.reasoning.rulebook`: `RULES`, `RULEBOOK_TEXT`, `CHAINS`, `CHAINS_TEXT`, `EDGE_RELATIONS`, `NODE_MECHANISM`, `NODE_SECTOR`, `get_rule`, `get_chain` — `cascade.py`, `pipeline.py`, and tests import them.
- `get_rule(rule_id)` keeps returning `str | None` (rendered prose). `pipeline.py:216` depends on non-None meaning "known rule".
- Chart chain edges keep the exact shape `{"from": {"kind","label"}, "to": {"kind","label"}, "relation", "direction", "note"}` with kinds `mechanism|sector`, relations from `EDGE_RELATIONS`, directions `bullish|bearish`, non-empty notes.
- Mechanism sentences: plain language, causal, no finance jargon without unpacking (per 2026-07-15 spec follow-ups: "causal" and "plain-language" are independent axes, both required).
- All sub_sector values must exist in `SUB_SECTOR_TAXONOMY[sector]`; all sectors in `SECTORS`; enforcement via tests, not import-time asserts.
- Run tests from `backend/`: `python -m pytest tests/ -q` (full) or targeted files.
- Cascade stages 5/7 get NO rulebook content (production incident: prompt overweight → degenerate empty tool calls).

---

### Task 1: Sub-sector taxonomy extension to all 17 sectors

**Files:**
- Modify: `backend/app/companies/sub_sectors.py` (extend `SUB_SECTOR_TAXONOMY` + `SUB_SECTOR_DEFINITIONS`)
- Test: `backend/tests/test_sub_sectors.py`

**Interfaces:**
- Produces: `SUB_SECTOR_TAXONOMY` entries for `railways_transport`, `construction_realestate`, `defense`, `agriculture`, `consumer_durables`, `media_entertainment`, `chemicals`, `textiles`. Task 3+ rule branches validate against these exact strings.

- [ ] **Step 1: Read current test file**

Read `backend/tests/test_sub_sectors.py` fully to see existing invariant tests (every sector's list ends with `<sector>_other`, definitions cover every sector, etc.) so additions follow the same pattern.

- [ ] **Step 2: Write failing test**

Add to `backend/tests/test_sub_sectors.py`:

```python
def test_taxonomy_covers_every_sector_except_other():
    from app.analysis.schemas import SECTORS
    from app.companies.sub_sectors import SUB_SECTOR_TAXONOMY
    expected = set(SECTORS) - {"other"}
    assert set(SUB_SECTOR_TAXONOMY) == expected
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_sub_sectors.py::test_taxonomy_covers_every_sector_except_other -v`
Expected: FAIL — 8 sectors missing.

- [ ] **Step 4: Extend taxonomy + definitions**

Append to `SUB_SECTOR_TAXONOMY` in `backend/app/companies/sub_sectors.py`:

```python
    "railways_transport": [
        "aviation", "ports_shipping", "logistics_roadways", "rail_equipment", "transport_other",
    ],
    "construction_realestate": [
        "residential_developer", "commercial_reit", "realestate_other",
    ],
    "defense": [
        "defense_platforms", "defense_electronics", "shipyard", "defense_other",
    ],
    "agriculture": [
        "fertilizers", "agrochemicals", "seeds_agri_inputs", "agri_other",
    ],
    "consumer_durables": [
        "appliances_electronics", "wires_cables", "durables_other",
    ],
    "media_entertainment": [
        "broadcast_tv", "multiplex_film", "digital_gaming", "media_other",
    ],
    "chemicals": [
        "specialty_chemicals", "commodity_chemicals", "paints", "chemicals_other",
    ],
    "textiles": [
        "apparel_garments", "yarn_fabric", "textiles_other",
    ],
```

Append matching `SUB_SECTOR_DEFINITIONS` entries (same terse style as existing):

```python
    "railways_transport": (
        "- aviation: airlines and airport operators.\n"
        "- ports_shipping: port operators and shipping lines.\n"
        "- logistics_roadways: road logistics, warehousing, and express delivery.\n"
        "- rail_equipment: rail wagon/locomotive/component manufacturers.\n"
        "- transport_other: none of the above cleanly."
    ),
    "construction_realestate": (
        "- residential_developer: housing-focused property developers.\n"
        "- commercial_reit: office/mall developers and REITs.\n"
        "- realestate_other: none of the above cleanly."
    ),
    "defense": (
        "- defense_platforms: aircraft/missile/vehicle platform manufacturers.\n"
        "- defense_electronics: radar, avionics, and defense electronics makers.\n"
        "- shipyard: naval and commercial shipbuilders.\n"
        "- defense_other: none of the above cleanly."
    ),
    "agriculture": (
        "- fertilizers: urea/NPK/phosphate fertilizer producers.\n"
        "- agrochemicals: pesticide/herbicide/crop-protection makers.\n"
        "- seeds_agri_inputs: seed companies and other farm-input suppliers.\n"
        "- agri_other: none of the above cleanly."
    ),
    "consumer_durables": (
        "- appliances_electronics: appliance and consumer-electronics manufacturers.\n"
        "- wires_cables: wires, cables, and electrical-accessories makers.\n"
        "- durables_other: none of the above cleanly."
    ),
    "media_entertainment": (
        "- broadcast_tv: TV broadcasters and content networks.\n"
        "- multiplex_film: cinema chains and film production companies.\n"
        "- digital_gaming: digital media, OTT, and gaming companies.\n"
        "- media_other: none of the above cleanly."
    ),
    "chemicals": (
        "- specialty_chemicals: high-value niche chemical manufacturers.\n"
        "- commodity_chemicals: bulk/basic chemical producers.\n"
        "- paints: paint and coatings manufacturers.\n"
        "- chemicals_other: none of the above cleanly."
    ),
    "textiles": (
        "- apparel_garments: garment and apparel makers/brands.\n"
        "- yarn_fabric: spinning, yarn, and fabric manufacturers.\n"
        "- textiles_other: none of the above cleanly."
    ),
```

- [ ] **Step 5: Run full sub_sectors test file**

Run: `python -m pytest tests/test_sub_sectors.py -v`
Expected: ALL PASS (existing invariant tests should automatically cover the new sectors; if any existing test hardcodes the old 9-sector set, update it to derive from `SECTORS`).

- [ ] **Step 6: Commit**

```bash
git add app/companies/sub_sectors.py tests/test_sub_sectors.py
git commit -m "feat: extend sub-sector taxonomy to all 17 sectors"
```

---

### Task 2: EVENT_TYPES expansion

**Files:**
- Modify: `backend/app/analysis/schemas.py:11-15`
- Test: `backend/tests/test_schemas.py`

**Interfaces:**
- Produces: expanded `EVENT_TYPES` list (22 values). Task 3+ rules reference these exact strings; the stage-1 facts tool enum (`cascade.py:76`) picks them up automatically.

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_schemas.py`:

```python
def test_event_types_expanded_vocabulary():
    from app.analysis.schemas import EVENT_TYPES
    expected = [
        "repo_rate_change", "inflation", "macro_data", "fiscal_policy",
        "monsoon_weather", "crude_oil", "commodity_price", "currency_move",
        "global_rates", "geopolitics", "government_spending", "government_policy",
        "trade_policy", "regulation", "pricing_action", "fii_dii_flows",
        "earnings", "merger_acquisition", "order_win_contract",
        "corporate_action", "banking_metrics", "other",
    ]
    assert EVENT_TYPES == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_schemas.py::test_event_types_expanded_vocabulary -v`
Expected: FAIL — current list has 9 entries.

- [ ] **Step 3: Replace EVENT_TYPES in schemas.py**

```python
# The specific triggering event (stage-1 classification; also keys the
# rulebook's transmission chains). Existing 9 values keep their exact names
# -- persisted Alert.event_type rows cite them.
EVENT_TYPES = [
    "repo_rate_change",      # RBI repo/policy rate decisions
    "inflation",             # CPI/WPI prints and inflation commentary
    "macro_data",            # GDP, IIP, PMI, employment, trade-balance data
    "fiscal_policy",         # budget, fiscal deficit, government borrowing, GST changes
    "monsoon_weather",       # monsoon progress, drought, extreme weather
    "crude_oil",             # crude price moves and oil supply events
    "commodity_price",       # non-crude commodities: gold, metals, coal, agri
    "currency_move",         # INR/USD and other FX moves
    "global_rates",          # Fed/ECB decisions, global risk-on/risk-off
    "geopolitics",           # war, sanctions, cross-border conflict
    "government_spending",   # infra capex, defense procurement, public projects
    "government_policy",     # PLI schemes, subsidies, sector programs
    "trade_policy",          # import/export duties, FTAs, export bans
    "regulation",            # RBI/SEBI/TRAI/USFDA and sector regulators
    "pricing_action",        # industry-wide price hikes/cuts (telecom tariffs, cement)
    "fii_dii_flows",         # foreign/domestic institutional flow stories
    "earnings",              # results, guidance, and peer demand signals
    "merger_acquisition",
    "order_win_contract",    # large contract/order wins
    "corporate_action",      # buyback, dividend, stake sale, IPO, rating, mgmt change, capacity expansion
    "banking_metrics",
    "other",
]
```

- [ ] **Step 4: Run schema + cascade + pipeline tests**

Run: `python -m pytest tests/test_schemas.py tests/test_cascade.py tests/test_pipeline.py -q`
Expected: PASS (the facts-tool enum derives from `EVENT_TYPES`; if any test hardcodes the old 9-value list, update it to the new list).

- [ ] **Step 5: Commit**

```bash
git add app/analysis/schemas.py tests/test_schemas.py
git commit -m "feat: expand EVENT_TYPES to 22 values for rulebook coverage"
```

---

### Task 3: Structured rule machinery + migrate the existing 9 rules

**Files:**
- Rewrite: `backend/app/reasoning/rulebook.py`
- Rewrite: `backend/tests/test_rulebook.py` (keep existing 4 tests, add structure suite)
- Modify: `backend/tests/test_chains.py` (chain set changes in Task 4-7; here only the derivation must keep the current 5 chains passing)

**Interfaces:**
- Consumes: `SECTORS` from `app.analysis.schemas`, `SUB_SECTOR_TAXONOMY` from `app.companies.sub_sectors` (test-side only — rulebook.py itself must NOT import sub_sectors, avoiding a reasoning→companies dependency; validation lives in tests).
- Produces (all existing exports preserved):
  - `RULES: dict[str, dict]` — structured rules
  - `_b(...)` / branch dicts with keys: `sector, sub_sector, direction, relation, mechanism, order, condition, via, parent_sector`
  - `RULEBOOK_TEXT: str`, `RULEBOOK_DIGEST: str`, `CHAINS: dict`, `CHAINS_TEXT: str`
  - `get_rule(rule_id) -> str | None`, `get_chain(event_type) -> list[dict] | None`
  - `CHAIN_EXCLUDED_EVENT_TYPES: frozenset[str]`

- [ ] **Step 1: Write the new structure test suite**

Replace `backend/tests/test_rulebook.py` with (keeping the 4 existing test behaviors):

```python
from app.analysis.schemas import EVENT_TYPES, SECTORS
from app.companies.sub_sectors import SUB_SECTOR_TAXONOMY
from app.reasoning.rulebook import (
    CHAIN_EXCLUDED_EVENT_TYPES, EDGE_RELATIONS, RULEBOOK_DIGEST, RULEBOOK_TEXT,
    RULES, get_rule,
)


def test_get_rule_returns_text_for_known_id():
    assert get_rule("RULE_REPO_RATE_CUT") is not None
    text = get_rule("RULE_REPO_RATE_CUT").lower()
    assert "bank" in text


def test_get_rule_returns_none_for_unknown_id():
    assert get_rule("RULE_DOES_NOT_EXIST") is None


def test_rule_ids_are_uppercase_with_prefix():
    for rule_id in RULES:
        assert rule_id.startswith("RULE_")
        assert rule_id == rule_id.upper()


def test_rulebook_text_contains_every_rule_id():
    for rule_id in RULES:
        assert rule_id in RULEBOOK_TEXT


def test_legacy_rule_ids_survive():
    # Persisted evidence_refs in production cite these exact ids.
    for rule_id in [
        "RULE_REPO_RATE_CUT", "RULE_REPO_RATE_HIKE", "RULE_INFLATION_RISE",
        "RULE_CRUDE_OIL_UP", "RULE_CURRENCY_INR_WEAKENS", "RULE_GOVERNMENT_CAPEX",
        "RULE_EARNINGS", "RULE_MERGER_ACQUISITION", "RULE_BANKING_METRICS",
    ]:
        assert rule_id in RULES, f"legacy id {rule_id} was renamed or dropped"


def test_every_rule_has_required_fields():
    for rule_id, rule in RULES.items():
        assert rule["trigger"].strip(), rule_id
        assert rule["event_type"] in EVENT_TYPES, f"{rule_id}: bad event_type {rule['event_type']!r}"
        assert isinstance(rule["branches"], list), rule_id
        if rule["branches"]:
            assert rule.get("label"), f"{rule_id}: branch rules need a chart label"


def test_every_branch_is_valid():
    for rule_id, rule in RULES.items():
        for b in rule["branches"]:
            assert b["sector"] in SECTORS, f"{rule_id}: bad sector {b['sector']!r}"
            if b["sub_sector"] is not None:
                assert b["sub_sector"] in SUB_SECTOR_TAXONOMY.get(b["sector"], []), (
                    f"{rule_id}: {b['sub_sector']!r} not in taxonomy for {b['sector']}"
                )
            assert b["direction"] in {"bullish", "bearish"}, rule_id
            assert b["relation"] in EDGE_RELATIONS, f"{rule_id}: bad relation {b['relation']!r}"
            assert b["mechanism"].strip(), f"{rule_id}: empty mechanism"
            assert b["order"] in {1, 2}, rule_id
            if b["order"] == 2:
                assert b["via"], f"{rule_id}: order-2 branch missing via"
            if b["parent_sector"] is not None:
                assert b["parent_sector"] in SECTORS, rule_id


def test_digest_covers_exactly_the_branch_rules():
    for rule_id, rule in RULES.items():
        if rule["branches"]:
            assert rule_id in RULEBOOK_DIGEST, f"{rule_id} missing from digest"
        else:
            assert rule_id not in RULEBOOK_DIGEST, f"company-scoped {rule_id} should not be in digest"


def test_chain_excluded_event_types_are_the_company_scoped_ones():
    assert CHAIN_EXCLUDED_EVENT_TYPES == frozenset({
        "earnings", "merger_acquisition", "banking_metrics",
        "order_win_contract", "corporate_action", "other",
    })


def test_rendered_rule_mentions_condition_and_via():
    # RULE_CRUDE_OIL_UP has a conditional branch and (after Task 5) an
    # order-2 branch -- the rendering must surface both markers.
    text = get_rule("RULE_CRUDE_OIL_UP")
    assert "only if" in text
```

- [ ] **Step 2: Run to verify failures**

Run: `python -m pytest tests/test_rulebook.py -v`
Expected: FAIL — imports (`CHAIN_EXCLUDED_EVENT_TYPES`, `RULEBOOK_DIGEST`) don't exist yet.

- [ ] **Step 3: Rewrite rulebook.py — machinery + 9 migrated rules**

Replace `backend/app/reasoning/rulebook.py` entirely:

```python
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
```

- [ ] **Step 4: Update test_chains.py for the interim chain set**

In `backend/tests/test_chains.py`:
- `test_chains_has_exactly_the_five_broad_mechanism_event_types` → rename to `test_every_chain_event_type_is_chain_bearing` and assert dynamically:

```python
def test_every_chain_event_type_is_chain_bearing():
    from app.reasoning.rulebook import CHAIN_EXCLUDED_EVENT_TYPES
    for event_type in CHAINS:
        assert event_type not in CHAIN_EXCLUDED_EVENT_TYPES
```

- `test_broad_mechanism_event_types_have_a_nonempty_chain` parametrize list stays `["repo_rate_change", "crude_oil", "government_spending", "currency_move", "inflation"]` for now (Tasks 4-7 extend it).
- `test_company_specific_event_types_have_no_chain` parametrize list becomes `["earnings", "merger_acquisition", "banking_metrics", "order_win_contract", "corporate_action", "other"]`.
- All other node/relation/direction/note invariant tests stay unchanged — they iterate `CHAINS` generically.

- [ ] **Step 5: Run rulebook + chains + downstream tests**

Run: `python -m pytest tests/test_rulebook.py tests/test_chains.py tests/test_cascade.py tests/test_pipeline.py tests/test_confidence.py -q`
Expected: ALL PASS. `test_rendered_rule_mentions_condition_and_via` passes because RULE_CRUDE_OIL_UP has a conditional branch.

- [ ] **Step 6: Commit**

```bash
git add app/reasoning/rulebook.py tests/test_rulebook.py tests/test_chains.py
git commit -m "feat: structured rulebook -- one data source renders prompt text, digest, and chains"
```

---

### Task 4: Macro rule catalog (inflation fall, GDP, fiscal, monsoon)

**Files:**
- Modify: `backend/app/reasoning/rulebook.py` (add rules to `RULES`, keeping declaration order: canonical chain rule first per event_type)
- Modify: `backend/tests/test_chains.py` (extend chain-bearing parametrize list)

**Interfaces:**
- Consumes: `_rule`/`_b` helpers from Task 3.
- Produces: rules `RULE_INFLATION_FALL`, `RULE_GDP_GROWTH_STRONG`, `RULE_GDP_GROWTH_WEAK`, `RULE_GST_RATE_CUT`, `RULE_FISCAL_SLIPPAGE`, `RULE_MONSOON_GOOD`, `RULE_MONSOON_DEFICIENT`; chains for `macro_data`, `fiscal_policy`, `monsoon_weather`.

- [ ] **Step 1: Extend chain test first**

In `backend/tests/test_chains.py`, extend the chain-bearing parametrize list:

```python
@pytest.mark.parametrize("event_type", [
    "repo_rate_change", "crude_oil", "government_spending", "currency_move",
    "inflation", "macro_data", "fiscal_policy", "monsoon_weather",
])
```

Run: `python -m pytest tests/test_chains.py -q` — expect 3 new FAILs (no chains for the new event types yet).

- [ ] **Step 2: Add the rules**

Insert into `RULES` (after `RULE_INFLATION_RISE`, before the company-scoped block; GST before fiscal-slippage so GST's consumer chain is `fiscal_policy`'s canonical chart chain):

```python
    "RULE_INFLATION_FALL": _rule(
        "CPI/WPI inflation cools faster than expected",
        "inflation",
        [
            _b("fmcg", None, "bullish", "input_cost",
               "Input costs ease while shelf prices hold, expanding margins; household budgets stretch further"),
            _b("consumer_durables", None, "bullish", "demand",
               "Real purchasing power recovers, and postponed big-ticket purchases come back"),
            _b("banking", None, "bullish", "credit_cost", order=2, via="RBI rate-cut room",
               mechanism="Cooling inflation gives RBI room to cut rates, which revives loan demand"),
        ],
        label="Inflation ↓",
    ),
    "RULE_GDP_GROWTH_STRONG": _rule(
        "GDP, IIP, or PMI data comes in stronger than expected",
        "macro_data",
        [
            _b("banking", None, "bullish", "demand",
               "Credit growth broadly tracks nominal GDP -- faster growth means more borrowing"),
            _b("auto", None, "bullish", "demand",
               "Vehicle sales closely track income growth and business activity"),
            _b("infra", "capital_goods", "bullish", "demand",
               "Companies expand capacity when demand visibility improves, ordering machinery"),
            _b("fmcg", None, "bullish", "demand",
               "Household consumption rises with incomes"),
        ],
        label="GDP Growth ↑",
    ),
    "RULE_GDP_GROWTH_WEAK": _rule(
        "GDP, IIP, or PMI data disappoints or contracts",
        "macro_data",
        [
            _b("banking", None, "bearish", "demand",
               "Loan demand weakens with activity, and bad-loan risk rises in a slowdown"),
            _b("auto", None, "bearish", "demand",
               "Vehicle purchases are postponed first when incomes and business activity soften"),
            _b("infra", "capital_goods", "bearish", "demand",
               "Private capex plans get shelved when demand visibility fades"),
            _b("metals", None, "bearish", "demand",
               "Industrial slowdown cuts steel and metal consumption directly"),
        ],
        label="GDP Growth ↓",
        caveats="Staple consumer goods are defensive -- they fall less than discretionary sectors in a slowdown",
    ),
    "RULE_GST_RATE_CUT": _rule(
        "GST rates are cut on consumer product categories",
        "fiscal_policy",
        [
            _b("auto", None, "bullish", "demand",
               condition="the cut covers vehicles",
               mechanism="A GST cut lowers on-road prices directly, lifting showroom demand"),
            _b("consumer_durables", None, "bullish", "demand",
               condition="the cut covers appliances/electronics",
               mechanism="Lower tax cuts sticker prices, and volumes respond quickly"),
            _b("fmcg", None, "bullish", "demand",
               condition="the cut covers packaged goods",
               mechanism="Lower prices lift volumes; companies often keep part of the cut as margin"),
        ],
        label="GST Cut",
        caveats="A GST hike on the same categories runs each branch in reverse",
    ),
    "RULE_FISCAL_SLIPPAGE": _rule(
        "Fiscal deficit widens beyond target, or government borrowing jumps",
        "fiscal_policy",
        [
            _b("banking", None, "bearish", "correlation",
               "Banks hold large government-bond books -- heavier borrowing pushes yields up, causing mark-to-market losses"),
            _b("infra", None, "bearish", "credit_cost", order=2, via="crowding out",
               mechanism="Heavy government borrowing keeps market interest rates high, raising project funding costs"),
        ],
        label="Fiscal Slippage",
    ),
    "RULE_MONSOON_GOOD": _rule(
        "Monsoon arrives on time / rainfall is normal-to-above-normal",
        "monsoon_weather",
        [
            _b("agriculture", "fertilizers", "bullish", "demand",
               "More sowing means more fertilizer applied per acre and season"),
            _b("agriculture", "agrochemicals", "bullish", "demand",
               "Higher planted acreage lifts crop-protection demand"),
            _b("fmcg", None, "bullish", "demand", order=2, via="rural incomes",
               parent_sector="agriculture",
               mechanism="Good harvests lift rural incomes, and rural India is roughly 35-40% of consumer-goods sales"),
            _b("auto", "two_wheeler", "bullish", "demand", order=2, via="rural incomes",
               parent_sector="agriculture",
               mechanism="Two-wheeler and tractor purchases track rural cash flows"),
        ],
        label="Good Monsoon",
    ),
    "RULE_MONSOON_DEFICIENT": _rule(
        "Monsoon is deficient/delayed, or drought conditions emerge",
        "monsoon_weather",
        [
            _b("agriculture", "fertilizers", "bearish", "demand",
               "Less sowing directly cuts fertilizer volumes"),
            _b("agriculture", "agrochemicals", "bearish", "demand",
               "Lower acreage means less crop protection applied"),
            _b("fmcg", None, "bearish", "demand", order=2, via="rural incomes",
               parent_sector="agriculture",
               mechanism="Weak harvests squeeze rural incomes, hitting consumer-goods volumes"),
            _b("auto", "two_wheeler", "bearish", "demand", order=2, via="rural incomes",
               parent_sector="agriculture",
               mechanism="Rural cash-flow stress hits two-wheeler and tractor sales first"),
        ],
        label="Weak Monsoon",
        caveats="A failed monsoon also stokes food inflation, raising the odds of RBI staying tight for longer",
    ),
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_rulebook.py tests/test_chains.py -q`
Expected: ALL PASS.

- [ ] **Step 4: Commit**

```bash
git add app/reasoning/rulebook.py tests/test_chains.py
git commit -m "feat: macro rule catalog -- inflation, GDP, fiscal, monsoon"
```

---

### Task 5: Commodity + currency/global rule catalog

**Files:**
- Modify: `backend/app/reasoning/rulebook.py`
- Modify: `backend/tests/test_chains.py`

**Interfaces:**
- Consumes: `_rule`/`_b` helpers.
- Produces: `RULE_CRUDE_OIL_DOWN`, `RULE_STEEL_METAL_PRICES_UP`, `RULE_GOLD_PRICE_UP`, `RULE_COAL_FUEL_COST_UP`, `RULE_AGRI_COMMODITY_SPIKE`, `RULE_CURRENCY_INR_STRENGTHENS`, `RULE_GLOBAL_RISK_OFF`, `RULE_GLOBAL_RISK_ON`, `RULE_GEOPOLITICAL_CONFLICT`, `RULE_FII_OUTFLOWS`; chains for `commodity_price`, `global_rates`, `geopolitics`, `fii_dii_flows`.

- [ ] **Step 1: Extend chain test parametrize list** with `"commodity_price", "global_rates", "geopolitics", "fii_dii_flows"`. Run `python -m pytest tests/test_chains.py -q` — expect 4 FAILs.

- [ ] **Step 2: Add the rules**

Insert after `RULE_CRUDE_OIL_UP` (declaration order matters: `RULE_STEEL_METAL_PRICES_UP` must be the first `commodity_price` rule so it defines that chain; `RULE_GLOBAL_RISK_OFF` first for `global_rates`):

```python
    "RULE_CRUDE_OIL_DOWN": _rule(
        "Crude falls materially -- a sustained >3-5% drop or a supply-glut headline",
        "crude_oil",
        [
            _b("oil_gas", "upstream_exploration", "bearish", "commodity",
               "Producers realize less per barrel -- revenue falls directly"),
            _b("oil_gas", "refining_marketing", "bullish", "input_cost",
               "Fuel retailers buy crude cheaper while pump prices lag downward, expanding marketing margins"),
            _b("railways_transport", "aviation", "bullish", "input_cost",
               "Jet fuel -- an airline's biggest cost -- gets cheaper while fares hold"),
            _b("chemicals", "paints", "bullish", "input_cost",
               "Cheaper crude derivatives cut the main raw-material cost for paints"),
            _b("fmcg", None, "bullish", "input_cost", order=2, via="packaging and freight",
               mechanism="Packaging plastics and freight costs ease, helping consumer-goods margins"),
        ],
        label="Crude Oil ↓",
    ),
    "RULE_STEEL_METAL_PRICES_UP": _rule(
        "Steel or base-metal prices rise materially (global or domestic)",
        "commodity_price",
        [
            _b("metals", "steel", "bullish", "commodity",
               "Steelmakers sell at higher prices while costs lag -- margins expand"),
            _b("metals", "non_ferrous", "bullish", "commodity",
               "Aluminium/copper/zinc producers realize higher prices directly"),
            _b("auto", None, "bearish", "input_cost",
               "Steel and aluminium are a vehicle's biggest raw-material costs"),
            _b("infra", "construction_engineering", "bearish", "input_cost",
               "Fixed-price construction contracts absorb higher steel costs as lost margin"),
            _b("consumer_durables", "appliances_electronics", "bearish", "input_cost",
               "Appliances are steel-and-copper-intensive -- costs rise ahead of price hikes"),
        ],
        label="Metal Prices ↑",
    ),
    "RULE_GOLD_PRICE_UP": _rule(
        "Gold prices rally materially",
        "commodity_price",
        [
            _b("banking", "nbfc", "bullish", "commodity",
               condition="the lender is gold-loan focused",
               mechanism="Higher gold prices raise the value of loan collateral, letting gold-loan lenders lend more against the same pledged gold"),
            _b("fmcg", "retail", "bullish", "commodity",
               condition="the retailer is jewellery-focused",
               mechanism="Jewellery retailers gain on inventory bought at lower prices; but sustained high prices eventually dent volume demand"),
        ],
        label="Gold ↑",
        caveats="A sharp gold rally often signals global risk aversion -- check whether the driver is fear or festive demand",
    ),
    "RULE_COAL_FUEL_COST_UP": _rule(
        "Coal, pet-coke, or power-fuel costs rise materially",
        "commodity_price",
        [
            _b("metals", "mining_coal", "bullish", "commodity",
               "Coal miners sell at higher realizations directly"),
            _b("infra", "power_utilities", "bearish", "input_cost",
               condition="the generator lacks automatic fuel-cost pass-through",
               mechanism="Fuel is the largest cost for thermal power generators -- without pass-through clauses, margins compress"),
            _b("infra", "cement", "bearish", "input_cost",
               "Coal and pet-coke fire cement kilns -- power and fuel are roughly 30% of cement's cost"),
            _b("metals", "steel", "bearish", "input_cost",
               "Coking coal is steelmaking's key input -- costlier coal squeezes spreads"),
        ],
        label="Coal/Fuel ↑",
    ),
    "RULE_AGRI_COMMODITY_SPIKE": _rule(
        "An agricultural commodity (wheat, sugar, palm oil, cotton, etc.) spikes",
        "commodity_price",
        [
            _b("fmcg", "staples_food", "bearish", "input_cost",
               "Wheat, sugar, and edible oils are packaged-food's main inputs -- costs jump before prices can follow"),
            _b("fmcg", "beverages", "bearish", "input_cost",
               "Sugar and packaging costs squeeze beverage margins"),
            _b("textiles", "yarn_fabric", "bearish", "input_cost",
               condition="the spiking commodity is cotton",
               mechanism="Cotton is the yarn spinner's raw material -- price spikes compress spinning margins"),
        ],
        label="Agri Commodity ↑",
        caveats="Identify WHICH commodity spiked first -- each has different downstream users",
    ),
    "RULE_CURRENCY_INR_STRENGTHENS": _rule(
        "The rupee strengthens materially against the dollar",
        "currency_move",
        [
            _b("it", None, "bearish", "currency",
               "Each dollar of export revenue converts to fewer rupees, pressuring margins"),
            _b("pharma", "generics_formulations", "bearish", "currency",
               "Dollar-denominated US sales are worth less in rupees"),
            _b("oil_gas", "refining_marketing", "bullish", "currency",
               "Dollar-priced crude imports cost fewer rupees"),
            _b("railways_transport", "aviation", "bullish", "currency",
               "Dollar costs -- fuel, leases, maintenance -- shrink in rupee terms"),
            _b("consumer_durables", None, "bullish", "currency",
               "Imported components get cheaper, easing cost pressure"),
        ],
        label="INR ↑",
    ),
    "RULE_GLOBAL_RISK_OFF": _rule(
        "The Fed turns hawkish, or a global growth scare / market selloff hits",
        "global_rates",
        [
            _b("it", None, "bearish", "demand",
               "Indian IT's revenue comes from US/EU corporate tech budgets, which get cut first in a downturn"),
            _b("banking", None, "bearish", "correlation",
               "Foreign investors sell index heavyweights first, and financials are the largest index weight"),
            _b("metals", None, "bearish", "demand",
               "Global growth fear means less construction and manufacturing, cutting metal demand and prices"),
        ],
        label="Global Risk-Off",
        caveats=("Defensive sectors -- staple consumer goods, pharma -- typically fall less; a hawkish Fed also "
                 "pressures the rupee, which partially cushions IT exporters"),
    ),
    "RULE_GLOBAL_RISK_ON": _rule(
        "The Fed cuts/turns dovish, or global markets rally on growth optimism",
        "global_rates",
        [
            _b("it", None, "bullish", "demand",
               "Reviving US/EU corporate confidence unfreezes tech budgets and deal decisions"),
            _b("banking", None, "bullish", "correlation",
               "Foreign inflows chase index heavyweights, and financials are the largest index weight"),
            _b("metals", None, "bullish", "demand",
               "Global growth optimism lifts commodity demand and prices"),
        ],
        label="Global Risk-On",
    ),
    "RULE_GEOPOLITICAL_CONFLICT": _rule(
        "War, armed conflict, or sanctions escalate in a region relevant to trade or energy",
        "geopolitics",
        [
            _b("defense", "defense_platforms", "bullish", "demand",
               "Conflict accelerates procurement budgets and export interest in Indian defense equipment"),
            _b("oil_gas", "upstream_exploration", "bullish", "commodity",
               condition="the conflict threatens oil supply routes or producers",
               mechanism="Supply-disruption fear pushes crude prices up, lifting producer realizations"),
            _b("railways_transport", "ports_shipping", "bullish", "demand",
               condition="shipping routes are disrupted",
               mechanism="War-risk premiums and longer rerouted voyages push freight rates up, benefiting shipping lines"),
            _b("railways_transport", "aviation", "bearish", "input_cost",
               "Fuel spikes and airspace closures raise costs and lengthen routes"),
        ],
        label="Geopolitical Conflict",
        caveats="Effects depend entirely on WHERE the conflict is and WHICH commodities/routes it touches -- verify before applying",
    ),
    "RULE_FII_OUTFLOWS": _rule(
        "Foreign institutional investors sell Indian equities in size for days/weeks",
        "fii_dii_flows",
        [
            _b("banking", None, "bearish", "correlation",
               "Financials are the largest index weight -- foreign selling hits them hardest mechanically"),
            _b("it", None, "bearish", "correlation",
               "IT heavyweights are large foreign-owned index names and sell off with the flows"),
        ],
        label="FII Outflows",
        caveats=("Flow-driven moves reverse when flows reverse -- they say little about business fundamentals; "
                 "domestic institutional buying often absorbs foreign selling"),
    ),
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_rulebook.py tests/test_chains.py -q`
Expected: ALL PASS.

- [ ] **Step 4: Commit**

```bash
git add app/reasoning/rulebook.py tests/test_chains.py
git commit -m "feat: commodity, currency, and global-macro rule catalog"
```

---

### Task 6: Policy/regulatory + pricing rule catalog

**Files:**
- Modify: `backend/app/reasoning/rulebook.py`
- Modify: `backend/tests/test_chains.py`

**Interfaces:**
- Produces: `RULE_DEFENSE_PROCUREMENT`, `RULE_PLI_INCENTIVE`, `RULE_IMPORT_DUTY_HIKE`, `RULE_EXPORT_RESTRICTION`, `RULE_RBI_TIGHTENING_NORMS`, `RULE_USFDA_ACTION`, `RULE_TELECOM_TARIFF_HIKE`; chains for `government_policy`, `trade_policy`, `regulation`, `pricing_action`.

- [ ] **Step 1: Extend chain test parametrize list** with `"government_policy", "trade_policy", "regulation", "pricing_action"`. Run `python -m pytest tests/test_chains.py -q` — expect 4 FAILs.

- [ ] **Step 2: Add the rules**

Insert after `RULE_GOVERNMENT_CAPEX` (order: `RULE_PLI_INCENTIVE` first for `government_policy`, `RULE_IMPORT_DUTY_HIKE` first for `trade_policy`, `RULE_RBI_TIGHTENING_NORMS` first for `regulation`):

```python
    "RULE_DEFENSE_PROCUREMENT": _rule(
        "Government approves or signs major defense procurement / indigenization orders",
        "government_spending",
        [
            _b("defense", "defense_platforms", "bullish", "demand",
               "Platform makers win multi-year production orders directly"),
            _b("defense", "defense_electronics", "bullish", "demand",
               "Every platform order pulls through radar, avionics, and electronics content"),
            _b("defense", "shipyard", "bullish", "demand",
               condition="the order is naval",
               mechanism="Naval orders book shipyard capacity for years"),
        ],
        label="Defense Orders",
        caveats="Execution timelines run years -- order wins change revenue visibility, not next quarter's numbers",
    ),
    "RULE_PLI_INCENTIVE": _rule(
        "Government announces/extends a production-linked incentive (PLI) or manufacturing subsidy scheme",
        "government_policy",
        [
            _b("consumer_durables", "appliances_electronics", "bullish", "regulation",
               condition="the scheme covers electronics/appliances",
               mechanism="Cash incentives tied to output cut effective manufacturing cost, improving margins and drawing capacity to India"),
            _b("auto", "auto_component", "bullish", "regulation",
               condition="the scheme covers auto/EV components",
               mechanism="Subsidies make local component manufacturing cost-competitive, winning share from imports"),
            _b("pharma", "api_cdmo", "bullish", "regulation",
               condition="the scheme covers APIs/bulk drugs",
               mechanism="Incentives revive domestic API manufacturing that had lost ground to Chinese imports"),
        ],
        label="PLI Scheme",
        caveats="Applies ONLY to the sectors the specific scheme actually covers -- read the announcement, don't assume",
    ),
    "RULE_IMPORT_DUTY_HIKE": _rule(
        "Import duties rise on a specific product category",
        "trade_policy",
        [
            _b("metals", "steel", "bullish", "regulation",
               condition="the duty protects steel",
               mechanism="Costlier imports let domestic steelmakers raise prices and win volume"),
            _b("consumer_durables", "appliances_electronics", "bullish", "regulation",
               condition="the duty protects finished electronics/appliances",
               mechanism="Import protection shifts demand to domestic manufacturers"),
            _b("auto", None, "bearish", "input_cost",
               condition="the duty falls on inputs the industry imports",
               mechanism="Duties on imported components raise production costs for vehicle makers"),
        ],
        label="Import Duty ↑",
        caveats="Identify the protected product first: its domestic PRODUCERS gain, its domestic USERS/importers lose",
    ),
    "RULE_EXPORT_RESTRICTION": _rule(
        "Government restricts or taxes exports of a commodity (steel, rice, sugar, wheat...)",
        "trade_policy",
        [
            _b("metals", "steel", "bearish", "regulation",
               condition="the restriction targets steel",
               mechanism="Losing export markets forces sales into the domestic market at lower prices"),
            _b("fmcg", "staples_food", "bearish", "regulation",
               condition="the restriction targets sugar/rice/wheat processors' output",
               mechanism="Export caps remove the higher-priced sales channel for food processors"),
            _b("auto", None, "bullish", "input_cost", order=2, via="cheaper domestic supply",
               parent_sector="metals",
               mechanism="Export-blocked steel floods the domestic market, cutting input costs for vehicle makers"),
        ],
        label="Export Curbs",
        caveats="The restricted commodity's producers lose; its domestic industrial buyers quietly win",
    ),
    "RULE_RBI_TIGHTENING_NORMS": _rule(
        "RBI tightens prudential norms -- risk weights, provisioning, or lending rules",
        "regulation",
        [
            _b("banking", "nbfc", "bearish", "regulation",
               "Higher risk weights on bank lending to NBFCs raise NBFC funding costs directly"),
            _b("banking", "private_bank", "bearish", "regulation",
               condition="the norms target the bank's growth segments (e.g. unsecured retail)",
               mechanism="Higher capital requirements against targeted loan types force slower growth in exactly the fastest-growing books"),
        ],
        label="RBI Tightening",
        caveats="Tighter norms strengthen the system long-term -- the hit lands on lenders leaning hardest on the targeted segment",
    ),
    "RULE_USFDA_ACTION": _rule(
        "USFDA issues a warning letter, import alert, or adverse inspection for an Indian pharma plant",
        "regulation",
        [
            _b("pharma", "generics_formulations", "bearish", "regulation",
               condition="the action names the company's plant",
               mechanism="An import alert blocks US-bound supply from that plant until remediation -- a direct revenue hit"),
            _b("pharma", "api_cdmo", "bearish", "regulation",
               condition="the action names the company's plant",
               mechanism="Contract manufacturers lose client volumes routed through the flagged facility"),
        ],
        label="USFDA Action",
        caveats=("Strictly company-specific: competitors supplying the same molecules often GAIN share while "
                 "the flagged plant remediates -- check who else makes the affected drugs"),
    ),
    "RULE_TELECOM_TARIFF_HIKE": _rule(
        "Telecom operators raise tariffs industry-wide",
        "pricing_action",
        [
            _b("telecom", "telecom_operator", "bullish", "demand",
               "Tariff hikes flow almost directly to revenue per user and profit -- network costs don't rise with price"),
            _b("telecom", "telecom_infrastructure", "bullish", "demand", order=2,
               via="operator cash flows", parent_sector="telecom",
               mechanism="Healthier operator finances sustain tower rentals and network capex"),
        ],
        label="Telecom Tariff ↑",
        caveats="A steep hike can push price-sensitive subscribers to downgrade or churn -- watch subscriber numbers next quarter",
    ),
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_rulebook.py tests/test_chains.py -q`
Expected: ALL PASS.

- [ ] **Step 4: Commit**

```bash
git add app/reasoning/rulebook.py tests/test_chains.py
git commit -m "feat: policy, regulatory, and pricing-action rule catalog"
```

---

### Task 7: Corporate-event rule catalog (company-scoped)

**Files:**
- Modify: `backend/app/reasoning/rulebook.py`

**Interfaces:**
- Produces: `RULE_ORDER_WIN`, `RULE_CAPACITY_EXPANSION`, `RULE_CREDIT_RATING_CHANGE`, `RULE_MANAGEMENT_GOVERNANCE_ISSUE`, `RULE_BUYBACK_DIVIDEND`, `RULE_STAKE_SALE_IPO`, `RULE_IT_DEMAND_SIGNAL` — all `branches=[]` (guidance-only; no chains, absent from digest).

- [ ] **Step 1: Add the rules**

Insert into the company-scoped block (after `RULE_BANKING_METRICS`):

```python
    "RULE_ORDER_WIN": _rule(
        "A company announces a large contract or order win",
        "order_win_contract",
        [],
        caveats=("Judge size against the company's ANNUAL revenue -- a 'large' order at 2% of revenue is "
                 "noise, at 30% it transforms visibility. Check margin profile and execution timeline; "
                 "revenue books over years. Losing bidders and rivals move only with specific evidence"),
    ),
    "RULE_CAPACITY_EXPANSION": _rule(
        "A company announces a new plant, capacity expansion, or major capex program",
        "corporate_action",
        [],
        caveats=("Ask how it's funded: debt-funded expansion into weak demand destroys value; "
                 "internally-funded expansion into visible demand compounds it. Expect near-term margin "
                 "drag (depreciation, ramp-up costs) before long-term growth"),
    ),
    "RULE_CREDIT_RATING_CHANGE": _rule(
        "A rating agency upgrades or downgrades a company's credit rating",
        "corporate_action",
        [],
        caveats=("A downgrade raises borrowing costs and can trigger covenant/collateral demands -- the "
                 "hit scales with leverage; heavily-indebted NBFCs and infrastructure developers are most "
                 "sensitive. Upgrades work in reverse but move prices less"),
    ),
    "RULE_MANAGEMENT_GOVERNANCE_ISSUE": _rule(
        "CEO/CFO exit, auditor resignation, fraud allegation, or promoter-pledge stress surfaces",
        "corporate_action",
        [],
        caveats=("Governance shocks compress the valuation multiple regardless of current earnings. An "
                 "auditor resignation is among the most severe red flags -- it implies the numbers "
                 "themselves may be unreliable. High promoter share-pledging adds forced-selling risk "
                 "if the stock falls"),
    ),
    "RULE_BUYBACK_DIVIDEND": _rule(
        "A company announces a buyback, special dividend, or big payout change",
        "corporate_action",
        [],
        caveats=("A buyback signals management sees the stock as undervalued and shrinks share count "
                 "(raising earnings per share) -- but check it isn't funded by debt the business needs. "
                 "A dividend cut usually signals cash stress and is a stronger negative than a hike is "
                 "a positive"),
    ),
    "RULE_STAKE_SALE_IPO": _rule(
        "Promoter/major holder sells a stake, or an IPO / lockup expiry adds share supply",
        "corporate_action",
        [],
        caveats=("Large stake sales add supply AND raise the question of why an insider is selling -- "
                 "check the stated reason against the seller's history. Lockup expiries add mechanical "
                 "supply without a fundamentals signal. A parent listing a subsidiary can unlock value "
                 "for the parent"),
    ),
    "RULE_IT_DEMAND_SIGNAL": _rule(
        "A global IT bellwether (e.g. Accenture) reports results/guidance, or US tech-spending data shifts",
        "earnings",
        [],
        caveats=("Global peers' guidance is a LEADING indicator for Indian IT demand -- strong bookings "
                 "commentary is bullish for TCS/Infosys/Wipro/HCL before their own results, weak guidance "
                 "bearish. Large caps track enterprise deal commentary; mid-caps swing harder both ways"),
    ),
```

- [ ] **Step 2: Run rulebook tests + count check**

Run: `python -m pytest tests/test_rulebook.py tests/test_chains.py -q`
Expected: ALL PASS. Then `python -c "from app.reasoning.rulebook import RULES, CHAINS; print(len(RULES), 'rules,', len(CHAINS), 'chains')"` — expect **40 rules, 16 chains**.

- [ ] **Step 3: Commit**

```bash
git add app/reasoning/rulebook.py
git commit -m "feat: corporate-event rule catalog (guidance-only rules)"
```

---

### Task 8: Playbooks for all 17 sectors

**Files:**
- Modify: `backend/app/reasoning/playbooks.py`
- Test: `backend/tests/test_playbooks.py`

**Interfaces:**
- Produces: `PLAYBOOKS` entries for the 8 missing sectors. `PLAYBOOKS_TEXT` grows accordingly (injected into stage-3 prompt automatically).

- [ ] **Step 1: Write failing test**

In `backend/tests/test_playbooks.py` add:

```python
def test_playbooks_cover_every_sector_except_other():
    from app.analysis.schemas import SECTORS
    from app.reasoning.playbooks import PLAYBOOKS
    assert set(PLAYBOOKS) == set(SECTORS) - {"other"}
```

Run: `python -m pytest tests/test_playbooks.py -v` — expect FAIL (8 missing).

- [ ] **Step 2: Add the 8 playbooks**

```python
    "railways_transport": (
        "Transport: aviation drivers are passenger demand, jet fuel (ATF, ~40% "
        "of cost), and USD/INR (fuel/leases are dollar costs); KPIs are load "
        "factor and yields. Ports/shipping track trade volumes and freight "
        "rates. Road logistics tracks fuel costs, e-commerce, and "
        "manufacturing activity. Rail equipment tracks government railway "
        "capex."
    ),
    "construction_realestate": (
        "Real estate: drivers are mortgage rates, affordability, and job/income "
        "confidence. KPIs: pre-sales/bookings, collections, net debt, "
        "inventory months. Commercial/REIT depends on office absorption and "
        "retail footfalls. Highly rate-sensitive in both directions."
    ),
    "defense": (
        "Defense: driven by government procurement orders, indigenization "
        "policy, and export wins. KPIs: order book vs annual revenue, "
        "execution pace. Order-to-revenue lag runs years -- wins change "
        "visibility, not next quarter."
    ),
    "agriculture": (
        "Agri inputs: driven by monsoon/sowing, minimum support prices, and "
        "subsidy policy (urea subsidies drive fertilizer economics; gas is "
        "the key input cost). Agrochemical demand tracks planted acreage and "
        "pest cycles. Watch subsidy-receivable delays on fertilizer balance "
        "sheets."
    ),
    "consumer_durables": (
        "Consumer durables: driven by festive/summer season demand, consumer "
        "financing availability, and input costs (copper, aluminium, steel, "
        "imported electronics). Rate-sensitive (EMI purchases). KPIs: volume "
        "growth, channel inventory. PLI schemes shift manufacturing "
        "economics."
    ),
    "media_entertainment": (
        "Media: ad revenue tracks GDP and consumer-sector health (FMCG/auto "
        "are the biggest advertisers). Subscription/OTT growth structural; "
        "multiplexes track box-office slate and occupancy. KPIs: ad growth, "
        "subscriber counts, occupancy rates."
    ),
    "chemicals": (
        "Chemicals: crude derivatives are the feedstock -- margins move "
        "inversely with crude. China supply/pricing swings global spreads "
        "(Chinese oversupply crushes realizations). Specialty chemicals have "
        "stickier pricing than commodity chemicals. KPIs: spreads, capacity "
        "utilization, export mix."
    ),
    "textiles": (
        "Textiles: cotton/yarn prices drive spinning margins (spread between "
        "cotton and yarn). Export demand from US/EU retail, USD/INR, and "
        "trade agreements (UK/EU FTAs, China+1 shifts) drive orders. KPIs: "
        "yarn spreads, export order books, utilization."
    ),
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_playbooks.py -q`
Expected: ALL PASS (the existing "every playbook key is a real sector" style tests must still pass).

- [ ] **Step 4: Commit**

```bash
git add app/reasoning/playbooks.py tests/test_playbooks.py
git commit -m "feat: sector playbooks for all 17 sectors"
```

---

### Task 9: Cascade prompt integration + version bumps

**Files:**
- Modify: `backend/app/analysis/cascade.py` (stage-2 digest injection, stage-3 instruction sharpening)
- Modify: `backend/app/reasoning/versions.py`
- Test: `backend/tests/test_cascade.py`

**Interfaces:**
- Consumes: `RULEBOOK_DIGEST` from Task 3.
- Produces: stage-2 prompt containing the digest; stage-3 refine-not-echo instructions.

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/test_cascade.py`:

```python
def test_primary_sector_prompt_contains_rulebook_digest():
    # RULE_MONSOON_GOOD appears only in the digest (stage 2), never in
    # SECTOR_DEFINITIONS -- proves the digest block is actually injected
    # into the primary sector-identification call and NOT the cascade call.
    from app.analysis.cascade import _identify_sectors
    client = ScriptedClient({"record_sectors": {"sectors": []}})
    _identify_sectors(client, "some facts", None)
    prompt = client.last_messages[-1]["content"]
    assert "RULE_MONSOON_GOOD" in prompt
    assert "KNOWN TRANSMISSION CHAINS" in prompt


def test_cascade_sector_prompt_has_no_rulebook_digest():
    from app.analysis.cascade import _identify_sectors
    from app.analysis.schemas import SectorFinding
    client = ScriptedClient({"record_sectors": {"sectors": []}})
    parents = [SectorFinding(sector="banking", direction="bullish", mechanism="m")]
    _identify_sectors(client, "some facts", parents)
    prompt = client.last_messages[-1]["content"]
    assert "KNOWN TRANSMISSION CHAINS" not in prompt


def test_company_rationale_instructions_forbid_verbatim_echo():
    from app.analysis.cascade import COMPANY_RATIONALE_INSTRUCTIONS
    assert "verbatim" in COMPANY_RATIONALE_INSTRUCTIONS.lower()
    assert "first principles" in COMPANY_RATIONALE_INSTRUCTIONS.lower()
```

(Adapt `ScriptedClient` usage to the file's existing helper — it already exists there; `last_messages` may need adding as a capture attribute if the helper doesn't record messages. Check its definition and follow the file's existing capture pattern.)

Run: `python -m pytest tests/test_cascade.py -k "digest or verbatim" -v` — expect FAIL.

- [ ] **Step 2: Inject digest into stage 2**

In `_identify_sectors` (`cascade.py:148`), primary branch only (`parent_sectors is None`): append to `framing`:

```python
        framing += (
            "\n\nConsult the KNOWN TRANSMISSION CHAINS reference below. When a "
            "chain's trigger genuinely matches these facts, follow its sector "
            "branches -- adapted to this article's specifics, and dropping any "
            "branch whose stated condition doesn't hold here. When none "
            "matches, reason from first principles. Never include a sector "
            "just because it appears in a chain -- the mechanism must hold "
            "for THIS article."
        )
```

And in the message content (primary branch only), before `Facts:`, insert:

```python
                f"KNOWN TRANSMISSION CHAINS:\n{RULEBOOK_DIGEST}\n\n"
```

Import `RULEBOOK_DIGEST` in the existing `from app.reasoning.rulebook import ...` line.

- [ ] **Step 3: Sharpen stage-3 consult block**

In `COMPANY_RATIONALE_INSTRUCTIONS` (`cascade.py:336-339`), replace the consult sentence block with:

```python
    "Consult the ECONOMIC REASONING RULES and SECTOR PLAYBOOKS below. When a "
    "rule genuinely applies: include its rule id verbatim as one entry in that "
    "company's evidence_refs, then ADAPT its mechanism to this article's "
    "specifics -- name the actual numbers, companies, and conditions from the "
    "news. Copying rule text verbatim into rationale or key_points is "
    "forbidden: the rules are generic priors, your output must be this "
    "article's specific story. The article's own facts always override a "
    "rule's generic direction -- when they conflict, follow the article and "
    "do not cite the rule. Respect each rule's 'only if' conditions -- a "
    "conditional branch whose condition doesn't hold here does not apply. If "
    "no rule matches, reason from first principles and cite no rule id -- do "
    "not force-fit one.\n"
```

- [ ] **Step 4: Bump versions**

In `backend/app/reasoning/versions.py`:

```python
PROMPT_VERSION = "2026.07.27-reasoning-v3"
KNOWLEDGE_VERSION = "2026.07.27-rulebook-v2"
```

- [ ] **Step 5: Run cascade + pipeline tests**

Run: `python -m pytest tests/test_cascade.py tests/test_pipeline.py -q`
Expected: ALL PASS, including the existing `test_company_rationale_instructions_contains_rulebook_and_playbook_content` (RULE_CRUDE_OIL_UP + ARPU probes still hold).

- [ ] **Step 6: Commit**

```bash
git add app/analysis/cascade.py app/reasoning/versions.py tests/test_cascade.py
git commit -m "feat: rulebook digest in sector stage, refine-not-echo rules in company stage"
```

---

### Task 10: Full verification + backfill + manual quality check

**Files:**
- No new code. Run: full test suite, sub-sector backfill, manual reanalysis.

- [ ] **Step 1: Full test suite**

Run from `backend/`: `python -m pytest tests/ -q`
Expected: ALL PASS (307+ tests). Fix any missed hardcoded-list assumptions (grep candidates: `EVENT_TYPES`, `CHAINS`, `PLAYBOOKS`, `SUB_SECTOR_TAXONOMY` in `tests/`).

- [ ] **Step 2: Token-size sanity check**

Run: `python -c "from app.reasoning.rulebook import RULEBOOK_TEXT, RULEBOOK_DIGEST; print('rulebook chars:', len(RULEBOOK_TEXT), 'digest chars:', len(RULEBOOK_DIGEST))"`
Expected: RULEBOOK_TEXT roughly 15-25k chars (~4-6k tokens), RULEBOOK_DIGEST under ~6k chars (~1.5k tokens). If digest exceeds that, shorten trigger phrasing, not coverage.

- [ ] **Step 3: Read backfill script, then run it**

Read `backend/backfill_subsectors.py` first — confirm it only processes companies with `sub_sector IS NULL` (per its one-shot design). Then run it per its own usage instructions (needs `DATABASE_URL` — this is the deployed DB; if unavailable in the environment, note it as a user follow-up instead of guessing credentials).

- [ ] **Step 4: Manual reasoning-quality check**

Run `backend/reanalyze_recent.py` (reads recent articles, regenerates analyses). Then verify in output:
- matched rule ids appear in `evidence_refs` where a rule plausibly applies
- rationale/key_points text is article-specific (no rule-text echo)
- sub-sector distinctions show up (e.g. an oil story treats upstream vs marketing companies differently)
- an article matching NO rule still gets first-principles reasoning with no fabricated rule citation

This step is observational (LLM output is nondeterministic) — report findings to the user rather than asserting pass/fail.

- [ ] **Step 5: Final commit (if any test fixups were needed)**

```bash
git add -A
git commit -m "test: suite fixups for expanded rulebook"
```

---

## Self-review notes

- Spec coverage: taxonomy (Task 1), EVENT_TYPES (Task 2), structured format + rendering + validation (Task 3), catalog (Tasks 4-7 = 40 rules: 9 legacy ids preserved + 31 new), playbooks (Task 8), prompt integration + versions (Task 9), backfill + manual verification (Task 10). Spec's "~35 rules" → 40 actual.
- Chain count: 16 chain-bearing event types (repo_rate_change, inflation, macro_data, fiscal_policy, monsoon_weather, crude_oil, commodity_price, currency_move, global_rates, geopolitics, government_spending, government_policy, trade_policy, regulation, pricing_action, fii_dii_flows); 6 excluded (earnings, merger_acquisition, banking_metrics, order_win_contract, corporate_action, other) = 22 EVENT_TYPES total. Consistent across Tasks 2/3/4-7.
- Legacy prose behavior preserved: RULE_EARNINGS/RULE_MERGER_ACQUISITION/RULE_BANKING_METRICS keep their guidance content via `caveats` so `get_rule` output remains meaningful.
- `rulebook.py` deliberately does not import `sub_sectors` (no reasoning→companies dependency); validation lives in tests.
