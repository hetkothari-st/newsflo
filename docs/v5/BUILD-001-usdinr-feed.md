# BUILD-001 — THE USDINR FEED, CONSOLIDATED

**Type:** implementation order. One document, six items, dependency-ordered.
**Status:** READY. Nothing started.
**Supersedes for implementation purposes:** `TICKET-001-usdinr-feed.md`,
`USDINR_FEED_SPEC.md`, `DEFECTS-003` D11/D11.1, `PATCH-001`, `PATCH-002`, and the
event-sign design. Those remain the reasoning; this is the order.

**Read `docs/v5/SESSION_PROTOCOL.md` first.** Items 1–3 touch files another session may
hold. Claim any migration number in `docs/v5/MIGRATION_CLAIMS.md` before writing one.

---

## 0. DEPENDENCY GRAPH — read this before picking up any item

```
  1. D11  ──────────────────────────────┐
     (reducer + 3 configs)              │
                                        ├──> 4. THE FEED  ──> 5. REVIEW WORKFLOW
  2. member_evidence  ──────────────────┤       (edges, labels,
     (one column, four values)          │        20 companies)
                                        │
  3. SIGN RESOLVER  ────────────────────┘
     (closed output, T1-T4)

  6. PATCH-001 (steel) · PATCH-002 (corrections)   ── independent, land anytime
                                                      STEEL IS TIME-SENSITIVE
```

**ITEM 4 CANNOT BE BUILT WITHOUT ITEM 1. This is stated rather than left to the
ordering, because it is not a sequencing preference — it is a correctness dependency.**
Build item 4 first and the feed publishes 42 companies asserting a rupee move does not
affect them, sourced from the fact that nobody looked. That is a ONE RULE violation
shipped to a reader, and it is worse than shipping nothing, because it is not visibly
broken.

Items 1, 2 and 3 are **independent of each other** and can be built in parallel by
three people. Item 4 needs all three. Item 5 needs item 3. Item 6 needs nothing.

---

# ITEM 1 — D11: absence of measurement must not publish as measured immateriality

**Hard prerequisite for items 2, 4 and 5.** `DEFECTS-003` D11 and D11.1 in full.

## 1.1 The defect in one line

`app/core/reducer.py` falls through to `materiality_bucket = "NO_MATERIAL_IMPACT"`
whether or not any channel was ever built. `net_effect` already makes the distinction
(`if not channels: NET_UNCERTAIN`); the bucket does not. The gate then hard-blocks with
`rejection_reason = "NO_MATERIAL_IMPACT"` — a statement about the world produced by an
absence in our database.

## 1.2 Files touched — four, and each omission has its own failure

| # | file | change | **if this specific piece is omitted** |
|---|---|---|---|
| 1a | `backend/app/core/reducer.py` | the three lines in §1.3, plus `_MATERIALITY_RANK["NOT_SIZED"] = 0` | **the defect stands.** Everything else in this item becomes dead config |
| 1b | `backend/config/gates.yaml` | `NOT_SIZED` **absent** from `hard_blocks.no_impact_buckets` | if added there, the hard block rejects every qualitative company. **The feed publishes zero rows and looks like a data problem** |
| 1c | `backend/config/gates.yaml` | new `qualitative_exposure` tier block | without it no tier admits `NOT_SIZED`. **Feed publishes zero rows** |
| 1d | `backend/config/gates.yaml` | `materiality_floor_pct` **absent** from that block | if present, the feed clears the floor via `unknown_materiality_delta_passes`. **The day cutover item 1 flips that key to `false`, the entire feed dies silently** |
| 1e | `backend/config/horizons.yaml` | `materiality_weight: {NOT_SIZED: 0.0}` | `HorizonPolicy.weight_for` **RAISES `ReducerInputError`** on every multi-horizon signal set. Not a wrong answer — a crash, on the first three-horizon record |
| 1f | `backend/app/discovery/coherence.py` | `NOT_SIZED` into `DATA_GAP_REASONS` | **D11.1 stands.** Every starved company counts as an *economic* peer, so the §A5.2 coverage note omits exactly the population it exists to describe. The system reports it checked when it did not |

## 1.3 The reducer change

```python
# reducer.py, replacing the fall-through at ~551-556
materiality_bucket = "NONE"
for channel in material:
    if _MATERIALITY_RANK[channel["materiality"]] > _MATERIALITY_RANK[materiality_bucket]:
        materiality_bucket = channel["materiality"]

if not channels:                              # nothing was sized, nothing attempted
    materiality_bucket = NOT_SIZED
elif materiality_bucket == "NONE":            # channels built, none material -- a finding
    materiality_bucket = "NO_MATERIAL_IMPACT"
```

`_MATERIALITY_RANK` gains `"NOT_SIZED": 0` so the loop stays total.

