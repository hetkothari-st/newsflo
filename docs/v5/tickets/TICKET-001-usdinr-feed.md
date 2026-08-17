# TICKET-001 — THE USDINR FEED

**Type:** build ticket. **Status:** READY FOR IMPLEMENTATION, not started.
**Supersedes:** `docs/v5/USDINR_FEED_SPEC.md` (design note). Company count revised
15 → **20** after sweeping the 11 auto-component filings acquired 2026-08-17.
**Blocked by:** §2 (D11). Nothing else.
**Touches `mechanism_edge` / `exposure_tags.yaml`:** no. Both are covered by patches
(`docs/v5/patches/`), applied by a human.

---

## 1. What ships

A rupee story renders **20 companies** across **3 sections**, every row carrying a
company-named filing sentence with a page number. **Zero `SECTOR_PROXY` rows. Zero
acquisition.** One company is excluded on its own disclosure, with the citation shown.

| | |
|---|---|
| companies published | **20** — 11 NEGATIVE, 4 POSITIVE, 5 MIXED |
| companies excluded on evidence | **1** (Goodyear) |
| evidence grade | **C** throughout |
| distance | **d1** — direct balance-sheet exposure to the shock variable |
| sections | 3, keyed on exposure not on sector |
| new authored artefacts | 3 mechanism edges, 3 section labels |
| new data acquisition | **none** |

---

## 2. THE PREREQUISITE — D11, exactly

Without this, the 43 corpus companies with no usable FX leg each publish a rejected
row reading `NO_MATERIAL_IMPACT` — asserting a rupee move does not affect them when
nobody looked. `DEFECTS-003` D11 in full; **this is the minimum subset the ticket
needs.**

### 2.1 `app/core/reducer.py` — three lines

The bucket falls through to `NO_MATERIAL_IMPACT` whether or not any channel existed.
`net_effect` already makes the distinction (`if not channels: NET_UNCERTAIN`);
`materiality_bucket` does not.

```python
# reducer.py, replacing the current fall-through at ~551-556
materiality_bucket = "NONE"
for channel in material:
    if _MATERIALITY_RANK[channel["materiality"]] > _MATERIALITY_RANK[materiality_bucket]:
        materiality_bucket = channel["materiality"]

if not channels:                              # nothing was sized, and nothing was
    materiality_bucket = NOT_SIZED            #   even attempted
elif materiality_bucket == "NONE":            # channels were built and none was
    materiality_bucket = "NO_MATERIAL_IMPACT" #   material -- a real finding
```

`_MATERIALITY_RANK` gains `NOT_SIZED: 0` so the loop is total. **No new signal kind
is required** — "zero channels" already carries the fact.

### 2.2 `config/gates.yaml` — three keys

```yaml
hard_blocks:
  no_impact_buckets: [NO_MATERIAL_IMPACT, NONE]   # UNCHANGED. NOT_SIZED is absent
                                                  # on purpose: it is not a finding
                                                  # of no impact.
qualitative_exposure:            # the third tier block
  materiality_buckets: [NOT_SIZED]
  evidence_grades: [C, D]
  require_mechanism_id: true
  max_graph_distance: 2
  min_sign_consistency: 0.60
  below_floor_allowed_effects: [MIXED, UNCERTAIN]
```

**`materiality_floor_pct` is deliberately ABSENT from this block** — the floor is not
a rule at this tier, rather than a rule cleared by an unknown-input escape. Otherwise
flipping `unknown_materiality_delta_passes` to `false` (cutover item 1) silently kills
the whole feed. This is `DEFECTS-003` D11's §6 requirement.

### 2.3 `config/horizons.yaml` — one key

```yaml
materiality_weight:
  NOT_SIZED: 0.0        # REQUIRED. HorizonPolicy.weight_for RAISES ReducerInputError
                        # on any bucket it does not carry, on every multi-horizon set.
```

### 2.4 `app/discovery/coherence.py` — one entry

