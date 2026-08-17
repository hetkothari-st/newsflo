# QUALITATIVE TIER — can V5 publish a directional, ordered, mechanism-explained company list without sizing?

**Status:** DESIGN REPORT. Nothing implemented, no schema changed, no row written.
**Date:** 2026-08-17 · **Method:** read-only trace of the deployed code and a
read-only (`mode=ro`) audit of `backend/newsflo.db`.

> **`docs/v5/CONSOLIDATED_STATE_2026-08-17.md` does not exist in this tree.** It is
> not in `docs/v5/` and not in `git status`. Session A may hold it unmerged. This
> report was written from `00_MASTER_CONTEXT.md`, the three handovers in
> `docs/v5/handover/`, and the code itself. If the consolidated state contains
> decisions that contradict anything below, the consolidated state wins and this
> report needs a second pass.

**Answer up front.** Yes — but not on the path you think, and one of the two paths
that could carry it is the V4 LLM path you are trying to leave. The V5 ledger path
cannot, and the reason is not the publication gate. It is three layers *upstream* of
the gate: `company_exposure.share_of_base` is `NOT NULL`, the `exposure_index` view
hardcodes `share_of_base >= 0.02`, and discovery's only entry point is that view. A
qualitative exposure is not merely un-publishable today — it is **undiscoverable**,
because discovery's contract with the ledger is a numeric comparison.

The sizing layer is **not** necessary for the requirement as you stated it. It is
necessary for exactly one thing you did not ask for and will be asked for: ranking
two companies *within* a section. §F says what to do about that.

---

## A. THE TRACE

### A.0 There are two paths, and they behave oppositely

**Path A — the V4-fed canonical path. This is production today, and it already
publishes unsized.**

`app/core/signal_adapters.signals_from_entry` converts a V4 entry into signals. When
`sensitivity_channels` is empty (an empty ledger — which is production), it emits
CHANNEL signals carrying V4's **ordinal** materiality grade
(`MATERIALITY_GRADE_MAP`, signal_adapters.py:63) and **no `sensitivity` block**. The
reducer's ordinal aggregation runs (`reducer.py:528-556`), the gate sees
`delta_ebitda_pct_abs = None`, and `unknown_materiality_delta_passes: true` at both
tiers (`gates.yaml:139, 182`) lets it through as an `unknown_escape`.

So the machinery for "publish with no computed band" is already built, already
deployed, and already carrying every row you serve. What it is missing is not the
plumbing — it is the *provenance*. On Path A:

* `materiality_bucket` comes from an LLM grader;
* `mechanism_id` is `entry["causal_parent_id"]`, a free-form V4 node id, **not** a
  reviewed `mechanism_edge` id — signal_adapters.py:169-181 says so explicitly, and
  ADR-002 records that 45 of 58 V4 mechanism ids resolved to nothing;
* the direction comes from `channels_json`, i.e. from the model.

Path A satisfies "no sizing". It fails "no hallucination, no wrong identification,
no wrong logic" — which is the whole of your requirement.

**Path B — the V5 ledger path. It abstains before it ever reaches the gate.**

The gate is not the blocker. The engine never emits a signal, so there is nothing to
gate. The chain, with line numbers:

1. `discovery/engine.discover` → MECHANISM source → `graph/traverse.traverse` →
   `reachable_tags` → `config.threshold_for(distance)` →
   `discovery/index.query_exposure_index(tag, min_share=threshold)`.
   **Requires a numeric `share_of_base`.**
2. `analysis/sensitivity/engine.analyse_company` → `ledger/channels.ledger_exposures`
   → `ExposureView(base_value_inr=float(...), share_of_base=float(...))`
   → `_resolve_params` → `REQUIRED_PARAMS["COST"] = ("pass_through", "hedge_ratio")`
   → `params.resolve_param`, which has exactly three outcomes and the third is
   `raise InsufficientParameterData` (params.py:362-367). There is no step 4.
3. `engine.py:313` — `if not channels or not base: return SensitivityRun(signals=())`.
   Also needs `company_financials.ebitda_inr`, which has **1 row**.
4. No CHANNEL signal reaches the reducer → `net_effect = UNCERTAIN`,
   `materiality_bucket` falls through to `"NO_MATERIAL_IMPACT"` (reducer.py:551-556)
   → hard block `materiality_present` → **REJECTED / NO_MATERIAL_IMPACT**.

**Read step 4 again.** On the V5 path, "we have no pass-through curve" is rendered to
the reader as *"there is no material impact"*. That is a statement about the world
produced by an absence in our database. It is the exact inversion the master context's
ONE RULE exists to prevent, and it is live.

### A.1 Every rule, step and constraint that requires materiality or a computed band

Grouped by where it sits. "Must admit" = the minimum honest change.

#### HARD BLOCKS — `app/core/gates.py:219-251`, `config/gates.yaml:46-54`

| # | rule | what it does | must admit |
|---|---|---|---|
| 1 | `materiality_present` | REJECT when `materiality_bucket ∈ {NO_MATERIAL_IMPACT, NONE}` | a bucket value meaning *"exposure present, magnitude not measured"*. **Config-only** — migration 0011 declares `materiality_bucket` as a plain nullable String with **no CHECK constraint**, verified. |
| 2 | `shock_magnitude_confidence` | REJECT when confidence `< 0.5`, reason `MACRO_CONTEXT_HAS_NO_COMPANIES` | Guarded by `is not None`, so a shock that never claimed a magnitude passes. **But the field's meaning must be restated in writing**: it means "how sure are we the variable moved, and which way", not "how big". Today's comment ties it to sizing ("a shock we cannot size"). For your headlines — "markets decline amid rising crude" — the honest value is `None`. If any upstream stage starts writing a low confidence because no number was extracted, every company on every such story dies at the hard block. |
| 3 | `unbound_claims` | REJECT on any `UNBOUND` claim | **nothing. Keep.** This is the evidence firewall. |
| 4 | `exposure_freshness` | REJECT on stale exposure | **nothing. Keep** — but a qualitative tag needs its own `freshness_days`; `config/freshness.yaml` keys on `exposure_kind`, which a qualitative row still has. Reuses cleanly. |

