# Handover — genericity audit → orphan mechanisms → mechanism-edge review authority

**Session role:** commodity-genericity audit of the impact engine, which
turned into a measurement session on V4's mechanism vocabulary and ended on a
schema defect. Ended 2026-08-17 on owner instruction. **Nothing merged; the
owner is sequencing merges.**

**Branch:** `wt/mechanism-review-authority`, worktree
`.worktrees/mechanism-review-authority`, branched from `master` at `eb177f84`.

**This session ran in the SHARED MAIN TREE for its whole working life** — it
predates `docs/v5/SESSION_PROTOCOL.md` (`ee302d11`, committed mid-session).
The worktree was created only at wrap-up, to commit. See "Suite numbers"
below: this materially affects which numbers are reportable.

---

## What was asked, across five turns

1. Audit for crude-specific logic that should be generic. Prove genericity by
   running a synthetic commodity end-to-end through discovery → sensitivity →
   reducer → gate → sectioning, config-only, zero code changes. If a code
   change is required, that is the finding.
2. Measure the `normalize.py` phrase-rule asymmetry in production before
   touching the transform. Fix the `BROAD_EVENT_TYPES` divergence. Log the
   `_TAXONOMY_LABELS` duplication as a cutover item; do not fix it.
3. Investigate the writer behind 45 orphan node ids — do not change it.
   Five specific questions (prompt constraint, post-hoc mapping, orphan
   classification, rendered output, V5 immunity).
4. Author the five fertilizer mechanisms as candidate `mechanism_edge` rows;
   add a metric (not a fix) to the V4 orphan fall-through; record the
   market/sentiment finding and an invariant against models writing
   `mechanism_edge`.
5. Do NOT insert the five edges — write the schema defect up instead,
   alongside the other session's D2.

---

## Completed (with paths)

### Already committed by the owner, not by me
- `f2e9d902` — `backend/tests/genericity/` (the synthetic-commodity proof),
  migration 0016, `exposure_measurement_grade_cap`, ripple bootstrap scripts.
- `2ee521d2` — carried my `DATA_GAPS` §15 (fertilizer complex) and cutover
  checklist item 6 (`_TAXONOMY_LABELS`) into `DATA_GAPS/fertilizer-complex.md`
  and `DATA_GAPS/cutover-checklist.md` during the per-topic split.

### On this branch
- **`BROAD_EVENT_TYPES` consolidation** — `backend/app/config.py`
  (`BROAD_MACRO_EVENT_TYPES` base, `BROAD_FANOUT_EVENT_TYPES`,
  `IMPACT_BROAD_EXTRA_EVENT_TYPES` = the declared `{geopolitics}` delta),
  `backend/app/analysis/cascade.py` (imports instead of restating),
  `backend/tests/test_broad_event_types_single_source.py` (7 tests).
  **Value-preserving on both sides: fan-out 10, triage 11, unchanged.**
- **Orphan metric, observation only** —
  `backend/app/market/orphan_metrics.py`, wired at the end of
  `_strict_sections` in `backend/app/market/ripple_layers.py`,
  `backend/tests/test_orphan_metrics.py` (11 tests, incl. an AST test that the
  call site is a bare statement and the return is the bare `layers`).
- **Five fertilizer mechanism candidates, NOT loaded and NOT loadable** —
  `backend/config/mechanism_edges_authored.yaml`,
  `backend/app/graph/authored_edges.py` (refuses all five by name today).
- **Invariant 13** (no model may write `mechanism_edge`) —
  `docs/v5/00_MASTER_CONTEXT.md` + guard
  `backend/tests/test_mechanism_edge_human_authored.py` (9 tests, same shape
  as `test_node_id_single_source.py`).
- **`docs/v5/decisions/ADR-002-price-fundamental-decoupling-load-bearing.md`**
  — six of 45 orphans are price-driven channels the doctrine refuses; three
  structural refusals in V5, two of them verified by execution.
- **`docs/v5/defects/DEFECTS-002-mechanism-edge-review-authority.md`** — D10,
  paired with DEFECTS-001's D2.

---

## Found but not written anywhere in the repo

**These exist only in this file. They are the reason to read it.**

### 1. The `normalize.py` asymmetry has a measured defect size of ZERO — my earlier claim was wrong

I reported in an early turn that the 12 modelled shock variables without a
`_PHRASE_RULES` entry cause node-id fragmentation. **Measurement says no.**