```python
DATA_GAP_REASONS = frozenset({
    "NO_EXPOSURE_ROW", "EXPOSURE_STALE", "UNCOMPUTABLE_CHANNEL",
    "NO_EBITDA_BASE", "INSUFFICIENT_PARAMETER_DATA", "ENTITY_UNRESOLVED",
    "NOT_SIZED",                       # D11.1 -- without this the coverage note
})                                     # still omits the population it describes
```

### 2.5 Acceptance tests

1. A company with zero channels rejects with `NOT_SIZED`, **never** `NO_MATERIAL_IMPACT`.
2. A company with channels that are all immaterial still rejects with
   `NO_MATERIAL_IMPACT` — the existing behaviour must not change.
3. A section where every peer abstained renders a coverage note naming all of them.
4. A qualitative record with `materiality_bucket = NOT_SIZED` reaches the qualitative
   tier and **cannot** reach PRIMARY or SECONDARY_RIPPLE.
5. Flipping `unknown_materiality_delta_passes` to `false` does not change any
   qualitative-tier verdict.

---

## 3. THE MEMBER-EXAMINATION COLUMN

One column, four values. Lives on the qualitative exposure row, travels on the CHANNEL
payload → `CompanyImpact` → `serialize_company_impact`.

```
member_evidence  NOT_EXAMINED | EXAMINED_SILENT | EXAMINED_CONFIRMS | EXAMINED_CONTRADICTS
```

### 3.1 How each value is set, and by what

| value | set by | condition | publishes? |
|---|---|---|---|
| `NOT_EXAMINED` | **default; nothing sets it** | no filing artefact for this company (`data/filings/<isin>/source.json` absent) | yes, grade D, **caveat rendered** |
| `EXAMINED_SILENT` | **the sweep, mechanically** | a filing artefact exists, the sweep ran for this leaf, and returned no candidate | yes, grade D, **no caveat** |
| `EXAMINED_CONFIRMS` | **a human, through the review path only** | a reviewer approved an A+ excerpt (verbatim gate passed, page cited) | yes, **grade C**, excerpt rendered |
| `EXAMINED_CONTRADICTS` | **a human, through the review path only** | a reviewer approved a disclaimer excerpt | **NO — excluded**, citation shown |

**The split is the design.** `EXAMINED_SILENT` is machine-set because "we opened the
document and found nothing" is a mechanical fact. `CONFIRMS` and `CONTRADICTS` are
human-set because both attach a *meaning* to a sentence, and the verbatim gate proves
containment, not semantics (`MEMBERSHIP_CLAIM_ASSESSMENT.md` §3.1, point 7).

### 3.2 Why `EXAMINED_SILENT` is load-bearing

It is the value an implementer will drop, because three states "look sufficient".
Dropping it collapses `NOT_EXAMINED` and `EXAMINED_SILENT` into one — **which is D11
re-emerging one level down**: absence of examination and examined-and-silent wearing
the same label, exactly as absence-of-measurement and measured-immateriality do at
record level.

It is also **strictly stronger evidence**: we opened the annual report and the company
did not disclaim. That is why it renders without the caveat and `NOT_EXAMINED` does
not.

### 3.3 Rendered caveat

Only `NOT_EXAMINED` carries one:

> *Included on industry classification; this company's own filing has not been read.*

`EXAMINED_SILENT`, `EXAMINED_CONFIRMS`: no caveat. `EXAMINED_CONTRADICTS`: not
rendered as a company at all — see §7.

---

## 4. THE THREE EDGES

Patch only. **A human runs the loader; this ticket does not write `mechanism_edge`**
(invariant 13).