#### TIER RULES — `gates.py:273-421`, `gates.yaml:69-184`

| # | rule | what it does | must admit |
|---|---|---|---|
| 5 | `materiality` | `materiality_buckets: [HIGH]` primary, `[HIGH, MEDIUM]` secondary | the qualitative bucket must be in **neither** of these. It goes in a **third tier block**. This is the single most important config decision in the proposal: putting the unsized bucket into `secondary_ripple.materiality_buckets` would silently turn every sized SECONDARY judgement and every unsized one into the same claim. |
| 6 | `materiality_floor_pct` | 2.0% primary / 0.75% secondary, with `unknown_materiality_delta_passes: true` | **do not route the qualitative tier through the unknown-escape.** Today a band-less draft clears the PRIMARY floor by escape; that is the "KNOWN HOLE" gates.yaml:18-42 documents and cutover-checklist item 1 exists to close. A qualitative draft must clear it because **the rule is not walked at its tier**, not because an input was missing. Otherwise the day you flip that key to `false`, the entire qualitative tier dies with the hole. |
| 7 | `directness` | at d1 requires `DIRECT`; at d2 requires `materiality_bucket == "HIGH"` (gates.py:256-270) | nothing — but note the coupling: an unsized company can never reach PRIMARY at d2 by construction. That is the correct outcome and it is free. |
| 8 | `evidence_grade` | primary `[A,B,C]`, secondary `[A,B,C,D]`; `exposure_measurement_grade_cap` maps `ESTIMATED→D`, `MODELLED→D` (materiality.yaml:87-89) | a `QUALITATIVE` measurement value with its own cap. **Recommend C when the citation is a company-named filing, D when it is a sector classification.** Never above C — a qualitative tag is never a PRIMARY authority. |
| 9 | `sign_consistency` | ≥0.90 primary, ≥0.60 secondary | **nothing, and this is the best news in the trace.** `_MATERIALITY_WEIGHT` (reducer.py:76) is ordinal and its own comment says "these are NOT magnitudes and never become one". With one bucket every weight is equal, so sign consistency degenerates to *(largest directional channel count) / (total directional channel count)* — 3 of 3 = 1.0, 2 of 3 = 0.67. That is exactly the qualitative statement you want, and **invariants 8 and 9 survive untouched.** |
| 10 | `require_mechanism_id: true` | invariant 7 | **nothing. Keep, and reuse verbatim in the third tier.** |

#### REDUCER STEPS — `app/core/reducer.py`

| # | step | issue | must admit |
|---|---|---|---|
| 11 | `mechanism_ids` (line 612) | reads only channels where `material` is true, and `material` is `materiality != "NONE"` | the qualitative bucket **must not be spelled `NONE`**, or `mechanism_id` becomes `None` and invariant 7 fails the record it was meant to protect. Easy to miss; it is a one-line coupling two hundred lines from the rule it breaks. |
| 12 | `_select_headline` (line 297) | scores each horizon by `|delta_ebitda_pct_p50| × materiality_weight`; with no band the magnitude term is `0.0` for all three, every score ties, and `policy.tie_break` (NEAR_TERM) always wins | works, but it is degenerate. See §F.3 — the honest fix is to **evaluate one horizon** for an unsized record and leave the other two `evaluated: false`, rather than assert three identical answers. |
| 13 | `HorizonPolicy.weight_for` (line 134) | **RAISES `ReducerInputError` on any bucket not in `config/horizons.yaml`** | the new bucket must land in `horizons.yaml` in the *same change*. Omit it and the reducer crashes on the first multi-horizon set. Hard coupling. |
| 14 | evidence grade cap (line 662) | `if sensitivity is not None: evidence_grade = cap_evidence_grade(...)` | **a real hole.** The cap is only applied when a sensitivity block exists. An unsized record therefore has **no cap applied at all**, so a qualitative claim carrying an A-graded `EVIDENCE_BINDING` would publish at PRIMARY. This is precisely the defect fix-round-1 C1 closed for the sized path, re-opened on the unsized one. The cap must be read from the exposure row's own `measurement` regardless of whether a band was computed. |
| 15 | `_uses_sector_proxy` (line 395) | returns `None` when no channel reports `param_sources` | a qualitative channel has no parameters, so it will always report `None` → `unknown_sector_proxy_passes: true` → the PRIMARY sector-proxy ban never evaluates. Same shape of hole as #14. A qualitative channel must report its own provenance (`FILED_QUALITATIVE` vs `CLASSIFIED`) so the rule has something true to read. |

#### OUTPUT — `app/output/`

| # | thing | issue | must admit |
|---|---|---|---|
| 16 | `sections._sort_key` (sections.py:150) | `tier → |median materiality| desc → alphabetical`; unsized sections sort **after every sized one** | replaced. See §E. |
| 17 | `compiler.TEMPLATES` | keyed `(claim_type, direction, materiality_bucket)` with buckets **HIGH/MEDIUM/LOW only**, and every `COST_EXPOSURE` / `REVENUE_EXPOSURE` template embeds `"{share_pct} percent of {base_kind}"` | numeral-free templates for the qualitative bucket. `MECHANISM_SENTENCE` (`"{ticker} is exposed through the {mechanism} channel."`) already has the right shape and no digits — it is the model to copy. |
| 18 | `firewall.stage_one` | checks numerals/entities/dates against the record set | **nothing.** The firewall gets *easier*: a numeral-free sentence has nothing to check. The only numerals a qualitative record contributes are `graph_distance` and `sign_consistency`, both already in `record_set_from`. The entailment firewall is strengthened by this proposal, not relaxed. |
| 19 | `coherence.section_decision` | `DATA_GAP_REASONS` | **nothing.** Works unchanged, and the coverage note becomes more accurate, not less. |