**No new signal kind is required.** "Zero channels" already carries the fact. An
`ABSTENTION` signal was considered and is not needed for this item; it becomes worth
revisiting only when partial sizing exists (`engine.py:328` already logs `PARTIAL`).

**Two couplings an implementer will trip over:**

* **`NOT_SIZED` must not be spelled `NONE`.** `mechanism_id` is resolved at
  reducer.py:612 from `material` channels only, and `material` is
  `materiality != "NONE"`. Spell it `NONE` and `mechanism_id` becomes `None`,
  **failing invariant 7 on the very records this change exists to protect.**
* A qualitative company **does** emit a CHANNEL signal (carrying direction and
  mechanism, `materiality = NOT_SIZED`). It is the *no-exposure* company that emits
  none. Both paths must be exercised.

## 1.4 Config

```yaml
# gates.yaml
hard_blocks:
  no_impact_buckets: [NO_MATERIAL_IMPACT, NONE]   # UNCHANGED -- NOT_SIZED absent

qualitative_exposure:
  materiality_buckets: [NOT_SIZED]
  evidence_grades: [C, D]
  require_mechanism_id: true          # invariant 7, reused verbatim
  max_graph_distance: 2
  min_sign_consistency: 0.60
  below_floor_allowed_effects: [MIXED, UNCERTAIN]
  # materiality_floor_pct DELIBERATELY ABSENT -- see 1d
```

```yaml
# horizons.yaml
materiality_weight:
  NOT_SIZED: 0.0
```

```python
# coherence.py
DATA_GAP_REASONS = frozenset({
    "NO_EXPOSURE_ROW", "EXPOSURE_STALE", "UNCOMPUTABLE_CHANNEL",
    "NO_EBITDA_BASE", "INSUFFICIENT_PARAMETER_DATA", "ENTITY_UNRESOLVED",
    "NOT_SIZED",
})
```

## 1.5 Acceptance tests

| # | test |
|---|---|
| A1 | a company with **zero channels** rejects with `NOT_SIZED`, never `NO_MATERIAL_IMPACT` |
| A2 | a company with channels that are **all immaterial** still rejects with `NO_MATERIAL_IMPACT` — existing behaviour unchanged |
| A3 | a section where every peer abstained renders a coverage note **naming all of them** |
| A4 | a record with `materiality_bucket = NOT_SIZED` reaches the qualitative tier and **cannot** reach PRIMARY or SECONDARY_RIPPLE |
| A5 | flipping `unknown_materiality_delta_passes` to `false` changes **no** qualitative-tier verdict |
| A6 | a three-horizon signal set containing a `NOT_SIZED` bucket does not raise `ReducerInputError` |

## 1.6 If item 1 is skipped

The feed ships and **42 of the 63 corpus companies publish a rejected row reading
`NO_MATERIAL_IMPACT`** on every rupee story. The review console shows a human that
those companies were assessed and found unaffected. They were not looked at. The
coverage note that exists to say so is silent, because `NO_MATERIAL_IMPACT` is not in
`DATA_GAP_REASONS`.

---

# ITEM 2 — `member_evidence`: one column, four values

**Depends on:** nothing. **Required by:** item 4.

## 2.1 Why

`evidence_grade` C vs D separates filing-cited from membership-only. **D conflates
three states**: never looked; looked and silent; looked and contradicted. A reader
cannot tell Goodyear (read, disclaims) from a company whose annual report nobody has
downloaded. **That is D11 arriving one level down**, and it is the fix for the one case
`MEMBERSHIP_CLAIM_ASSESSMENT.md` §5.3 calls indefensible.

## 2.2 The column

```
member_evidence:  NOT_EXAMINED | EXAMINED_SILENT | EXAMINED_CONFIRMS | EXAMINED_CONTRADICTS
```

| value | **set by** | condition | publishes? |
|---|---|---|---|
| `NOT_EXAMINED` | **nothing — the default** | no filing artefact (`data/filings/<isin>/source.json` absent) | yes · grade D · **caveat rendered** |
| `EXAMINED_SILENT` | **the sweep, mechanically** | artefact exists, sweep ran for this leaf, no candidate returned | yes · grade D · **no caveat** |
| `EXAMINED_CONFIRMS` | **a human, review path only** | reviewer approved an A+ excerpt (verbatim gate passed, page cited) | yes · **grade C** · excerpt rendered |
| `EXAMINED_CONTRADICTS` | **a human, review path only** | reviewer approved a disclaimer excerpt | **NO — excluded**, citation shown |

**The machine/human split is the design, not an optimisation.** `EXAMINED_SILENT` is
machine-set because "we opened the document and found nothing" is a mechanical fact.
`CONFIRMS` and `CONTRADICTS` are human-set because both attach a *meaning* to a
sentence — and the verbatim gate proves **containment, not semantics**.