```yaml
# docs/v5/patches/ -> backend/config/families/usdinr.yaml
family_id: usdinr
version: 1
owner: <REQUIRED - named human>
reviewed_at: <REQUIRED>

shock_variables:
  - name: USDINR
    status: MODELLED          # already in config/discovery.yaml
    sign_convention: >
      UP = the rupee DEPRECIATES (more INR per USD). Stated because "USDINR up"
      is ambiguous to a reader and inverts every company in the feed.

exposure_leaves: []           # all three already in valid_exposure_tag

mechanism_edges:
  - edge_id: usdinr_imported_input_cost
    from_node: USDINR
    to_node: exposure:usd_cost_share
    exposure_tag: fx:usd_cost_share
    relationship_type: INPUT_COST
    distance: 1
    derivation: AUTHORED
    confidence: <REQUIRED - no default>
    source_url: <REQUIRED>
    mechanism: >
      A company buying inputs invoiced in USD pays more rupees for the same
      quantity when the rupee depreciates. The effect is on the cost line and
      is immediate at the point of invoicing.

  - edge_id: usdinr_export_realization
    from_node: USDINR
    to_node: exposure:usd_revenue_share
    exposure_tag: fx:usd_revenue_share
    relationship_type: REVENUE_REALIZATION
    distance: 1
    derivation: AUTHORED
    confidence: <REQUIRED>
    source_url: <REQUIRED>
    mechanism: >
      A company billing in USD realises more rupees per unit sold when the
      rupee depreciates.

  - edge_id: usdinr_foreign_currency_debt
    from_node: USDINR
    to_node: exposure:usd_debt_share
    exposure_tag: fx:usd_debt_share
    relationship_type: FX_TRANSLATION
    distance: 1
    derivation: AUTHORED
    confidence: <REQUIRED>
    source_url: <REQUIRED>
    mechanism: >
      A USD-denominated liability is worth more rupees when the rupee
      depreciates. The effect lands on the balance sheet and, through
      restatement, on the P&L below EBITDA.

section_labels:
  usdinr_imported_input_cost:    IMPORTED INPUT COSTS
  usdinr_export_realization:     EXPORT REALISATION
  usdinr_foreign_currency_debt:  FOREIGN CURRENCY DEBT

nodes: []                     # NONE. FX exposure is balance-sheet-determined;
                              # no industry implies it. This is the only family
                              # in the design with an empty layer 6.
```

**Note for the implementer:** the three existing sector-flavoured labels
(`it_export_realization`, `pharma_export_realization`, `import_cost_inflation`,
`electronic_import_cost`) are **not** reused. This feed's sections are keyed on the
exposure, so the labels must be sector-neutral or an FMCG importer renders under
"ELECTRONICS IMPORTS".

---

## 5. THE 20 COMPANIES

Direction is a **pure function of (leaf, shock direction)** — no per-company
judgement. On rupee **depreciation**: cost leg NEGATIVE, revenue leg POSITIVE, debt
leg NEGATIVE. Invert throughout on appreciation.

Every excerpt below is in `backend/scripts/probes/_v2_clean.tsv` at the same
`(leaf, ticker)` key, extracted verbatim from the cited page.

### 5.1 NEGATIVE — 11

| # | ticker | leg | p | excerpt |
|---|---|---|---|---|
| 1 | AARTIIND | COST | 185 | *"Exposures … arise on account of the various assets and liabilities which are denominated in currencies other than Indian Rupee"* |
| 2 | BALKRISIND | COST | 234 | *"Consumption of Raw Materials is arrived at after adjusting … imported raw materials"* |
| 3 | COLPAL | COST | 284 | *"changes in foreign currency values that impact costs of imported raw material"* |
| 4 | COSMOFIRST | COST | 111 | *"policy is to hedge material foreign exchange risk associated with borrowings, highly probable forecast sales and purchases"* |
| 5 | SIRCA | COST | 124 | *"The Company make significant amount of purchases in foreign currency which exposes th[em]"* |
| 6 | XPROINDIA | COST | 127 | *"major borrowings are in foreign currency and also purchases are made in foreign currency"* |
| 7 | **SCHAEFFLER** | **COST (net)** | 138 | *"Imports are higher than exports and hence the Company has foreign currency exposure to the extent of imports being higher than exports."* — **see §6** |
| 8 | HUHTAMAKI | DEBT | 90 | *"availed External Commercial Borrowings from Huhtamaki Finance Company V B.V., Netherlands"* |
| 9 | JKTYRE | DEBT | 57 | *"rebalanced its borrowing mix … including foreign curr[ency]"* |
| 10 | SRF | DEBT | 142 | *"designates non derivative financial liabilities, such as foreign currency borrowings from banks, as hedging instruments"* |
| 11 | ASAHIINDIA | DEBT | 227 | *"foreign currency interest rate swaps to mitigate foreign currency and interest rate risk on foreign currency loan"* |