#### SCHEMA + DISCOVERY — the actual blockers

| # | thing | issue | must admit |
|---|---|---|---|
| 20 | `company_exposure` (0012:277-280) | `share_of_base NUMERIC NOT NULL`, `base_value_inr NUMERIC NOT NULL`, `measurement NOT NULL` | **the one true schema blocker.** A qualitative exposure has neither a share nor a base. Three options: (i) a sibling table `company_exposure_qualitative`; (ii) relax the NOT NULLs — **do not**, a SQLite `batch_alter_table` rebuild silently drops the table's triggers, which is 0008's documented warning and would take the review-only write guard with it; (iii) a sentinel share — that is fabrication. **Recommend (i).** |
| 21 | `exposure_index` VIEW (0013:169) | `WHERE e.share_of_base >= 0.02`, hardcoded in the view body | a companion view or a UNION. `discovery/index.py`'s docstring states discovery "never reads `company_exposure` directly, so the index's pruning rule cannot be bypassed by accident" — correct, and it means a qualitative row is invisible to discovery no matter what the gate says. |
| 22 | `discovery.yaml distance_thresholds` + `query_exposure_index(min_share=)` | 0.02 / 0.05 / 0.10 by distance | for a share-less row the threshold has no referent. Qualitative rows enter without a share test, which means the 250-name pool bound has to be governed some other way. See §F. |
| 23 | `engine._prior` (discovery/engine.py:202) | `if share_of_base is None: return 0.0` | **silent and fatal.** Every qualitative candidate gets prior 0.0, ranks last, and is the first thing `CandidatePool.add` evicts when the pool overflows. Qualitative discovery would appear to "not work" and the reason would be invisible. Needs a distinct ranking for share-less candidates. |
| 24 | `mechanism_edge` | `confidence NOT NULL`, `exposure_tag NOT NULL` + `valid_exposure_tag` trigger | **nothing. Keep all of it.** Invariant 13 is untouched by this proposal. |

### A.2 A live defect found while tracing

The two `mechanism_edge` rows in `backend/newsflo.db` have
`from_node = 'commodity:crude_oil'`. `config/discovery.yaml::modelled_shock_variables`
carries **`BRENT_CRUDE`**. `traverse(session, variable)` starts from `shock.variable`,
so a crude shock walks from `BRENT_CRUDE` and finds **neither edge**.

Those two edges are unreachable from discovery as written. `authored_edges.blockers()`
would have refused them for exactly this reason (`"from_node ... is not in
config/discovery.yaml::modelled_shock_variables, so discovery would report it
unmodelled and never walk this edge"`) — but they were hand-`INSERT`ed by the CEAT
proof-of-life session, which routed around the loader. The guard is right and it was
bypassed. This is §G's problem in miniature, sitting in the DB right now.

---

## B. THE QUALITATIVE TIER

### B.1 Shape

A **third publication tier**, `QUALITATIVE_EXPOSURE` — not a loosened
`SECONDARY_RIPPLE`. Three reasons:

1. Invariant 5 requires tiers to be evaluated by separate walks over the same draft.
   A third walk is structurally identical to the two that exist; `gates.evaluate`
   grows one more independent call. Merging it into secondary would break the
   separation the invariant protects.
2. The UI label must be a **tier**, not a footnote. A reader who cannot tell a sized
   ripple from an unsized one at a glance is being misled by omission.
3. It keeps A5.3's guardrail literally true: no primary threshold moves.

Every published qualitative record carries:

| field | source | note |
|---|---|---|
| `mechanism_id` | reviewed `mechanism_edge` | required, invariant 7, unchanged |
| `net_effect` | mechanism structure | see B.2 — never from a model |
| `graph_distance` | the BFS walk | computed, never authored |
| `directness` | as today | separate field, invariant 4 |
| `evidence_grade` + `claim_bindings` | filing citation | `BOUND` or `SECTOR_PROXY`, never `UNBOUND` |
| `materiality_bucket` | the literal `UNSIZED` | not `NONE`, not `LOW` |
| `sensitivity` | `null` | already a supported state everywhere |
| `sizing_status` | `NOT_SIZED` | **new, explicit** — so "we did not size this" and "we sized it and it was small" are different records rather than the same silence |

### B.2 Direction comes from structure, not from prose

This is already how the engine works and it needs no change. `channels._cost` opens
with a **minus sign**; `_revenue_realization` opens with a plus. The sign is a
property of `exposure_kind` × `relationship_type` × shock sign — a buyer of a thing
whose price rose is negative, a seller is positive — and it is read off the
`mechanism_edge` row, which only a human writes.

So "direction from the mechanism structure" is not a new capability. It is what
remains when you remove the multipliers. MIXED still arises structurally when a
company carries channels of both signs (e.g. an integrated energy name), and
`section_taxonomy.yaml` already has `integrated_energy` for exactly that.

**One caveat, and it is a real semantic change.** Sized `MIXED` means *both tails are
material* (`_apply_sensitivity`, reducer.py:355-361). Unsized `MIXED` can only mean
*there are channels in both directions*. Those are different claims. Conflating them
under one word is a silent redefinition. **Recommend a distinct value —
`OFFSETTING` — for the unsized case**, so `MIXED` keeps its sized meaning and
invariant 9 still says what it said.

### B.3 The six non-negotiables — all survive, none relaxed