## 2.3 `EXAMINED_SILENT` is the value an implementer will drop

Flagged explicitly because three states look sufficient and the fourth looks like
bookkeeping. **Dropping it collapses `NOT_EXAMINED` and `EXAMINED_SILENT` into one,
which is precisely the D11 conflation this document exists to remove — absence of
examination and examined-and-silent wearing the same label.**

It is also **strictly stronger evidence**: we opened the annual report and the company
did not disclaim. That is why it renders **without** the caveat and `NOT_EXAMINED`
renders **with** it.

## 2.4 Files touched

| file | change |
|---|---|
| new qualitative exposure table (migration — **claim the number first**) | `member_evidence` column, NOT NULL, default `NOT_EXAMINED` |
| `backend/app/analysis/sensitivity/engine.py` (or the qualitative emitter) | carry it onto the CHANNEL payload |
| `backend/app/core/reducer.py` | carry it onto `CompanyImpact` |
| `backend/app/core/reducer.py::serialize_company_impact` | emit it under `evidence` |
| renderer | the §2.5 caveat |
| `backend/app/ledger/review.py` | only path that may write `CONFIRMS` / `CONTRADICTS` |

## 2.5 Rendered caveat — `NOT_EXAMINED` only

> *Included on industry classification; this company's own filing has not been read.*

## 2.6 Acceptance tests

| # | test |
|---|---|
| B1 | all four values round-trip: exposure row → CHANNEL → `CompanyImpact` → serialized JSON |
| B2 | `EXAMINED_CONTRADICTS` **never** produces a company row, at any tier |
| B3 | `CONFIRMS` / `CONTRADICTS` cannot be written outside `review.py` — same guard shape as the 0012 review-session trigger |
| B4 | `EXAMINED_SILENT` is set by the sweep with **no human action**, and is distinguishable in the persisted record from `NOT_EXAMINED` |
| B5 | the caveat renders for `NOT_EXAMINED` and for **no other value** |

## 2.7 If item 2 is skipped

Goodyear either publishes NEGATIVE against its own filing, or vanishes with no
explanation. **Both are the §5.3 indefensible case.** An analyst who checks one name
and finds the feed contradicting that company's annual report has grounds to disbelieve
the whole feed, and is right to, because nothing in the output distinguishes a member
we read from one we did not.

---

# ITEM 3 — the sign resolver

**Depends on:** nothing. **Required by:** items 4 and 5.

## 3.1 The output object — closed on every axis

```
shock_proposal:
  variable:       <one of the 15 config/discovery.yaml modelled_shock_variables> | NONE
  direction:      UP | DOWN | FLAT | UNRESOLVED
  basis:          VERBATIM | INFERRED
  evidence_span:  <exact substring of the article body>
```

**Four direction values.** `FLAT` (read it, barely moved — a finding) and `UNRESOLVED`
(could not tell — an absence) are **different**, for the same reason
`NO_MATERIAL_IMPACT` and `NOT_SIZED` are. Collapsing them is D11 at the event layer.

**`evidence_span` is guarded by the gate that already exists.**
`app/ingest/filings/verbatim.contains_verbatim`, unmodified, checked against the
article body. A model that paraphrases fails. This makes the least verifiable judgement
in the system partly machine-checkable — not *"is the sign right"* but *"is the model
reading a sentence that exists"*.

## 3.2 Forbidden emissions

| forbidden | why |
|---|---|
| a variable outside the 15 | V4's failure was an **open** output space — 45 of 58 mechanism ids resolved to nothing |
| **any numeral, including a confidence score** | invariant 2 |
| a company | invariant 6; the event layer has no business naming one |
| `basis: VERBATIM` where the span contains no directional token about the variable | promotes an inference to a quotation |
| a direction on a **forecast** | *"rupee may weaken further"* is not a realised move. Sets `event_status`, not a shock |
| more than one variable per proposal | a story moving two variables emits two proposals, each with its own span |

## 3.3 `sign_convention` is a REQUIRED manifest field

```yaml
shock_variables:
  - name: USDINR
    sign_convention: >
      UP = the rupee DEPRECIATES (more INR per USD).
```

**Not documentation.** `USDINR` is quoted INR-per-USD, so *rupee weakens* → **UP**. A
model reasoning "weaken → down" is wrong every time and inverts the entire feed. The
loader must refuse a shock variable with no `sign_convention`.

## 3.4 The fixture table — this IS the regression set

