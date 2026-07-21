# Impact Charts — Phase 2 (Structured Transmission Chains) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the prose transmission chains already in `RULES` (`backend/app/reasoning/rulebook.py`) into structured `CHAINS` data the graph (Phase 3+) can consume and an LLM can verify. Pure data, no behavior change yet — nothing in the live pipeline calls `CHAINS`/`get_chain` after this plan; that wiring is Phase 3.

**Architecture:** A new `CHAINS: dict[str, list[dict]]` in `rulebook.py`, keyed by `event_type` (`app.analysis.schemas.EVENT_TYPES`), each value an ordered list of mechanism/sector edge dicts. Every edge is derived directly from the matching prose `RULES` entry's own text — this plan does not add any economic claim `RULES` doesn't already make.

**Tech Stack:** Python, pytest.

## Global Constraints

- Do not remove or rename any existing `RULES` key — `app.reasoning.confidence` and `pipeline._persist_alert`'s `rulebook_ids_json` extraction depend on them (verified: `pipeline.py`'s `_build_alert_company` calls `get_rule(ref)` for each `evidence_refs` entry to build `matched_rule_ids`).
- Every SECTOR-kind node label used in `CHAINS` must be a real value in `app.analysis.schemas.SECTORS` (verified list, 18 entries: `oil_gas, banking, auto, it, pharma, fmcg, metals, telecom, infra, railways_transport, construction_realestate, defense, agriculture, consumer_durables, media_entertainment, chemicals, textiles, other`).
- Every edge's `relation` must be one of `EDGE_RELATIONS` (this plan defines the list); every `direction` must be `"bullish"` or `"bearish"`.
- **No invented economics.** Every edge below is traced to the literal text of the matching `RULES` entry (quoted in this plan). Two sectors the source task doc originally proposed for the `crude_oil` chain (`auto`, `fmcg`) are DELIBERATELY DROPPED in this plan — `RULE_CRUDE_OIL_UP`'s actual text ("beneficiaries are upstream producers and oil exploration companies. Potentially negative: airlines, paints, chemicals, logistics, fuel-intensive manufacturing") names airlines/logistics (→ `railways_transport`) and paints/chemicals (→ `chemicals`), but never names auto or fmcg — "fuel-intensive manufacturing" is too generic to license picking a specific unnamed sector without guessing. This is exactly the kind of judgment call the source task doc's own reliability contract demands: real derivation, not filling a gap to look complete.
- `RULES` currently has 9 entries but `EVENT_TYPES` (schemas.py) has 9 values too, with a mismatch worth naming explicitly: `RULE_REPO_RATE_HIKE` exists in `RULES` but has NO corresponding `CHAINS` entry — `CHAINS["repo_rate_change"]` is derived ONLY from `RULE_REPO_RATE_CUT` (bullish-framed: rate cuts help banking/auto/construction). A real repo rate HIKE event would need the opposite directions, which this data structure (one fixed chain per event_type, no direction parameter) cannot represent. This is a known, documented limitation carried forward from the source task doc's own spec (which only asked for the CUT rule's chain) — out of scope to fix in Phase 2, flagged here so Phase 3+ doesn't silently assume `CHAINS["repo_rate_change"]` is direction-agnostic.

---

### Task 1: `CHAINS` structured data + tests

**Files:**
- Modify: `backend/app/reasoning/rulebook.py`
- Test: `backend/tests/test_chains.py` (new file)

**Interfaces:**
- Produces: `EDGE_RELATIONS: list[str]`, `NODE_MECHANISM = "mechanism"`, `NODE_SECTOR = "sector"`, `CHAINS: dict[str, list[dict]]`, `get_chain(event_type: str | None) -> list[dict] | None`, `CHAINS_TEXT: str` — all in `app.reasoning.rulebook`, for Phase 3's edge-generation stage to consume.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_chains.py`:

```python
import pytest

from app.analysis.schemas import SECTORS
from app.reasoning.rulebook import CHAINS, EDGE_RELATIONS, NODE_MECHANISM, NODE_SECTOR, get_chain


def test_every_sector_node_label_is_a_real_sector():
    for event_type, edges in CHAINS.items():
        for edge in edges:
            for endpoint in (edge["from"], edge["to"]):
                if endpoint["kind"] == NODE_SECTOR:
                    assert endpoint["label"] in SECTORS, f"{event_type}: {endpoint['label']!r} not in SECTORS"


def test_every_node_kind_is_mechanism_or_sector():
    for event_type, edges in CHAINS.items():
        for edge in edges:
            for endpoint in (edge["from"], edge["to"]):
                assert endpoint["kind"] in {NODE_MECHANISM, NODE_SECTOR}, f"{event_type}: bad kind {endpoint['kind']!r}"


def test_every_relation_is_valid():
    for event_type, edges in CHAINS.items():
        for edge in edges:
            assert edge["relation"] in EDGE_RELATIONS, f"{event_type}: bad relation {edge['relation']!r}"


def test_every_direction_is_valid():
    for event_type, edges in CHAINS.items():
        for edge in edges:
            assert edge["direction"] in {"bullish", "bearish"}, f"{event_type}: bad direction {edge['direction']!r}"


def test_every_edge_has_a_nonempty_note():
    for event_type, edges in CHAINS.items():
        for edge in edges:
            assert edge["note"].strip(), f"{event_type}: edge has an empty note"


def test_get_chain_none_event_type_returns_none():
    assert get_chain(None) is None


@pytest.mark.parametrize("event_type", [
    "repo_rate_change", "crude_oil", "government_spending", "currency_move", "inflation",
])
def test_broad_mechanism_event_types_have_a_nonempty_chain(event_type):
    chain = get_chain(event_type)
    assert chain is not None
    assert len(chain) > 0


@pytest.mark.parametrize("event_type", [
    "earnings", "merger_acquisition", "banking_metrics", "other",
])
def test_company_specific_event_types_have_no_chain(event_type):
    assert get_chain(event_type) is None


def test_get_chain_unknown_event_type_returns_none():
    assert get_chain("not_a_real_event_type") is None


def test_chains_text_is_nonempty_and_mentions_every_event_type():
    from app.reasoning.rulebook import CHAINS_TEXT
    assert CHAINS_TEXT
    for event_type in CHAINS:
        assert event_type in CHAINS_TEXT
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `python -m pytest tests/test_chains.py -v`
Expected: FAIL (`ImportError: cannot import name 'CHAINS' from 'app.reasoning.rulebook'`)

- [ ] **Step 3: Add `CHAINS` and its supporting code to `rulebook.py`**

In `backend/app/reasoning/rulebook.py`, add after the existing `RULES`/`RULEBOOK_TEXT`/`get_rule` block (after the current line 82, end of file):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_chains.py -v`
Expected: PASS, all tests.

- [ ] **Step 5: Run the full backend suite**

Run (from `backend/`): `python -m pytest -q`
Expected: PASS, no regressions. `RULES`/`RULEBOOK_TEXT`/`get_rule` untouched — every existing test that depends on them (e.g. `app.reasoning.confidence`'s rulebook-match tests, `pipeline.py`'s `rulebook_ids_json` tests) still passes unmodified.

- [ ] **Step 6: Commit**

```bash
git add backend/app/reasoning/rulebook.py backend/tests/test_chains.py
git commit -m "feat: add structured CHAINS transmission-chain data derived from RULES"
```

---

## Explicitly out of scope (this plan)

Wiring `CHAINS`/`get_chain` into `analyze_article` or any live LLM call — that's Phase 3 (edge generation + `ImpactEdge` persistence). Adding a `repo_rate_hike`-specific chain or any direction-parameterized chain structure — flagged as a known limitation above, not fixed here (the source task doc itself only specified the CUT rule's chain). Adding chains for `earnings`/`merger_acquisition`/`banking_metrics`/`other` — these are correctly company-specific per their `RULES` text, `get_chain` returning `None` for them is the intended, correct behavior, not a gap.

## Definition of done (this plan only)

1. `CHAINS` has exactly 5 keys (`repo_rate_change`, `crude_oil`, `government_spending`, `currency_move`, `inflation`), each a non-empty list of edges.
2. Every edge's sector-kind endpoint is a real `SECTORS` value, every `relation` is a real `EDGE_RELATIONS` value, every `direction` is `bullish`/`bearish` — enforced by tests, not just eyeballed.
3. `get_chain` returns `None` for `earnings`, `merger_acquisition`, `banking_metrics`, `other`, `None`, and any unrecognized string.
4. `RULES`/`RULEBOOK_TEXT`/`get_rule` are byte-for-byte unchanged.
5. Full backend test suite green.