- 12 of 15 `modelled_shock_variables` have no phrase rule (`NATURAL_GAS`,
  `GSEC_10Y`, `STEEL_*`, `ALUMINIUM`, `COPPER`, `PALM_OIL`, `WHEAT`, `SUGAR`,
  `MILK`, `PET_COKE`, `FREIGHT_RATE`). Covered: `BRENT_CRUDE`, `USDINR`,
  `REPO_RATE`.
- **Not one of those 12 has produced a single stored node id in any
  database.** Nothing to fragment.
- Two things I had not checked: `normalize_node_id` already handles direction
  and plurals *generically* before the phrase rules (`steel_prices_rise`,
  `higher steel prices`, `steel_price_up` all collapse today with no rule);
  and those 12 are V5 discovery vocabulary, while the ids are written by the
  V4 engine, which never emits them.

**Do not "fix" the phrase rules.** Changing normalization rewrites stored ids
for zero measured benefit.

### 2. The real fragmentation is writer prefixes, and it is unrecorded

20 of 58 stored ids carry `shk_` / `shock_` / `node_`. `normalize_node_id`
does not strip them. Two clusters that should have joined and did not:

| ids | differ by | alerts |
|---|---|---|
| `shk_crude_price_up` / `shock_crude_price_up` | prefix only | 3 |
| `inflation_rate` / `shk_inflation_rate` | prefix only | 2 |

Root cause is §1 of the writer investigation: `SCHEMA_SHOCKS` **requires**
`shock_id`, and `grep -c "shock_id" prompts.py` → **0**. The model must emit
an identifier it is never told how to form. `child_id` appears once in 756
lines of prompt text and constrains only the *sector* case
(`prompts.py:686`), which is exactly why sector ids come back canonical and
economic-node ids do not. The owner ruled prompt work out of scope (it dies at
cutover); this is why, recorded.

### 3. Which database actually holds the V4 impact-graph corpus

A fresh session will look at `backend/newsflo.db` and find almost nothing.

| db | alerts | impact_edges | what it is |
|---|---|---|---|
| `Desktop\newsflo-local\newsflo-main.db` | 1804 | 3276 | the big corpus — but mechanism labels are V3 *rulebook display labels* ("Crude Oil ↑"), `causal_parent_id` is **0 non-null** |
| `Desktop\newsflo-local\newsflo-ingestion.db` | 15 | 163 | **the only V4 impact_graph corpus.** 58 distinct node ids, 44 `causal_parent_id`, 128 `company_node_exposures` |
| `backend/newsflo.db` (repo) | 608 | 39 | 1 distinct node id |

Every orphan number in ADR-002 and DEFECTS-002 comes from
`newsflo-ingestion.db`. **The Bash tool cannot open paths outside the project
directory** — copy them out with the PowerShell tool first.

### 4. Suite numbers I reported earlier are NOT reportable under protocol §4

I reported **3935** and **3963 passed** during the session. Both were produced
in the shared main tree while other sessions were committing into it. Under
`SESSION_PROTOCOL.md` §4 those are noise. The only reportable number from this
session is the worktree run recorded at the bottom of this file.

One failure I saw mid-session
(`test_gate_zero_tooling.py::test_M7_data_gaps_states_the_contract_corpus_size`)
was a race with `2ee521d2` splitting `DATA_GAPS.md` underneath a running
suite. It passes clean. That is the same class as the 70-phantom-failure
incident the protocol was written for.

### 5. `cascade.py` is dead on the serving path but live in three scripts

`pipeline.py:2177` — "the legacy cascade is no longer wired here". Its live
readers are `reanalyze_cascade.py:184`, `reanalyze_recent.py:96`,
`benchmark_impact_graph.py:143`. So the `BROAD_EVENT_TYPES` divergence was
live in *reanalysis and benchmarking*, not in serving. I corrected the owner
on this and it is worth not re-deriving.

### 6. `git status --porcelain` lies after in-place patch experiments

The variant experiments patched `traverse.py` and three conftests in place and
restored them. `git status` kept showing them ` M` (stat-dirty) while
`git diff` was empty. **`git diff` is authoritative**; `git update-index
--refresh` clears the cache. I nearly reported a false "files not restored".

---

## What I was about to do next

**Nothing.** Turn 5 was findings-only and it is delivered. No work is in
flight, no half-finished edit exists on this branch.

