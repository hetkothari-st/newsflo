# Structured Rulebook Expansion Design

## Problem

`backend/app/reasoning/rulebook.py` holds 9 prose rules + 5 hand-written
transmission chains, injected always-on into the direct-company stage of the
cascade (`cascade.py:340`). Coverage is thin (no gold, Fed, trade policy,
monsoon, USFDA, order wins, ratings...), rules speak only at sector level
(no sub-sector branches like upstream vs OMC, private bank vs NBFC), and the
prose `RULES` and structured `CHAINS` are two hand-maintained copies of the
same knowledge that have already begun to drift.

The user wants a comprehensive news→sector→sub-sector→company relationship
rulebook the LLM consults per article: scan it, take what matches, refine it
to the article's specifics — never emit static rulebook text as output.

## Goals

- ~35 rules covering all major Indian-market news families, each with
  explicit sub-sector branches (both directions where real, second-order
  ripples, applicability conditions).
- Single source of truth: structured rule data auto-generates the prompt
  text, the chart chains, and the confidence-engine lookup. No more
  prose/chains duplication.
- Every sub-sector reference machine-validated against
  `SUB_SECTOR_TAXONOMY`; taxonomy extended to all 17 sectors (currently 9).
- Dynamic use, not static output: prompt instructions require the LLM to
  cite matched rule ids, adapt the mechanism to the article, and forbid
  verbatim echo; article facts override generic rule direction.
- Rule content mined from the user's ChatGPT bible docs
  (`~/Downloads/ai_reasoning_pipeline/`: ECONOMIC_PROPAGATION_RULEBOOK.md,
  FINANCIAL_REASONING_RULEBOOK.md, SECTOR_PLAYBOOKS.md,
  INSTITUTIONAL_FINANCIAL_KNOWLEDGE_BASE.md) merged with independent
  financial-domain knowledge, rewritten to this repo's style and vocabulary.

## Non-goals

- No event-classification call to select rule subsets — rulebook stays
  always-on in the direct stage (fits comfortably in Gemini-primary context;
  see 2026-07-27-gemini-primary-reasoning-provider-design.md).
- No knowledge graph / vector DB / external knowledge files (per
  2026-07-15-reasoning-engine-upgrade-design.md's retrofit-not-rebuild
  decision).
- No per-rule calibration scoring yet — `matched_rule_ids` is already
  persisted; per-rule hit-rate tuning is future flywheel work.
- No frontend changes. Chart chains stay sector-level (sub-sector detail
  lives in prompt text and company-level reasoning, not chart nodes).
- Cascade stages 5/7 stay rulebook-free (a production incident showed
  prompt overweight there causes degenerate empty tool calls).

## Design

### 1. Structured rule format (`rulebook.py` rewrite)

```python
RULES: dict[str, dict] = {
    "RULE_CRUDE_OIL_UP": {
        "trigger": "Crude (Brent/WTI) rises materially -- sustained >3-5% move or supply-shock headline",
        "event_type": "crude_oil",
        "branches": [
            {"sector": "oil_gas", "sub_sector": "upstream_exploration",
             "direction": "bullish",
             "mechanism": "Higher realizations per barrel flow straight to E&P revenue",
             "order": 1},
            {"sector": "oil_gas", "sub_sector": "refining_marketing",
             "direction": "bearish",
             "mechanism": "OMC marketing margins compress when retail prices are politically capped",
             "condition": "if pass-through to pump prices is restricted",
             "order": 1},
            {"sector": "fmcg", "sub_sector": None, "direction": "bearish",
             "mechanism": "Packaging and freight costs rise; margin squeeze if pricing power weak",
             "order": 2, "via": "input costs"},
        ],
        "caveats": "Verify the company's actual role (upstream vs refiner vs marketer) before applying",
    },
    ...
}
```

Branch fields:
- `sector` (required): one of `SECTORS`.
- `sub_sector` (optional, default None): one of
  `SUB_SECTOR_TAXONOMY[sector]`; None means the whole sector.