| non-negotiable | status under the proposal |
|---|---|
| entailment firewall | **strengthened.** Fewer numerals to entail. `MECHANISM_SENTENCE` already passes stage 1 with no record-set additions. |
| `mechanism_id` requirement | **reused verbatim.** `require_mechanism_id: true` in the third tier block. |
| closed exposure vocabulary | **unchanged.** Qualitative rows use the same `family:leaf` tags and the same `valid_exposure_tag` DB trigger. No new vocabulary axis, no new tag shape. |
| invariant 13 (no model writes `mechanism_edge`) | **untouched.** The qualitative tier *reads* the graph. Nothing in it writes an edge. |
| evidence citation on every claim | **tightened.** A qualitative row's whole content is a citation. `claims.EVIDENCE_REQUIRED_TYPES` and `ACCEPTED_SOURCES` are unchanged, and `binding_status` decides the tier's evidence grade. |
| single-writer reducer | **unchanged.** The qualitative path emits `CHANNEL` signals like every other path and the existing reducer folds them. No second writer, no bypass. |

### B.4 What else in the spec breaks — stated honestly

* **§15 section ordering breaks.** Median materiality is the sort key. §E replaces it.
* **§11.2 compiler breaks.** No template exists for the bucket. Additive fix.
* **A5.1's materiality floor becomes inapplicable rather than fail-open.** Net effect
  is a *tightening*: today a band-less draft clears the PRIMARY floor through an
  unknown-escape; under this proposal it is routed to a tier where PRIMARY is
  unreachable. Shipping this is what finally lets cutover-checklist item 1 flip.
* **Mixed sized/unsized records become ill-defined.** If one channel is `HIGH`
  (weight 3.0) and two are `UNSIZED`, the sign-consistency arithmetic compares a
  magnitude-derived weight against a count. **Rule needed: a record must not mix
  sized and unsized channels; if it does, the whole record publishes as unsized.**
  Weakest-link, same principle as `cap_evidence_grade`.
* **`§5.2` Monte Carlo, `driver_ranking`, `MaterialityResult`** — simply not run.
  Nothing breaks; `sensitivity=None` is already handled at every consumer.
* **Three horizons become one.** See §F.3.

### B.5 Minimum honest change set

Eight items. Three are config. None touches an invariant.

1. **`company_exposure_qualitative`** — new table, same review-session write trigger
   pattern as 0012. Columns: `exposure_id, company_id, exposure_tag, exposure_kind,
   provenance (FILED_QUALITATIVE|CLASSIFIED), source_type, source_url, source_page,
   verbatim_excerpt, as_of_date, freshness_days, created_by, reviewed_by,
   proposal_id`. **No share. No base. No magnitude-shaped column at all** — if the
   column does not exist, nobody can fill it with a plausible number.