| headline | direction | basis |
|---|---|---|
| "Rupee weakens past 88" | UP | VERBATIM |
| "Rupee at record low" | UP | VERBATIM |
| "Rupee strengthens on FII inflows" | DOWN | VERBATIM |
| "Rupee ends flat" / "little changed" | **FLAT** | VERBATIM |
| "Rupee gains vs euro, slips vs dollar" | UP | VERBATIM |
| "Importers rush to hedge as rupee slides" | UP | VERBATIM |
| "Rupee recovers from early losses to close higher" | DOWN | VERBATIM |
| "Rupee falls as crude spikes" | UP **+ a second proposal for BRENT_CRUDE** | VERBATIM |
| **"RBI intervenes to support the rupee"** | **UNRESOLVED** | INFERRED |
| **"RBI intervention halts rupee slide"** | **UNRESOLVED** | INFERRED |
| "RBI dollar sales lift rupee from record low" | DOWN | INFERRED |
| "RBI seen defending 88 level" | UNRESOLVED | — (forecast) |
| **"Dollar index surges to two-year high"** | **UNRESOLVED** | — |
| "Rupee may weaken further on Fed policy" | UNRESOLVED | — (forecast) |

**Two rules, both producing `UNRESOLVED`, both non-negotiable:**

* **Intervention vocabulary** (`intervene`, `support`, `defend`, `dollar sales`,
  `smoothing`, `curb volatility`) forces `basis: INFERRED` and requires an explicit
  net-move statement in the span. Absent one → `UNRESOLVED`. Intervention language
  contains **two opposite moves** — the fall that prompted it and the push back.
* **A statement about the dollar, DXY or "the greenback" is not a statement about
  USDINR** unless the rupee is named. The rupee can strengthen against a rising
  dollar; that is an ordinary Asian-FX day, not an edge case.

**The bolded rows are where a competent model is confidently wrong, so they break
first when a prompt changes.**

## 3.5 The abstain path

| direction | renders | why |
|---|---|---|
| `UNRESOLVED` | **`MACRO_CONTEXT`** — variable named, reason given, **no companies** | the tier exists for this, and **invariant 6 already forbids it from carrying a company list**, so the abstain path is enforced by a rule that predates this design |
| `FLAT` | no impact block; recorded `SHOCK_NOT_MATERIAL` | we could tell. Rendering it as macro would say "we could not" |
| `NONE` | no impact block, no macro block; recorded | the ordinary case; must not be noisy |

```
MACRO CONTEXT — USDINR
  This story reports a rupee move whose direction we could not determine
  from the article. No company-level impact is shown.
  Reason: intervention language with no net move stated.        [view article]
```

**Never defaults to a direction. Never silently drops the story.**

## 3.6 Invariant 3 — DO NOT AMEND

**Decision on record: no price-series check.** The sign comes from the article text
plus human confirmation.

A currency rate *is* a market price, and even a series check that may only **block**
would influence **tier** — which invariant 3 names explicitly. The circularity argument
(USDINR is the exogenous input, not the outcome) is sound and still does not survive
the text. Reinterpreting it silently is how a spec stops describing the system.

**Cost of not having it, quantified:** at ~1 rupee story/day, human confirmation is
~250 judgements/year at ~15 seconds — **about an hour a year.** Not worth amending a
load-bearing invariant for. Revisit only if volume outgrows human review.

## 3.7 Files touched

| file | change |
|---|---|
| new resolver module | prompt + closed-output parsing + `contains_verbatim` check |
| new fixture file | the §3.4 table |
| new AST test | resolver imports **no** market-data module and **no** company-keyed table — mirrors `tests/phase0/test_market_isolation.py` |
| family manifest loader | refuse a shock variable with no `sign_convention` |

## 3.8 Acceptance tests — T1 is the one that matters

| # | test |
|---|---|
| **T1 · MUTATION** | flipping the event sign **inverts every published company direction** (`NEGATIVE ↔ POSITIVE`; `MIXED` stays `MIXED`; company set unchanged). **If flipping the sign does not invert the output, the sign is not wired and the feed's direction comes from somewhere undeclared — worse than a wrong sign.** No assertion about correctness proves this; only mutation does |
| T2 | no `company_impact` row may exist whose event carries `shock_direction ∈ {UNRESOLVED, FLAT}`, or whose `shock_sign_confirmed_by` is NULL while the review phase requires confirmation. **DB-level, queryable**, in the shape of the 0011/0012 write guards |
| T3 | `contains_verbatim(article_body, evidence_span)` holds for every stored proposal; `basis: VERBATIM` with no directional token in the span is refused |
| T4 | AST: resolver isolation (§3.7) |
| T5 | every row of the §3.4 fixture table resolves as stated |

## 3.9 If item 3 is skipped

**A wrong sign inverts the entire feed — every company, every time — and nothing
detects it.** This is the single unverifiable point in the chain; skipping it does not
remove the judgement, it removes the record that a judgement was made.

---

# ITEM 4 — the feed

**DEPENDS ON ITEMS 1, 2 AND 3. Cannot be built without item 1** — see §0.