### 5.2 POSITIVE — 4

| # | ticker | leg | p | excerpt |
|---|---|---|---|---|
| 12 | BRITANNIA | REV | 123 | *"The Company has export sales (2% to 3% of total sales) primarily denominated in US dollars and Euro."* |
| 13 | MRF | REV | 151 | *"Earnings in Foreign Exchange: FOB Value of Exports"* |
| 14 | POLYPLEX | REV | 248 | *"exposure to the risk of changes in foreign exchange rates also relates to the Company's operating activities (when revenue …)"* |
| 15 | SONACOMS | REV | 120 | *"designates certain hedging instruments … as cash flow hedges to mitigate foreign currency exchange risk arising from certain highly probable sales transactions denominated in foreign currency"* |

### 5.3 MIXED — 5

| # | ticker | legs | p | excerpt |
|---|---|---|---|---|
| 16 | GANDHAR | COST + REV | 178 | *"currency risk mainly on account of its import payables, short term borrowings and export receivab[les]"* |
| 17 | PANAMAPET | COST + REV | 155 | *"currency risk mainly on account of its import payables and export receivables"* |
| 18 | SOTL | COST + REV | 179 | *"exposed to currency risk mainly on account of its import payables and export receivables"* |
| 19 | BHARATFORG | REV + DEBT | 179 | *"exposure … relates primarily to its export revenue and long-term foreign currency borrowings"* |
| 20 | TIINDIA | COST + REV + DEBT | 64 | *"forex exposure … arise through trade transactions, namely, exports and imports, import of capital items besides short-term and long-term foreign currency borr[owings]"* |

**All 5 are MIXED *by finding*, not by construction** — each company's own filing names
both legs in one sentence. Per `FAMILY_MANIFEST_DESIGN` §4A they are **grade C and
therefore exempt from the MIXED-per-section cap.** They are the most informative rows
in the feed.

### 5.4 Not published

| | n | why |
|---|---|---|
| **EXAMINED_CONTRADICTS** | 1 | Goodyear — §7 |
| **EXAMINED_SILENT** | 42 | swept, no usable FX leg. Publish nothing, **and must reject as `NOT_SIZED`, not `NO_MATERIAL_IMPACT`** |
| MARGINAL, not promoted | 2 | CRAFTSMAN, UNOMINDA — candidate found, too weak to approve |

---

## 6. `NET_DISCLOSED` — a state the corpus produced that the design does not have

**SCHAEFFLER**, p138:

> *"Imports are higher than exports and hence the Company has foreign currency exposure
> to the extent of imports being higher than exports."*

That company carries **both** legs — and its filing states **which side dominates**,
with no number. Under the current design it would publish MIXED. The filing says it is
net negative.

**Recommendation: a fourth pass-through-adjacent state, `NET_DISCLOSED`**, carrying
the dominant leg. It resolves MIXED → direction on filed evidence, with no magnitude,
and it is exactly the qualitative-tier pattern: the company answers the question we
cannot compute.

**Scope decision for this ticket:** ship Schaeffler as **NEGATIVE** with the excerpt
rendered, and record `NET_DISCLOSED` as the reason. If the reviewer prefers to defer
the state, ship Schaeffler as MIXED — the excerpt still renders and nothing is
falsified, only under-informative. **Do not ship it as MIXED silently.**

n=1. Not a rate. Recorded so the next corpus is swept for it.

---

## 7. GOODYEAR — the exclusion path

Live proof the exception handler works, and the only worked example in the system.