- `direction` (required): `bullish` | `bearish`.
- `mechanism` (required): one plain-language causal sentence.
- `condition` (optional): when this branch applies ("if pass-through
  restricted"). Rendered as "(only if ...)" in prose.
- `order` (required): 1 = first-order impact, 2 = second-order ripple.
- `via` (required when order == 2): the path label ("input costs",
  "housing demand").

Rule fields: `trigger` (when the rule fires), `event_type` (one of
`EVENT_TYPES`, shared by multiple rules), `branches`, `caveats` (optional).

Generated artifacts (all derived, none hand-written):
- `RULEBOOK_TEXT`: per-rule prose block — trigger, then first-order
  branches ("sector/sub_sector direction: mechanism (only if condition)"),
  then second-order ("→ via X: ..."), then caveats. Injected into the
  stage-3 prompt exactly where `RULEBOOK_TEXT` is today.
- `CHAINS[event_type]`: chart edges in the existing
  `{from, to, relation, direction, note}` shape, derived from each event
  type's primary directional rule (the `_UP`/first-listed variant — same
  known limitation as today's repo-cut-only chain; `_generate_edges`'
  LLM-verify step already prunes edges the article contradicts). Nodes stay
  mechanism/sector kind — sub-sector branches within one sector collapse to
  one sector node, keeping the chart contract unchanged.
- `get_rule(rule_id) -> str | None`: returns the rendered prose for that
  rule. Signature unchanged — `pipeline.py:216`'s `matched_rule_ids` /
  `rule_matched` confidence input and `models.py`'s stored refs keep
  working untouched.

Validation (import-time asserts are avoided; a dedicated test module
validates instead, so a bad edit fails CI not production):
- every `sector` in `SECTORS`; every non-None `sub_sector` in
  `SUB_SECTOR_TAXONOMY[sector]`; `direction` in {bullish, bearish};
  `event_type` in `EVENT_TYPES`; `via` present on every order-2 branch;
  rule ids unique, UPPER_SNAKE, prefixed `RULE_`.

### 2. EVENT_TYPES expansion (`schemas.py`)

9 → ~18-22: existing (`repo_rate_change`, `inflation`, `crude_oil`,
`currency_move`, `government_spending`, `earnings`, `merger_acquisition`,
`banking_metrics`, `other`) plus `commodity_price` (gold/metals/coal,
non-crude), `global_rates` (Fed/global central banks), `trade_policy`
(duties/FTAs/sanctions/China+1), `regulation` (SEBI/RBI/sector
regulators), `government_policy` (PLI/subsidies — distinct from capex),
`fii_dii_flows`, `monsoon_weather`, `geopolitics`, `credit_rating`,
`order_win_contract`, `capacity_expansion_capex`,
`management_governance`, `ipo_listing_stake_sale`.

(That lists 22 total — final enum trimmed/merged during implementation to
whatever the 35-rule catalog actually needs; every event_type must have at
least one rule or be `other`.)

### 3. Rule catalog (~35 rules)

- **Macro (8):** repo cut, repo hike, inflation up, inflation down,
  GDP/IIP surprise, fiscal deficit/borrowing surprise, monsoon
  good/deficient, GST rate changes.
- **Commodity (6):** crude up, crude down, gold up, steel/base-metal
  prices up, coal/power-fuel costs up, agri-commodity spike.
- **Currency/global (4):** INR weakens, INR strengthens, Fed hike /
  global risk-off, Fed cut / risk-on.
- **Policy/regulatory (6):** govt capex push, PLI/production incentives,
  import-duty changes, sector-regulation tightening, RBI banking norms,
  SEBI/market-structure actions.
- **Corporate (7):** earnings beat/miss, M&A, large order win, capacity
  expansion, management change / governance issue, credit-rating change,
  stake sale / IPO / lockup.
- **Sector-trigger (4):** USFDA action (pharma), US tech-spend/recession
  signal (IT), telecom tariff moves, defense procurement.

Content sourcing: read the four bible docs listed in Goals, extract sound
causal claims, merge with independent domain knowledge, rewrite every rule
in the repo's plain-language mechanism style (the key_points lessons from
2026-07-15 spec follow-ups apply: causal AND plain-language, no
finance-jargon without unpacking). Discard bible claims that are vague,
non-Indian-market, or assume infrastructure this repo rejected.

### 4. Sub-sector taxonomy extension (`sub_sectors.py`)

Add the 8 missing sectors to `SUB_SECTOR_TAXONOMY` +
`SUB_SECTOR_DEFINITIONS` (same closed-vocabulary, `<sector>_other` escape
discipline):

- `railways_transport`: aviation, ports_shipping, logistics_roadways,
  rail_equipment, transport_other
- `construction_realestate`: residential_developer, commercial_reit,
  realestate_other
- `defense`: defense_platforms, defense_electronics, shipyard,
  defense_other