## 4.1 Three edges, three labels, zero nodes

Emitted as a manifest patch. **A human runs the loader; this item does not write
`mechanism_edge`** (invariant 13).

```yaml
# backend/config/families/usdinr.yaml
family_id: usdinr
version: 1
owner: <REQUIRED - named human>
reviewed_at: <REQUIRED>

shock_variables:
  - name: USDINR
    status: MODELLED              # already in config/discovery.yaml
    sign_convention: >
      UP = the rupee DEPRECIATES (more INR per USD).

exposure_leaves: []               # all three already in valid_exposure_tag

mechanism_edges:
  - edge_id: usdinr_imported_input_cost
    from_node: USDINR
    to_node: exposure:usd_cost_share
    exposure_tag: fx:usd_cost_share
    relationship_type: INPUT_COST                # buys in USD  -> NEGATIVE
    distance: 1
    derivation: AUTHORED
    confidence: <REQUIRED - loader will not invent one>
    source_url: <REQUIRED>

  - edge_id: usdinr_export_realization
    from_node: USDINR
    to_node: exposure:usd_revenue_share
    exposure_tag: fx:usd_revenue_share
    relationship_type: REVENUE_REALIZATION       # bills in USD -> POSITIVE
    distance: 1
    derivation: AUTHORED
    confidence: <REQUIRED>
    source_url: <REQUIRED>

  - edge_id: usdinr_foreign_currency_debt
    from_node: USDINR
    to_node: exposure:usd_debt_share
    exposure_tag: fx:usd_debt_share
    relationship_type: FX_TRANSLATION            # USD liability -> NEGATIVE
    distance: 1
    derivation: AUTHORED
    confidence: <REQUIRED>
    source_url: <REQUIRED>

section_labels:
  usdinr_imported_input_cost:    IMPORTED INPUT COSTS
  usdinr_export_realization:     EXPORT REALISATION
  usdinr_foreign_currency_debt:  FOREIGN CURRENCY DEBT

nodes: []      # NONE. FX exposure is balance-sheet-determined; no industry
               # implies it. The only family in the design with an empty layer 6,
               # and therefore the only feed with ZERO SECTOR_PROXY rows.
```

**Do not reuse** `it_export_realization`, `pharma_export_realization`,
`import_cost_inflation` or `electronic_import_cost` — all sector-flavoured. This feed's
sections are keyed on the **exposure**, so an FMCG importer would render under
"ELECTRONICS IMPORTS".

## 4.2 The 20 companies

Direction is a **pure function of (leaf, shock direction)** — no per-company judgement.
On rupee **depreciation**: cost leg NEGATIVE, revenue leg POSITIVE, debt leg NEGATIVE.
Invert on appreciation. Every excerpt is in
`backend/scripts/probes/_v2_clean.tsv` at the same `(leaf, ticker)` key.

### NEGATIVE — 11

| # | ticker | leg | p | excerpt |
|---|---|---|---|---|
| 1 | AARTIIND | COST | 185 | *"Exposures … arise on account of the various assets and liabilities which are denominated in currencies other than Indian Rupee"* |
| 2 | BALKRISIND | COST | 234 | *"Consumption of Raw Materials is arrived at after adjusting … imported raw materials"* |
| 3 | COLPAL | COST | 284 | *"changes in foreign currency values that impact costs of imported raw material"* |
| 4 | COSMOFIRST | COST | 111 | *"policy is to hedge material foreign exchange risk associated with borrowings, highly probable forecast sales and purchases"* |
| 5 | SIRCA | COST | 124 | *"The Company make significant amount of purchases in foreign currency which exposes th[em]"* |
| 6 | XPROINDIA | COST | 127 | *"major borrowings are in foreign currency and also purchases are made in foreign currency"* |
| 7 | **SCHAEFFLER** | **COST (net)** | 138 | *"Imports are higher than exports and hence the Company has foreign currency exposure to the extent of imports being higher than exports."* — **NET_DISCLOSED, see §4.3** |
| 8 | HUHTAMAKI | DEBT | 90 | *"availed External Commercial Borrowings from Huhtamaki Finance Company V B.V., Netherlands"* |
| 9 | JKTYRE | DEBT | 57 | *"rebalanced its borrowing mix … including foreign curr[ency]"* |
| 10 | SRF | DEBT | 142 | *"designates non derivative financial liabilities, such as foreign currency borrowings from banks, as hedging instruments"* |
| 11 | ASAHIINDIA | DEBT | 227 | *"foreign currency interest rate swaps to mitigate foreign currency and interest rate risk on foreign currency loan"* |

### POSITIVE — 4