| step | |
|---|---|
| **membership would say** | tyre maker → any crude or FX story → NEGATIVE |
| **the sweep found** | `fx:usd_cost_share`, passing the same patterns that admit the other ten |
| **the sentence** (p100) | *"The company has limited exposure to foreign exchange risk due to low reliance on imported raw materials and thus the company does not hedge for the foreign currency exposure and rely on natural hedging to the extent possible."* |
| **reviewer sets** | `member_evidence = EXAMINED_CONTRADICTS`, `pass_through_state = DISCLOSED_IMMATERIAL` |
| **published as** | **not a company row.** A line in the section's coverage note |
| **rendered** | *"1 company in this section discloses low exposure and is excluded"* — with the excerpt and page on click |
| **NOT rendered as** | absent (that is D11), or NEGATIVE (that is false), or `NO_MATERIAL_IMPACT` (that asserts we measured) |

**The distinction that makes this defensible:** Goodyear is excluded on **its own
disclosure**, cited. Every other unpublished company is excluded because it said
nothing. `member_evidence` is the only field that tells those apart, which is why §3
is not optional.

---

## 8. END TO END — what a rupee story renders

Input: *"Rupee slips past 88 against dollar on sustained FII outflows."*

1. **Event → shock.** A model proposes `USDINR`, sign `UP` (depreciation), from the
   closed 15-variable list. **The single human judgement in the feed**
   (`MEMBERSHIP_CLAIM_ASSESSMENT.md` §3.1 points 1–2). Everything downstream is
   deterministic.
2. **Discovery.** `traverse` walks `USDINR` → 3 edges → 3 leaves.
   `query_exposure_index` returns the companies carrying each leaf. **No distance
   threshold applies** — qualitative rows have no `share_of_base` (see §9).
3. **Per company.** One CHANNEL signal per leaf held, `materiality = NOT_SIZED`,
   `direction` from the leaf, `mechanism_id` from the edge, `sensitivity = None`.
4. **Reducer.** A company on one leg takes that direction. A company on opposite legs
   folds to MIXED (invariants 8/9, unchanged). `sign_consistency` is the channel-count
   ratio over equal ordinal weights.
5. **Gate.** Qualitative tier: `NOT_SIZED` admitted, `mechanism_id` required, grade
   C/D. PRIMARY and SECONDARY_RIPPLE unreachable.
6. **Sections.** 3, keyed `(tier, effect, mechanism_id, horizon)`. Ordering per
   `MEASUREMENTS` §E: tier → min graph distance → filing-cited count → alphabetical.
7. **Prose.** Numeral-free templates. The firewall's record set carries only
   `graph_distance` and `sign_consistency`.

```
QUALITATIVE — IMPORTED INPUT COSTS                         negative · 7 companies
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

**And the 42 that must NOT say `NO_MATERIAL_IMPACT`:** each rejects with `NOT_SIZED`,
lands in `DATA_GAP_REASONS`, and is counted in the coverage note as a company whose
filing was read and was silent on FX — **not** as a company assessed and found
unaffected. That sentence is the whole of D11 and D11.1 in the output.

---

## 9. Open items an implementer will hit

1. **`exposure_index` hardcodes `WHERE e.share_of_base >= 0.02`** (migration 0013) and
   discovery reads only that view. A qualitative row has no share. **A companion view
   is required or this feed is invisible to discovery.** Named in
   `QUALITATIVE_TIER_DESIGN.md` §A.1 #21; not solved here.
2. **`engine._prior` returns `0.0` for share-less candidates** (D14) — they are evicted
   first when the pool overflows. 20 companies will not overflow a 250 pool, so this
   is dormant for this feed and must be fixed before a larger one.
3. **`fx:usd_debt_share` is the weakest leaf** — and ASIANPAINT's candidate is a **JPY**
   ECB against a leaf that says USD. Excluded from the 20. The leaf needs either a
   currency-general rename or an extractor that refuses non-USD.
4. **Britannia's excerpt contains "2% to 3%".** The firewall would pass it — the
   numeral traces to a stored record — and it **must not be rendered.** The qualitative
   templates are numeral-free by construction; do not add a `{share}` variable to
   "improve" the sentence.
5. **`NET_DISCLOSED`** — §6, decision required.