2. **`exposure_index_qualitative`** view; `discovery/index.py` reads both.
3. **`UNSIZED` bucket + `OFFSETTING` effect** — added to `gates.yaml`,
   `horizons.yaml` (item #13 above), and the compiler's `_DEGREE`/template map.
4. **Third tier block** in `gates.yaml` + `evaluate_qualitative` in `gates.py` +
   `TIER_QUALITATIVE` in the tier order tuple.
5. **Reducer: apply the exposure-measurement grade cap on the unsized path** (#14),
   and have qualitative channels report `param_sources`-equivalent provenance (#15).
6. **Compiler: numeral-free templates** keyed on the qualitative bucket.
7. **`sections._sort_key`** replaced per §E.
8. **`discovery.engine._prior`**: a distinct ranking rung for share-less candidates
   (#23), or they are evicted silently.

---

## C. PER-COMPANY COST

### C.1 Is "this filing states we consume synthetic rubber and carbon black" sufficient?

**For the tag: yes.** That sentence, with a page number and a `sha256`-provenanced
source, passing the verbatim containment gate, is a complete `COST_EXPOSURE` claim of
`fact_class = FACT` bound to a company by an `ANNUAL_REPORT` — which is already in
`claims.ACCEPTED_SOURCES` and already yields `binding_status = BOUND`.

**For the direction: yes, but not from the sentence.** The direction comes from the
mechanism edge (`relationship_type = INPUT_COST` → buyer → negative on a price rise).
The sentence establishes *that the company is a buyer*; the graph establishes *what
being a buyer means*. Neither a model nor the prose supplies the sign.

**For the distance: yes.** Distance is the BFS hop count, independent of the row.

**For which of two tyre makers is more affected: no.** That is §F, and it is the
honest limit.

### C.2 Cost, compared against the measured sized cost

The sized bootstrap's numbers, from `docs/v5/handover/ripple-exposure-bootstrap.md`:
**52 annual reports acquired → 9 usable `share_of_base`, 7 of them logistics.
Outside logistics: 2 of 45 (4%).** Cause named there: Schedule III requires one
"Cost of materials consumed" line and the Schedule VI class-wise breakup is gone.

The qualitative route hits a **different** constraint, and the difference is the
whole argument:

* Schedule III removed the *quantified* class-wise breakup. It did **not** remove the
  prose. The MD&A, the risk-factor section, the BRSR and the LODR commodity table all
  **name** inputs without quantifying them.
* Those are string-searchable in the corpus **already on disk** — `data/filings/`, 52
  reports with text layers in `pages.json.gz`, provenanced by URL + sha256, already
  swept for materials notes, LODR tables and hedging statements (handover §3e). That
  corpus is a reusable asset and nothing in the repo says so.
* The extraction is a regex sweep plus the existing verbatim containment gate — the
  same gate that caught three real errors last session (a cp1252 mojibake, the CEAT
  glyph split, a fabricated control excerpt). Machine-proposes, human-approves-excerpt.

**I will not give you a hit rate, because none has been measured and inventing one
here would be the fabrication guard's own target.** What I will give you is the
probe, because it costs nothing and it is the honest answer to "how many of my 3,400":

> **Run the tag sweep over the 52 reports already on disk.** For each of the 28
> vocabulary leaves, count how many of the 52 name that input in a company-named
> sentence that passes containment. One day, zero acquisition, zero new dependencies.
> That number is the qualitative yield, measured, and it is directly comparable to
> the sized 9/52.

Two things I can say without measuring:

1. **Reaching 3,400 companies by filing is an acquisition project, not an extraction
   project.** 52 reports are on disk. Extraction at any hit rate cannot exceed the
   corpus. Acquisition — not parsing — is the cost curve.
2. **The bulk lever is not filings at all.** It is `official_isubgroup`. See §D.

### C.3 The consequence: the qualitative tier has two grades, not one

| grade | source | reach today | binding | evidence grade | tier |
|---|---|---|---|---|---|
| **FILED_QUALITATIVE** | a company-named sentence in an accepted filing | bounded by the corpus (52 reports) | `BOUND` | C | qualitative tier, publishes |
| **CLASSIFIED** | an authored `official_isubgroup → exposure_tag` mapping | **4,669 companies immediately** | `SECTOR_PROXY` | D | qualitative tier, publishes **only where the mapping says `primacy: PRIMARY`** (§F.iv), always labelled as a classification |

That two-grade split is the entire practical content of this report. The first grade
is honest and slow. The second is honest, instant, and weaker — and it is honest
*only* because it is labelled as what it is and because it can never claim a filing
it does not have.

---

## D. AUDIT OF THE STORED COMPANIES DATABASE

**Located:** `backend/newsflo.db`, table `companies`, **5,321 rows**. Opened
`mode=ro`, read only, nothing written. (`newsflo.db` at repo root has the same schema
and **0 rows** — it is someone's scratch DB, flagged in the coordination handover.)

Universe split: **4,814 INDIA / 507 GLOBAL**. Tradeability: NORMAL 2,665 ·
RESTRICTED 2,100 · SME 509 · SUSPENDED 47. India + NORMAL + SME = 2,667.
**Your "~3,400" does not match any column in this table** — closest is
India-minus-SME-minus-suspended (4,258) or NORMAL+SME (2,667). Worth reconciling
before it becomes a denominator in a coverage metric.

### D.1 Field by field, with provenance and an importability verdict

| field | fill | provenance | importable? |
|---|---|---|---|
| `id`, `ticker`, `name` | 100% | internal / exchange | n/a — identity |
| `isin` | 90.5% (**100% of INDIA rows**) | exchange | **FILED** — identity, not a claim |
| `market` | 100% | internal | n/a |
| `sector` | 100% filled, **but 3,161 = `'other'`**, 11 distinct values | derived by `app/companies/sector_classification.py` + `universe/sector_map.py`; **contested writer** — the precision fix and the monthly refresh both write it | **NOT IMPORTABLE.** Provenance is a keyword map, not a source. Nothing here can back an exposure claim. |
| `sub_sector` | **15.5% (826)**, 43 distinct | same derivation | **NOT IMPORTABLE.** Coverage too thin and same provenance problem. |
| `official_sector` | 87.7% (4,669), 12 distinct | `classification_source = 'BSE'`, `classification_as_of = 2026-08-04` (uniform) | **ESTIMATED with review** |
| `official_industry` | 87.7%, **22 distinct** | BSE, dated | **ESTIMATED with review** |
| `official_igroup` | 87.7%, **58 distinct** | BSE, dated | **ESTIMATED with review** |
| `official_isubgroup` | 87.7%, **190 distinct** | BSE, dated | **ESTIMATED with review — this is the field.** See D.2. |
| `business_desc` | **10.9% (580)** | **`en.wikipedia.org`**, `as_of 2026-08-05` | **NOT IMPORTABLE.** Wikipedia is not in `claims.ACCEPTED_SOURCES` (`{ANNUAL_REPORT, QUARTERLY, EARNINGS_CALL, EXCHANGE_FILING}`). Binding a `COST_EXPOSURE` to it would be precisely what the fabrication guard forbids. **Usable only as a search hint** — to decide which filing page to open. |
| `supply_chain_suppliers_json` / `_customers_json` | **4 rows non-null, 1 with content** | LLM-era, unsourced | **NOT IMPORTABLE.** |
| `index_tier` | 100%, but 4,314 = `'OTHER'` | NSE index membership | ranking input only, never an exposure |
| `market_cap` | 87.5% (4,656) | `market_cap_source = 'BSE'`, `as_of 2026-08-04` | **FILED-equivalent**, for ranking/liquidity only. See §E on why it must not be the default sort. |
| `amfi_tier` / `amfi_rank` | 89.2% (4,744) | AMFI | ranking only |
| `tradeability` | 100% | exchange | **importable** — and it is the correct filter for the publishable universe |
| `shares_outstanding` | 48.9% (2,600) | unsourced column, no `_source` field | not needed here |
| `eps, ceps, pe, pb, opm, npm, roe, con_*` | **0% — all 5,321 rows NULL**; `financials_source` NULL for every row | — | **NOT IMPORTABLE — they are empty.** Any plan that assumed `opm × revenue` as an EBITDA proxy has no data behind it in this DB. (It would be a sizing input anyway, and out of scope.) |

Separately, the **`supply_links`** table (which discovery's `SUPPLY_CHAIN` source
actually reads) has **2 rows**, both with `counterparty_company_id IS NULL`.
`_extend_supply_chain` skips NULL counterparties, so **the SUPPLY_CHAIN discovery
source currently finds nothing at all.** The rows are well-sourced (ICRA rationale,
BSE URL, verbatim excerpt) — they just aren't resolved to company ids.

### D.2 Is the sector classification better than the 3,161-of-5,321 `'other'` problem?

**Decisively yes, and this is the highest-leverage finding in the report.**

* **2,971 of the 3,161 `'other'` rows carry a non-null `official_isubgroup`.**
* **190 sub-groups vs 11 sectors.** 58 industry groups. 22 industries.
* It is externally sourced (BSE), uniformly dated (2026-08-04), and its provenance
  is a named third party — which `companies.sector` is not.

The distribution is directly usable for exposure assignment. From the top of the
190: `Auto Components & Equipments` (136), `Iron & Steel Products` (125),
`Specialty Chemicals` (110), `Commodity Chemicals` (72), `Packaging` (75),
`Logistics Solution Provider` (58), `Cement & Cement Products` (39), `Sugar` (34),
`Edible Oil` (32), `Pesticides & Agrochemicals` (30), `Aerospace & Defense` (29),
`Breweries & Distilleries` (27), `Plastic Products - Industrial` (58),
`Paper & Paper Products` (50). Each of those maps to one or two exposure leaves with
a one-line human judgement.

**Two things this does NOT mean:**

1. **It does not fix `companies.sector`, and this proposal does not touch it.** You
   forbade that and the standing constraint holds. The mapping keys on
   `official_isubgroup` and leaves `sector` alone.
2. **A BSE classification is never a filing.** BSE saying a company is in "Tyres &
   Rubber" is not the company saying it buys carbon black. It is `SECTOR_PROXY`
   forever, grade D, and it must be labelled in the UI as a classification.

### D.3 A live noise bug this audit exposes

`discovery._industry_of` keys peer closure on `sub_sector OR sector`. `sub_sector` is
15.5% filled, so **84.5% of companies fall back to `sector`, and 3,161 of them are
`'other'`**. `peer_closure_min_members: 2` therefore fires on the pseudo-industry
`'other'` as soon as two mechanism-found companies land in it — and then sweeps
**every `'other'` company** carrying any reachable tag at ≥0.08.

Latent today only because the exposure ledger has 11 rows. It becomes a live noise
generator the moment the ledger is filled. `official_isubgroup` is the correct key
for `_industry_of` and switching it is a one-line change that does not touch
`companies.sector`.

---

## E. ORDERING WITHOUT MAGNITUDES

Graph distance is the primary key. It is not arbitrary: it is a BFS hop count over a
human-authored graph, computed by the walk and never authored (`traverse.py`'s own
docstring insists `authored_distance` and `graph_distance` are two different numbers).

### E.1 The tiebreak ladder

Each rung is a stored field, each answers a different question, and **none of them is
a magnitude**:

| rung | key | the question it answers | why it is defensible |
|---|---|---|---|
| 1 | `publication_tier` | how strong a claim is this? | already the first sort key today |
| 2 | `graph_distance` ↑ | how close is the causal path? | computed by BFS, not judged |
| 3 | `binding_status` / `evidence_grade` | how well do we know this company has this exposure? | `BOUND` (company-named filing) before `SECTOR_PROXY` (classification). This is the axis you actually care about, and it is auditable row by row. |
| 4 | `sign_consistency` ↓ | how consistently do this company's channels point one way? | a **count ratio over equal ordinal weights** — 3-of-3 above 2-of-3. `reducer.py:76` already states these are not magnitudes. |
| 5 | channel count ↓ | is it hit through one mechanism or two? | structural, countable, not a size |
| 6 | exposure `as_of_date` ↓ | how recent is the evidence? | a statement about *our* evidence, not about the company |
| 7 | `ticker` ↑ | — | deterministic final tiebreak |

**On market cap.** It is available at 87.5% and it is tempting. **Keep it out of the
default key.** Putting Reliance above a 500-crore tyre maker on a carbon-black story
implies Reliance is more affected — which is exactly the false claim removing sizing
was supposed to stop making. Offer it as a reader-selected sort, labelled *"ordered by
company size, not by size of effect"*, and never as the default.

### E.2 Two companies at the same distance through the same mechanism

**Do not rank them.** With equal distance, equal evidence grade and equal sign
consistency, there is no honest discriminator left, and inventing rung 8 would be
inventing the number you removed. Render them as an **unordered set, alphabetically,
on one line.**

This is not a new behaviour — `build_sections` already sorts companies inside a
section by ticker (sections.py:138). Magnitude was only ever doing work at the
*section* level. Company ordering inside a section is already not magnitude-ordered.

### E.3 Replacement for `sections._sort_key`

```
(tier_rank,
 min_graph_distance_in_section,        # ascending
 -bound_company_count,                 # descending: filing-cited members
 -company_count,                       # descending: A5.2's coherence premise
 median_materiality_if_present,        # descending, TIEBREAK ONLY
 label)                                # alphabetical
```

`bound_company_count` ranks a section by **how well evidenced it is**, not by how big
it is — a section where 4 of 5 names carry a company-named filing outranks one where
0 of 5 do.

Keeping `median_materiality` as a *late* tiebreak rather than deleting it is the
migration-safe form: a fully-sized deployment degrades gracefully back toward today's
ordering, and a mixed deployment does not put every unsized section at the bottom of
the page (which is what `(tier_rank, 1, 0, label)` does today, and which would make
the qualitative tier look like an afterthought no matter how good its evidence is).

---

## F. WHAT IS LOST

### F.1 Lost, concretely, with no mitigation

1. **"3.2% of EBITDA."** Gone. No band, no percentile, no denominator.
2. **Ranking two companies by effect size.** Gone. §E.2 refuses to fake it.
3. **Rejecting a company for trivial exposure.** The 2/5/10% distance thresholds and
   the 0.75/2% floors were doing exactly this work and they are gone.
4. **Driver attribution.** No `driver_ranking`, so no *"the pass-through assumption is
   doing all the work here"* honesty, and no `_dominant_proxy_param` weakest-link
   bridge.
5. **Sized `MIXED`.** Replaced by the weaker `OFFSETTING` (§B.2).

### F.2 What replaces the noise filter — four filters, none a percentage

**(i) Distance.** Qualitative publishes at **d1 and d2 only**. d3 requires a
company-named filing. The noise is at depth, and this is the cheapest cut.

**(ii) Evidence class.** Publish `BOUND` qualitative rows (company-named filing)
above `SECTOR_PROXY` ones, and consider not publishing `SECTOR_PROXY` at all in the
first release. That turns *"everything that touches crude"* into *"everything that
told its shareholders it touches crude"* — a materially smaller set, externally
auditable, and **the same filter a 20-year analyst would apply**.

**(iii) Mechanism specificity — the vocabulary is already built for this and it is
underused.** `input:crude_derivative_rubber` is not `input:freight_diesel` is not
`input:bought_in_freight`. The `bought_in_freight` comment in `exposure_tags.yaml` is
the model: a company *burning* diesel and a company *buying transport capacity* are
different exposures with different lags and different pass-through. **Rule: publish
only at the leaf the evidence names. Never publish a company under a parent concept.**
Structurally free — the vocabulary has no parent tags and three-segment tags are
rejected.

**(iv) The primary-business test.** `official_isubgroup` answers *"is this the
company's primary business?"* An airline on ATF is primary. A hotel chain that buys
some diesel is incidental. **The authored `isubgroup → tag` mapping gets a
`primacy: PRIMARY | INCIDENTAL` column, and `INCIDENTAL` never publishes.** One human
judgement per (isubgroup, tag) pair, made once, reviewed, reused forever — the
`mechanism_edge` discipline applied one layer down.

### F.3 Where an unsized system becomes indefensible to a 20-year analyst

Three places. Two have partial answers. One does not.

**1. A long list with no ordering by consequence. NO ANSWER.**
An analyst reads 40 names and asks "which three matter". Distance + evidence answers
"which three do we *know best*". Those diverge, sometimes badly. This is a real and
permanent loss and no filter above fixes it. State it in the UI: the tier's own label
must say the list is ordered by causal proximity and evidence strength, not by
expected impact.

**2. Two companies in the same section with opposite real outcomes. PARTIAL ANSWER,
and it is the best idea in this report.**
Two tyre makers both carry `input:crude_derivative_rubber` and both publish NEGATIVE
— but one has a quarterly RM-linked price-adjustment clause with its OEM customers and
one does not. The sized system caught that with `pass_through`. The unsized system
cannot… *unless the pass-through claim is itself made qualitatively.*

> *"The Company has a quarterly raw-material price-adjustment mechanism with its
> principal customers."*

That is a filing sentence with **no number in it**. It is `claim_type = PASS_THROUGH`,
which `claims.EVIDENCE_REQUIRED_TYPES` already forces to be company-named-filing-bound
or `UNBOUND`. It needs **no curve, no ratio, no lag in days**. And it can flip the
published label from `NEGATIVE` to `MITIGATED` — a qualitative modifier for a
qualitative claim.

Blue Dart's Fuel Surcharge Mechanism is exactly this shape and **has already been
found** (`data/hedge_ratio_UNSOURCED.csv`, reason `PASS_THROUGH_NOT_HEDGE`;
`CURVE_BOOTSTRAP.md` §4). The last session flagged it as the best filing-sourced
pass-through lead in the corpus. Under the sized design it was blocked because the
cadence had to become a curve. Under the qualitative design it publishes as-is.

**This is why you should not delete `pass_through_curve`.** Leave the table empty
forever if you like. The *claim type*, the *evidence rule* and the *review path* are
what you are reusing, and they already exist and already work.

**3. Direction right, horizon wrong. PARTIAL ANSWER.**
An unsized system cannot say *"yes, but not this quarter"*. `direction_by_horizon`
has three slots and all three would carry the same answer (§A.1 #12), which asserts
three evaluations nobody performed. **Answer: evaluate ONE horizon for a qualitative
record and mark the other two `evaluated: false`.** `UNEVALUATED_HORIZON` already
exists for precisely this and the serializer already emits all three keys with an
explicit `evaluated` flag. Free, and honest.

### F.4 The defensible floor, without a percentage

> **We publish a company when its own filing names this input through a mechanism a
> named human authored, or when its exchange-published primary-business classification
> makes the exposure structural — and the row says which of the two it is.**

An analyst can audit every published row against a source document in under a minute.
That is defensible. "Everything that touches crude" is a different claim, and the
tier label plus the `BOUND`/`SECTOR_PROXY` chip are what keep the two from being
mistaken for each other.

### F.5 Do I want to argue for the sizing layer instead?

**No.** For the requirement as you stated it — a directional, ordered,
mechanism-explained company list with correct identification and no hallucination —
sizing is not on the critical path. The measured evidence supports that: the sized
route yielded 2 usable non-logistics companies from 45 annual reports, and the
handover's own conclusion is that the bottleneck is a **chain of seven** empty links,
of which `share_of_base` is only one. Filling one link produces zero published
companies. The qualitative tier needs **two** links — `mechanism_edge` and a
qualitative exposure row — plus reviewed vocabulary, all of which are cheap.

The one thing I would push back on: **do not delete the sizing machinery.** Not
because you will need it soon, but because (a) §F.3.2's qualitative `PASS_THROUGH`
reuses its claim type and its evidence gate verbatim, (b) `§5.1`'s COST arithmetic
reproduced CEAT's own note 45(iv) sensitivity to within 0.8% — the strongest
validation in the repo — and (c) the day a filing hands you a number, the sized path
is already built and already tested. Leave the three tables empty. Empty tables cost
nothing; the pipeline already abstains correctly on them.

---

## G. THE FOUR-LAYER GAP, AND ONE REVIEWED PATH

### G.1 It is four layers, not three

Session 2 found three. The evidence in the tree shows four, and arguably five:

| layer | file / table | rule for changing it |
|---|---|---|
| 1 | `config/discovery.yaml::modelled_shock_variables` | edit + review; an unmodelled `from_node` is reported `unmodelled` and never walked |
| 2 | `config/exposure_tags.yaml` | its own header: *"a code review of THIS FILE plus a re-run of the loader"*; enforced at the **database** by the `valid_exposure_tag` trigger, not by a Python `if` |
| 3 | `mechanism_edge` row | invariant 13; written by a person, `AUTHORED` + `PENDING`, never by a model |
| **4** | **`config/section_taxonomy.yaml::labels`** | **missed by the three-layer framing.** A mechanism with no label renders `UNCLASSIFIED MECHANISM (x)` — a raw engine node id in a section header — **and fragments into its own singleton section**, because the id is part of the section key. `mechanism_edges_authored.yaml` already carries `section_label_proposed` for every entry, which is that file quietly discovering layer 4. |
| 5? | `config/policy_modifiers.yaml` | uses the same `pending_tag` convention, so it is on the same seam |

And under this proposal there is a **new layer 6**: the
`official_isubgroup → exposure_tag` mapping with its `primacy` column.

### G.2 The proposal: a mechanism-family manifest

One reviewed file per family, `backend/config/families/<family>.yaml`, and **one
loader that is the only route in**. All-or-nothing.

The shape is not invented — `config/mechanism_edges_authored.yaml` is already ~80% of
it (it has `shock_variables` with a `status`, `pending_tag`, `edges`, and
`section_label_proposed`). **The proposal is to promote that file's shape into the
reviewed path, not to design a new one.**

```yaml
family_id: fertilizer_subsidy
version: 1
owner:       <named human>       # required, no default
reviewed_at: <date>              # required

shock_variables:                 # -> config/discovery.yaml
  - name: FERTILIZER_SUBSIDY_OUTLAY
    definition: <what moves, where the level is observed>
    source_url: <the published series>

exposure_leaves:                 # -> config/exposure_tags.yaml families:
  - tag: revenue:subsidy_realization_share
    family: revenue
    group:  realization
    carried_by: <industries, prose>
    definition: <what a share on this tag would be a share OF>

mechanism_edges:                 # -> mechanism_edge rows, AUTHORED + PENDING
  - edge_id: fertilizer_subsidy_receivable_wc
    from_node: FERTILIZER_SUBSIDY_OUTLAY
    to_node:   fertilizer_subsidy_receivable
    exposure_tag: revenue:subsidy_realization_share
    relationship_type: REGULATORY
    distance: 1
    confidence: <required, no default>
    source_url: <required>

section_labels:                  # -> config/section_taxonomy.yaml labels:
  fertilizer_subsidy_receivable_wc: FERTILIZER SUBSIDY RECEIVABLES

classification_map:              # -> the isubgroup->tag mapping (qualitative tier)
  - official_isubgroup: "Fertilizers"
    tag: revenue:subsidy_realization_share
    primacy: PRIMARY
```

### G.3 What the loader does, in order

1. **Validate the WHOLE manifest first and report EVERY blocker at once.** Generalize
   `authored_edges.blockers()`, whose docstring already states the principle: *"ALL
   blockers are reported, not the first one: an owner clearing a vocabulary gap should
   see in one pass that the same edge is also waiting on a shock variable."* Nothing is
   written if anything is blocked.
2. **`--emit-patch`, not in-place edits.** The vocabulary files' own headers make
   extending them a code review of the file. The loader **must not append to
   `exposure_tags.yaml`**. It emits the exact YAML fragments for layers 1, 2, 4 and 6;
   a human commits them.
3. **`--apply`** re-reads the committed configs, runs the `valid_exposure_tag` resync
   (migration 0016 is the precedent), and inserts the edges as `derivation: AUTHORED`,
   `review_status: PENDING`, `reviewed_by: NULL`. **Invariant 13 intact** — the
   manifest is written by a person, the loader never approves.
4. **Assert closure** and refuse on any orphan:
   * every `from_node` ∈ `modelled_shock_variables` *(this is the check the two live
     CEAT edges failed — see §A.2)*;
   * every `exposure_tag` ∈ `valid_exposure_tag`;
   * every mechanism has a `section_taxonomy` label **after `normalize_node_id`** — the
     nine-id dialect trap that `section-taxonomy-v5.1.0`'s header documents;
   * every `classification_map` isubgroup exists in `companies.official_isubgroup`.
5. **Print the six-layer checklist with ✓/✗ per layer.** The refusal is the deliverable,
   exactly as `authored_edges.py`'s docstring already says.

### G.4 Why one unit and not six PRs

The layers are **not independent**, and each is individually valid while the
combination is broken:

* a tag with no edge is unreachable;
* an edge with no tag is refused by the DB trigger;
* an edge with no label renders a raw node id in a section header **and** fragments
  into a singleton section;
* a shock variable with no edge is silently reported `unmodelled`;
* a classification entry with no tag maps nothing.

Six separate reviews make the completeness check structurally impossible, because no
single reviewer ever sees the whole. One manifest makes it a single assertion.

### G.5 The cheap thing that makes it self-enforcing

A test — `test_no_orphan_mechanism_family` — asserting over the live config that:

1. every `modelled_shock_variables` entry is the `from_node` of ≥1 `mechanism_edge`,
   or is declared `PENDING` in a manifest;
2. every `valid_exposure_tag` leaf is the `exposure_tag` of ≥1 edge, or is declared
   unused;
3. every edge's mechanism has a section label after `normalize_node_id`.

**Today all three would fail** — 28 valid tags against 2 edges, 15 modelled variables
against 2 edges whose `from_node` matches none of them. That is the point: **the
failure list is the backlog**, and it is the first honest coverage number this program
would have.

---

## H. WHAT I DID NOT DO

* Did not run migrations, insert rows, or run the suite. Session A owns the tree.
* Did not measure the qualitative extraction hit rate — the probe is specified in
  §C.2 and it has **not** been run. Any number I gave you there would be invented.
* Did not read `CONSOLIDATED_STATE_2026-08-17.md`; it is not in this tree.
* Did not verify §D.3's peer-closure noise bug by execution — it is read off
  `_industry_of` (`sub_sector or sector`), the 15.5% `sub_sector` fill, and
  `peer_closure_min_members: 2`. It is a code + data reading, not a measurement.
* Did not check whether `docs/v5/defects/DEFECTS-001` already names any of #14, #15,
  #23 or §D.3. Some may be duplicates of existing defect entries.