| # | ticker | leg | p | excerpt |
|---|---|---|---|---|
| 12 | BRITANNIA | REV | 123 | *"The Company has export sales (2% to 3% of total sales) primarily denominated in US dollars and Euro."* |
| 13 | MRF | REV | 151 | *"Earnings in Foreign Exchange: FOB Value of Exports"* |
| 14 | POLYPLEX | REV | 248 | *"exposure to the risk of changes in foreign exchange rates also relates to the Company's operating activities (when revenue …)"* |
| 15 | SONACOMS | REV | 120 | *"cash flow hedges to mitigate foreign currency exchange risk arising from certain highly probable sales transactions denominated in foreign currency"* |

### MIXED — 5, all mixed BY FINDING

| # | ticker | legs | p | excerpt |
|---|---|---|---|---|
| 16 | GANDHAR | COST + REV | 178 | *"currency risk mainly on account of its import payables, short term borrowings and export receivab[les]"* |
| 17 | PANAMAPET | COST + REV | 155 | *"currency risk mainly on account of its import payables and export receivables"* |
| 18 | SOTL | COST + REV | 179 | *"exposed to currency risk mainly on account of its import payables and export receivables"* |
| 19 | BHARATFORG | REV + DEBT | 179 | *"exposure … relates primarily to its export revenue and long-term foreign currency borrowings"* |
| 20 | TIINDIA | COST+REV+DEBT | 64 | *"forex exposure … arise through trade transactions, namely, exports and imports, import of capital items besides short-term and long-term foreign currency borr[owings]"* |

**Each names both legs in one sentence — grade C, therefore exempt from the
MIXED-per-section cap** (`FAMILY_MANIFEST_DESIGN` §4A). They are the most informative
rows in the feed and must not be capped away.

### Not published

| | n | disposition |
|---|---|---|
| `EXAMINED_CONTRADICTS` | 1 | **Goodyear** — §4.4 |
| `EXAMINED_SILENT` | 42 | swept, no usable FX leg → **`NOT_SIZED`, never `NO_MATERIAL_IMPACT`** |
| MARGINAL, not promoted | 2 | CRAFTSMAN, UNOMINDA |

## 4.3 Schaeffler — NET_DISCLOSED, ship NEGATIVE

> *"Imports are higher than exports and hence the Company has foreign currency exposure
> to the extent of imports being higher than exports."*

Carries **both** legs, and its filing states **which side dominates, with no number**.
**Owner decision: ship NEGATIVE with the excerpt rendered, reason `NET_DISCLOSED`.**
Publishing MIXED while holding a filing that resolves it would be the worse error.

**n=1. The state generalises** — it is the qualitative-tier pattern in its purest form:
the company answers the question we refuse to compute. Sweep for it in every future
corpus.

## 4.4 Goodyear — the exclusion path

| step | |
|---|---|
| membership would say | tyre maker → NEGATIVE |
| the sweep found | `fx:usd_cost_share`, via the same patterns that admit the other ten |
| the sentence (p100) | *"The company has limited exposure to foreign exchange risk due to low reliance on imported raw materials and thus the company does not hedge…"* |
| reviewer sets | `member_evidence = EXAMINED_CONTRADICTS`, `pass_through_state = DISCLOSED_IMMATERIAL` |
| renders as | a line in the section's **coverage note**, excerpt and page on click |
| **never** renders as | absent (D11) · NEGATIVE (false) · `NO_MATERIAL_IMPACT` (asserts we measured) |

**Excluded on its own disclosure, cited. Every other unpublished company is excluded
because it said nothing. `member_evidence` is the only field that tells those apart.**

## 4.5 End to end

```
QUALITATIVE — IMPORTED INPUT COSTS                         negative · 8 companies
  Aarti Industries · Asahi India Glass · Balkrishna · Colgate-Palmolive ·
  Cosmo First · Schaeffler India · Sirca Paints · Xpro India
  Each company's own filing states it purchases inputs in foreign currency.
  1 company in this section discloses low exposure and is excluded.   [Goodyear]

QUALITATIVE — EXPORT REALISATION                           positive · 4 companies
  Britannia · MRF · Polyplex · Sona BLW

QUALITATIVE — FOREIGN CURRENCY DEBT                        negative · 4 companies
  Huhtamaki · JK Tyre · SRF · Asahi India Glass

QUALITATIVE — MIXED                                        mixed · 5 companies
  Bharat Forge · Gandhar Oil · Panama Petrochem · Savita Oil · Tube Investments
  Each discloses both an import and an export or borrowing exposure.

  No magnitude is shown. These are directional exposures from company filings,
  not sized impacts.
```

## 4.6 Acceptance tests