The next step the work *points at* — not started, not authorized — is the
combined D2+D10 fix, whose full cost is measured in DEFECTS-002: three seeder
signatures, one test with a wrong premise
(`test_a_reviewed_io_table_edge_can_be_traversed`), and one assertion that
inverts by design
(`test_an_unreviewed_io_edge_appears_in_the_review_queue`).

---

## Open questions waiting on the owner

1. **D10: does the AUTHORED exception survive?** I argue no — `derivation` is
   self-declared and cannot be a security boundary, and this repo's own
   `seed_edge` defaults to `derivation="AUTHORED"`, so "skip review" is what
   you get by not thinking. Owner has not ruled.
2. **The three-layer fertilizer gap** (`DATA_GAPS/fertilizer-complex.md` §15)
   — recorded as one ticket per instruction. Needs
   `FERTILIZER_SUBSIDY_OUTLAY` in `config/discovery.yaml`, five leaves in
   `config/exposure_tags.yaml`, then the edges. A leaf added without the shock
   variable is dead config.
3. **`subsidised_volume_rationing`** is flagged in the YAML as the weakest of
   the five, on one alert's evidence. It is written down so it can be
   *rejected explicitly* — a rejected edge is retained with its reason
   (invariant 12).
4. **Should the five candidates be relabelled `MODEL_PROPOSED`** once that
   enum exists? They are that, not AUTHORED. Currently `AUTHORED` because that
   is the only honest value the schema has today.

---

## What a fresh session would not learn from the repo alone

- `docs/v5/defects/DEFECTS-001` **D2** and `DEFECTS-002` **D10** are one
  defect. Fixing either alone leaves the §A3.2 guarantee leaking through the
  other. They were raised by two different sessions on the same day from
  opposite ends — reader side (a gate that checks a string is non-null) and
  writer side (a walk that reads provenance as authority).
- The V5 canonical path (`app/discovery`, `app/graph`, `app/analysis/
  sensitivity`, `app/core/reducer`, `app/core/gates`, `app/output/sections`)
  is **genuinely commodity-agnostic** — proven by `tests/genericity/`, which
  runs `SYNTH_COMMODITY_X` end to end with three YAML lines and zero code
  changes. It is also **completely unwired**: `grep` for it across
  `pipeline.py`, `routers/*.py`, `main.py` returns nothing. The generic engine
  exists and is dark; the crude-shaped one serves.
- The V4 registry (`knowledge.MECHANISMS`, 42 entries) is the *only* thing
  keeping 45 of 58 stored ids from being fully unlabelled. Extracting it to
  YAML — explicitly out of scope, and I agree it should stay out — would not
  change that orphan rate. Move it only after the writer stops emitting
  free-form ids, or you are building a config schema for a vocabulary the
  writer does not use.
- The V4 orphan fall-through **merges**: `_assemble` pass 2 collapses all
  `OTHER_LABEL` groups per effect, so N distinct mechanisms render as one
  section. Alert 21 renders three sections, all titled "other verified
  mechanisms", two of them identically. V5 cannot do this — `section_key`
  contains `mechanism_id`, so two unknowns stay two sections
  (`UNCLASSIFIED MECHANISM (<id>)`). Verified both ways.
- `directness` **does not exist as a column** on `alert_companies` in V4. The
  nearest proxy is `impact_type` ('direct'/'indirect'). `causal_distance` is
  stored and then **dropped at render** — not blank, not defaulted, discarded.
- The measurement scripts for every number in ADR-002 and DEFECTS-002 live in
  this session's scratchpad and are **not in the repo** — see "Would be lost"
  below.

---

## Reportable suite number (protocol §4)

Produced in `.worktrees/mechanism-review-authority` at `eb177f84` + this
branch's changes, `ENABLE_SCHEDULER=false`, main tree's interpreter:

**3961 passed · 10 skipped · 2 failed**

The two failures are **pre-existing and not from this branch**:

```
tests/test_scheduler_universe.py::test_supply_links_refresh_isolates_a_poisoned_doc
tests/test_scheduler_universe.py::test_supply_links_refresh_circuit_breaker_stops_after_consecutive_llm_failures
```

Verified by running that file in the clean `.worktrees/session-a` at
`ee302d11`, which contains none of this branch's changes: **same two fail
there** (2 failed, 13 passed). Nothing on this branch touches the scheduler
or supply links. Owner: whoever owns `test_scheduler_universe.py` — not
raised as a defect here because it was not this session's scope.