- `agriculture`: fertilizers, agrochemicals, seeds_agri_inputs, agri_other
- `consumer_durables`: appliances_electronics, wires_cables, durables_other
- `media_entertainment`: broadcast_tv, multiplex_film, digital_gaming,
  media_other
- `chemicals`: specialty_chemicals, commodity_chemicals, paints,
  chemicals_other
- `textiles`: apparel_garments, yarn_fabric, textiles_other

Run `backend/backfill_subsectors.py` for the new sectors after ship —
confirm during implementation that it only targets companies whose
`sub_sector` is still NULL (its documented one-shot design) so already-
classified sectors aren't reprocessed.

### 5. Prompt integration (`cascade.py`)

- **Stage 3 (direct companies):** `RULEBOOK_TEXT` injection point
  unchanged. `COMPANY_RATIONALE_INSTRUCTIONS` consult-block sharpened to:
  scan the rules; when one genuinely applies, cite its id verbatim in
  `evidence_refs` AND adapt its mechanism to this article's specifics —
  copying rule text verbatim into rationale/key_points is forbidden; the
  article's own facts always override a rule's generic direction (a rule is
  a prior, not a verdict); if no rule applies, reason from first principles
  and cite no rule id. Sub-sector branch language gives the model the
  vocabulary to distinguish company roles (upstream vs OMC) it currently
  blurs.
- **Stage 2 (sector identification, `_identify_sectors`):** add a compact
  always-on digest (rule id + trigger + affected sectors one-liner per
  rule, ~1-2k tokens) so sector fan-out follows known transmission chains
  instead of free association. Digest is a third generated artifact
  (`RULEBOOK_DIGEST`) from the same structure.
- **Stages 5/7 (cascade companies):** unchanged, no rulebook (see
  Non-goals).

### 6. Playbooks extension (`playbooks.py`)

Extend `PLAYBOOKS` from 9 to all 17 sectors (add railways_transport,
construction_realestate, defense, agriculture, consumer_durables,
media_entertainment, chemicals, textiles) in the same terse KPI/drivers
prose style. Minor, no structural change.

### 7. Versioning, confidence, flywheel

- `versions.py`: bump `knowledge_version` (and `prompt_version` — stage-2/3
  instruction text changes).
- Confidence engine: zero changes. `rule_matched` keeps working via
  unchanged `get_rule`. More rules → more legitimate matches → the 0.20
  rulebook-match weight stops penalizing well-reasoned analyses that simply
  had no matching rule to cite.
- `matched_rule_ids` already persisted per company — per-rule calibration
  scoring is deliberately deferred (Non-goals).

## Error handling

Pure static data + pure functions — no new runtime failure modes. All
integrity enforcement lives in tests (CI-time), not import-time asserts.
The LLM citing a nonexistent rule id is already handled: `get_rule` returns
None → ref simply doesn't count as a match (`pipeline.py:216`).

## Testing

- New `test_rulebook.py` structure suite: every branch resolves to a real
  sector/sub-sector, directions/event_types valid, ids unique and
  `RULE_`-prefixed, order-2 branches carry `via`, every event_type in
  `CHAINS` has ≥1 rule, `RULEBOOK_TEXT`/`RULEBOOK_DIGEST`/`CHAINS` all
  non-empty and contain every rule id / event type respectively.
- `test_chains.py` / `test_playbooks.py` / `test_cascade.py` expectations
  updated (chains now generated; playbooks cover 17 sectors; stage-2 prompt
  probe includes digest).
- Full suite green before merge.
- LLM behavior (rule matching + refinement quality) is not
  unit-testable — verify manually via `backend/reanalyze_recent.py` on
  recent articles after ship, checking: matched rule ids appear in
  evidence_refs where expected, rationale text is article-specific (not
  rule echo), sub-sector distinctions (e.g. upstream vs OMC on an oil
  story) actually show up.

## Implementation order

1. Taxonomy + definitions extension (sub_sectors.py) — foundation others
   validate against.
2. EVENT_TYPES expansion (schemas.py).
3. Structured rule format + rendering + validation tests (rulebook.py) with
   the existing 9 rules migrated first — proves the machinery before
   content scale-up.
4. Author remaining ~26 rules (bible mining + domain knowledge).
5. Playbooks extension.
6. Prompt integration (cascade.py stage 2 digest + stage 3 instruction
   sharpening) + version bumps.
7. Backfill run + manual reanalysis verification.