| # | test |
|---|---|
| C1 | all 20 publish at grade C with a page-cited excerpt; **zero `SECTOR_PROXY` rows in the feed** |
| C2 | the 42 silent companies reject with `NOT_SIZED` and appear in the coverage note |
| C3 | Goodyear appears in the coverage note and **as no company row at any tier** |
| C4 | all 5 MIXED survive the MIXED-per-section cap on grade-C exemption |
| C5 | Britannia's "2% to 3%" **does not render** — the qualitative templates are numeral-free by construction |
| C6 | on rupee **appreciation** every direction inverts (this is T1 applied to the real feed) |

## 4.7 If item 4 is built before item 1

**Stated again because it is the failure mode this document exists to prevent:** 42
companies publish `NO_MATERIAL_IMPACT`, the coverage note omits them, and the output
tells a reader the system checked when it did not. **Not visibly broken. Worse than
shipping nothing.**

---

# ITEM 5 — review workflow and stopping rule

**Depends on:** item 3.

## 5.1 The rule — sequential, not a fixed N

| phase | rule |
|---|---|
| **1** | human confirms **every** story |
| **2** | after **30 consecutive** confirmations with no correction → sample **1 in 5** |
| **3** | after **100 sampled** with no correction → sample **1 in 20** |
| **any correction, any phase** | **return to 100%**, restart the counter |
| **any prompt, model or vocabulary change** | **return to 100% automatically** |

**What 30-consecutive buys.** At a true 10% error rate, P(30 clean) ≈ 4%. Passing
phase 1 is strong evidence the rate is below ~10%; passing phase 2 pushes it below ~3%.
A real bound — unlike "we did 50 and it seemed fine."

**The auto-return clause is load-bearing.** The realistic failure is not a model wrong
today; it is a prompt edit six months from now silently inverting the convention while
sampling sits at 1-in-20. **Triggered by a hash over (prompt, model id, `sign_convention`,
`modelled_shock_variables`) — not by anyone remembering.**

## 5.2 It is Gate Zero starting

Every confirmation is a labelled `(article, variable, direction)` triple. The eval
corpus is empty **by design** because labelling is human work; this produces it as a
**by-product of shipping** rather than as a project. After a few hundred it is a
regression suite for the resolver.

**Store them in the Phase 7 eval schema from day one**, not in a side table.

## 5.3 Files touched

| file | change |
|---|---|
| review console | sign-confirmation surface: article, span, proposed variable + direction, confirm/correct |
| `backend/app/eval/store.py` | persist each confirmation as a labelled example |
| new | the phase/counter state, and the change-hash that resets it |

## 5.4 Acceptance tests

| # | test |
|---|---|
| D1 | in phase 1, **nothing publishes** without `shock_sign_confirmed_by` |
| D2 | one correction returns the phase to 100% and resets the counter |
| D3 | changing the prompt, the model id, or `sign_convention` returns to 100% **without human action** |
| D4 | every confirmation persists as a labelled eval example |

## 5.5 If item 5 is skipped

The sign ships unconfirmed. Item 3's T1 proves the sign is *wired*; only this proves it
is *right*. **And there is no path to ever turning review off**, because the phase
ladder is what earns that.

---

# ITEM 6 — the two patches

**Independent. Land anytime. No dependency on items 1–5.**

## 6.1 PATCH-001 — steel rename · **TIME-SENSITIVE**

Replace `input:steel_flat` and `input:steel_long` with a single **`input:steel`**;
flat-vs-long moves onto the **edge**, where the shock variable makes it verifiable.
`config/discovery.yaml` keeps both `STEEL_FLAT` and `STEEL_LONG`.

**Measured:** `steel_flat` 1 of 11, `steel_long` **0 of 11**, generic `steel` 7 of 11
across 11 auto-component annual reports. Buyers write "steel"; flat-vs-long is a
**mill's** distinction being asked to match demand-side prose.

> ### WHY THIS IS TIME-SENSITIVE
> **Both leaves have ZERO `company_exposure` rows and ZERO `mechanism_edge` rows
> today, so this is a vocabulary rename with no data migration.** The moment one row
> exists it becomes a **review-path ledger migration**, because `exposure_tag` is one
> of the columns the 0012 trigger guards and **there is no reviewed UPDATE path for
> it** (`DEFECTS-001` D1). **Do this before the first steel manifest, not after.**

Also lands the **leaf-authoring rule** into `config/exposure_tags.yaml`'s own header —
Rule 1: name the leaf in the **buyer's** vocabulary. Rule 2: **no leaf is authored
until swept against a corpus of the companies expected to carry it.** Both failures
cited with measured numbers.

**Files:** `backend/config/exposure_tags.yaml` (a human, per its header) · a
`valid_exposure_tag` resync migration (**claim the number first**; 0016 is the
precedent) · `qualitative_tag_yield_v2.py::PATTERNS`.

**Tests:** E1 — no `valid_exposure_tag` row for the two old leaves. E2 — re-sweeping the
11 auto-component filings yields ~6 of 11 usable on `input:steel`.

**If skipped:** ~50 acquired filings buy **five** steel companies instead of twenty, and
the failure looks like *"steel filings don't disclose inputs"* rather than *"we wrote
the leaf in the wrong vocabulary."*

## 6.2 PATCH-002 — two corrections

**A · `packaging_film_makers` → BOTH-edge node.** 3 of 6 corpus members disclose
in-house PET resin or polyester chip manufacture (Polyplex, Uflex, Jindal Poly) — the
highest backward-integration rate of any node tested, and structural rather than
coincidental. Recommended: **BOTH edges + per-company node membership**, so the three
non-integrated members keep a directional call. **First use of the `role` override on
measured evidence** — each `include` carries a filing citation, making these
`EXAMINED_CONFIRMS` findings rather than classification judgements.
**Blocked on the Packaging sub-split** (that isubgroup also holds glass and paper).

**B · Delhivery — CORRECTED 2026-08-17. This is a NODE correction, not a ledger one.**
The original text claimed no ledger row existed. **It does, and it is already at
`input:bought_in_freight`** (company_id 216, share 0.313, `reviewed_by ST269`). What
was wrong was `NODE_FOR_ISUBGROUP` in `contradiction_rate.py`, which collapsed the
whole `Logistics Solution Provider` isubgroup onto one node asserting diesel. **The
ledger was ahead of the design**, and it already carries the correct tag for all six
corpus logistics companies (`bought_in_freight`: DELHIVERY, TCIEXP, TCI, MAHLOG;
`freight_diesel`: VRLLOG 0.276, CONCOR 0.015 — VRL's figure matching the
ripple-bootstrap handover independently). **Nothing to migrate.** Delhivery's
*"commodity price risk is low"* is what the intermediated tag PREDICTS, so it
corroborates rather than contradicts: reclassified `EXAMINED_CONFIRMS` with a
low-sensitivity qualifier, **not** `EXAMINED_CONTRADICTS`. **Goodyear is now the only
`EXAMINED_CONTRADICTS` in the corpus, and the contradiction rate is 1 of 33 (3%), not
2 of 33.** Full record in `PATCH-002` §B.

**If skipped:** (A) three companies publish against their own filings — the §5.3
indefensible case, now with names. (B) the logistics NODES are authored against the
probe's coarse mapping rather than the ledger, and Delhivery is rendered as an
`EXAMINED_CONTRADICTS` exclusion when its filing in fact corroborates its tag.

---

# CARRIED FORWARD — recorded, not blocking

| # | item | why it is not blocking | what would unblock it |
|---|---|---|---|
| 1 | **diversification rate** — of the 336 membership-only companies, how many carry material revenue outside their isubgroup? | needs `company_segment`: **0 rows**, and **no reviewed write path** (`DEFECTS-001` D1), so it cannot be populated compliantly even with the data | fix D1, then measure. **The single largest open risk to membership-only** — if high, `MEMBERSHIP_CLAIM_ASSESSMENT` §5.3(2) moves from partly-mitigable to fatal |
| 2 | **CONCOR's table-shaped evidence** — logged as a **METHOD gap, not a vocabulary gap** | the sentence sweep systematically under-finds table-form disclosures. CONCOR's *"Rail freight expenses 5,022.02 / Road freight expenses 326.65"* (p412) and VRL's lorry-hire percentage are the two measured cases, and **both are the strongest evidence in their leaf** | a table-aware second-pass extractor. This is where the sized and qualitative routes converge |
| 3 | **`crude_derivative_petchem` split** | unlike steel it has **live rows** — 2 of 11 `company_exposure` (CEAT, Savita) and **2 of 2** `mechanism_edge`. A review-path ledger migration, not a rename | its own ticket. Candidates: `input:polyester_chain`, `input:styrenics`, `input:coating_resins`, `input:packaging_polymer` |
| 4 | **Packaging sub-split** | blocks `packaging_film_makers` taking `default_from_isubgroup: ["Packaging"]`, since that isubgroup also holds glass (AGI Greenpac, Haldyn) and paper (TCPL, Subam, B&B Triplewall) — neither carries petchem exposure | one reviewed sub-split. Until then membership is the 6 named corpus companies and nothing else |

---

# DEFINITION OF DONE

1. Items 1, 2, 3 complete with A1–A6, B1–B5, T1–T5 passing.
2. Item 4 complete with C1–C6 passing, **and not started before item 1 is merged.**
3. Item 5 in **phase 1** — every sign human-confirmed — on the day the feed first
   renders.
4. Item 6 landed, **steel before any steel manifest.**
5. The four carried-forward items still recorded and still not silently dropped.

**One human judgement per story. Everything downstream deterministic. No magnitude
anywhere.**
