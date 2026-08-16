# NEWSFLO V5 — ADDENDUM A
## Ripple coverage: making indirect and second-order discovery systematic

**Attaches to:** `NEWSFLO_V5_BUILD_SPEC.md` §6 (Exposure Tag Index), §10 (Empirical Cross-Check).
**Problem being solved:** the system finds direct companies and misses ripple families. §6 fixed the *mechanism* of discovery. This addendum fixes *coverage*, which is the part that actually determines recall.

---

# A1. RECALL IS A PRODUCT, NOT A FEATURE

```
ripple_recall  ≈  V  ×  M  ×  C  ×  G

V = shock-variable coverage      — do we model the economic variable this event moves?
M = mechanism-edge coverage      — does a path exist from that variable to an exposure tag?
C = company-tagging coverage     — are companies tagged with that exposure in the ledger?
G = gate survival                — do ripple candidates survive the publication gates?
```

Each is a separate build project with a separate owner. If M is 55%, nothing you do to C or the prompts matters. **Measure all four independently** (§A6) — a single aggregate "recall" number will hide which one is broken.

Today the system is roughly: V high, **M low**, C near zero, G untuned. That ordering explains the observed behaviour exactly — direct companies come from article mentions and need none of V/M/C, so they work; everything else needs all four, so nothing else works.

---

# A2. AXIS M — BOOTSTRAPPING MECHANISM EDGES FROM INPUT–OUTPUT TABLES

Hand-authoring `variable → mechanism → exposure_tag` edges across the economy does not converge. Bootstrap from published inter-industry data instead.

### A2.1 Source

India's **Supply-Use Tables / Input-Output Transaction Tables** (MOSPI; RBI KLEMS for the industry-level series) give, for each industry pair, the value of industry A's output consumed as input by industry B. Normalised by B's total input, this is a direct input coefficient `a(A→B)` — the share of B's input cost that comes from A.

This is a complete, empirically grounded, government-published mechanism graph for the whole economy. It is the single highest-leverage dataset for this problem.

### A2.2 Pipeline

```
Supply-Use Table
      ↓  normalise to direct input coefficients a(A→B)
INDUSTRY INPUT MATRIX  (≈130 × 130)
      ↓  Leontief inverse (I − A)⁻¹  → total requirements, capturing indirect rounds
TOTAL REQUIREMENT MATRIX
      ↓  map NIC/IOTT industry codes → internal sector_id → exposure_tag
CANDIDATE MECHANISM EDGES  (with a quantitative coefficient, not a guess)
      ↓  human review: keep / discard / rename mechanism
CAUSAL GRAPH EDGES
```

The **Leontief inverse is the ripple engine you are missing.** Direct coefficients give you first-round exposure (paints buy petrochemicals). The inverse gives you total exposure including every indirect round (paints buy packaging which buys plastics which buys petrochemicals). That is literally second- and third-order economic transmission, computed rather than imagined.

### A2.3 Schema

```sql
CREATE TABLE io_coefficient (
  source_industry   text NOT NULL,      -- IOTT/NIC code
  target_industry   text NOT NULL,
  direct_coeff      numeric NOT NULL,   -- a(A→B)
  total_coeff       numeric NOT NULL,   -- from (I−A)⁻¹, includes indirect rounds
  table_year        int NOT NULL,
  source_url        text NOT NULL,
  PRIMARY KEY (source_industry, target_industry, table_year)
);

CREATE TABLE mechanism_edge (
  edge_id          uuid PRIMARY KEY,
  from_node        text NOT NULL,        -- economic variable or industry
  to_node          text NOT NULL,
  exposure_tag     text NOT NULL,        -- must exist in exposure_tags.yaml
  relationship_type text NOT NULL,       -- INPUT_COST|REVENUE_REALIZATION|DEMAND|...
  distance         int NOT NULL,
  io_total_coeff   numeric,              -- null for non-IO-derived edges
  derivation       text NOT NULL,        -- IO_TABLE|EMPIRICAL|AUTHORED
  reviewed_by      text,                 -- mandatory for IO_TABLE and EMPIRICAL
  confidence       numeric NOT NULL,
  effective_from   date, effective_to date
);
```

### A2.4 Rules

- IO tables are published with a multi-year lag and at industry granularity, so they are a **hypothesis generator, not a truth source**. Every IO-derived edge requires `reviewed_by` before it can publish. Coefficients inform the graph; they do not set company materiality — that still comes from the filed exposure ledger (§4).
- Prune aggressively: `total_coeff < 0.02` is noise at industry level. Keep the ranked top edges per source industry.
- IO tables model *cost structure*, so they generate INPUT_COST and DEMAND edges well. They do **not** generate REVENUE_REALIZATION, FX, rate, or regulatory edges. Those remain authored, and there are far fewer of them — a manageable hand-authored set of roughly 60–100 edges covering FX, rates, commodity realization, and policy channels.

---

# A3. AXIS M (SECOND SOURCE) — REVERSE EVENT STUDIES

The §10 event-study infrastructure was specified as a *checker*. Run it in reverse and it becomes your blind-spot detector.

### A3.1 Procedure

For each shock variable `V` and sign:

1. Compute CAR (+1d, +5d, +20d) for **every listed company**, not just candidates, across all historical shock instances of `V`.
2. Aggregate by industry: median CAR, IQR, n, sign consistency across events, p-value.
3. Retain industries with `n ≥ 15`, `p < 0.05`, and consistent sign in ≥65% of instances.
4. Diff against what the current graph can reach for `V`.

```
INDUSTRIES EMPIRICALLY REACTING TO  crude ↑
  ✓ explained by graph : upstream, refining/marketing, aviation, lubricants
  ✗ UNEXPLAINED        : paints, tyres, adhesives, packaging films, city gas
                          ← these are your coverage gaps, ranked by |median CAR| × n
```

The unexplained set is a **prioritised work queue for graph authoring**. This is how you stop discovering gaps by reading complaints and start discovering them systematically.

### A3.2 The discipline that keeps this honest

An empirically-discovered relationship **may never publish until a named mechanism exists.** The workflow is:

```
empirical signal  →  gap queue  →  human/LLM proposes mechanism
                                →  mechanism reviewed & authored as edge
                                →  companies tagged in ledger (§4)
                                →  now publishable, with a mechanism to show the user
```

Skipping the middle steps turns the product into a correlation miner. A ripple company published with a CAR statistic and no mechanism is exactly the "faulty finding" a senior analyst would destroy you for — *"you're showing me a chart, not a reason."*

**Hard rule: `SECONDARY_RIPPLE` requires a non-null `mechanism_id`. No exceptions, no empirical-only publication.**

---

# A4. AXIS C — TAGGING COMPANIES FOR RIPPLE EXPOSURE

The Phase 1 ledger plan (Nifty 200, filed exposures) is biased toward *large direct* names. Ripple families are often mid-caps. Adjust:

### A4.1 Tag-first, not company-first

Instead of "populate exposures for the Nifty 200," work tag by tag:

```
for each high-traffic exposure_tag:
    enumerate the industries carrying it (from IO matrix)
    enumerate listed companies in those industries with ADV ≥ threshold
    extract share_of_base from filings for each
    target ≥80% of the industry's listed market cap tagged
```

This guarantees that when a mechanism fires, the sector materialises *as a family* rather than as the two names that happened to be in the ledger. A half-populated tag is worse than an empty one — it produces a section containing Asian Paints and nothing else, which reads as an error rather than an analysis.

### A4.2 Priority tag order (India, by event frequency)

1. `input:crude_derivative_petchem` — paints, adhesives, plastics, packaging
2. `input:crude_derivative_rubber` — tyres, belts, footwear
3. `input:atf` — aviation
4. `input:freight_diesel` — logistics, FMCG distribution, e-commerce
5. `fx:usd_revenue_share` / `usd_cost_share` — IT, pharma, electronics importers
6. `input:metals:steel_flat` — autos, appliances, capital goods
7. `rate:floating_debt_share` — leveraged infra, real estate, NBFC
8. `input:agri:palm_oil` — FMCG, soaps, food
9. `input:fuel_furnace_pet_coke` — cement, ceramics, glass
10. `revenue:*` realization tags — commodity producers

### A4.3 Sector-proxy fallback, used honestly

Where company-level extraction is not yet done, a sector median from the IO matrix may populate `share_of_base` with `measurement = MODELLED`, `param_source = SECTOR_PROXY`. Per §7.4 this caps the candidate at `SECONDARY_RIPPLE` and evidence grade C. That is the correct outcome: it gives you ripple *breadth* immediately while structurally preventing a proxy-based number from ever masquerading as a primary call. Show it in the UI as *"sector-level estimate"* rather than a company-specific figure.

---

# A5. AXIS G — TUNING GATES SO RIPPLES SURVIVE

Precision gates calibrated for PRIMARY will silently kill ripple recall. Ripple candidates characteristically have smaller ΔEBITDA, weaker evidence, and proxy parameters. Separate the thresholds explicitly.

### A5.1 Ripple-specific configuration

```yaml
# config/gates.yaml
primary:
  materiality_floor_pct: 2.0
  max_distance: 2
  min_sign_consistency: 0.90
  allow_sector_proxy: false
  min_evidence_grade: C

secondary_ripple:
  materiality_floor_pct: 0.75     # lower than primary — small but real is still tradeable
  max_distance: 3
  min_sign_consistency: 0.60
  allow_sector_proxy: true         # with UI labelling
  min_evidence_grade: D
  require_mechanism_id: true       # A3.2 — non-negotiable
  min_companies_per_section: 1
```

### A5.2 Sector coherence rule

If a mechanism fires and ≥3 companies in an industry clear the ripple gate, publish the **section**. If only one clears while peers were rejected on data gaps rather than on economics, prefer publishing the section with a coverage note over publishing a lone name:

> **SECONDARY — TYRES & RUBBER** · negative on synthetic rubber and carbon black cost
> Apollo Tyres, CEAT, JK Tyre · *2 further names in this sector lack company-level input data*

Admitting a coverage gap is more credible than presenting partial coverage as complete.

### A5.3 The precision guardrail

Every ripple threshold loosening must be re-run against the eval corpus, including the 50 null events. **SECONDARY precision floor of 0.80 is not negotiable for recall gains.** If loosening a threshold buys 5 points of recall and costs 3 points of precision, reject it — the failure mode of this product category is a feed full of tenuous names that users learn to ignore.

---

# A6. THE COVERAGE AUDIT HARNESS

Ripple coverage must be *measured*, or it will regress silently as data ages.

### A6.1 Expected-ripple map

For 12–15 canonical shock classes, a domain expert authors the ripple families that a competent analyst would expect to see. Stored as fixtures, versioned, reviewed. Example:

```yaml
- shock: {variable: BRENT_CRUDE, sign: UP, magnitude_pct: 6}
  expected_primary:   [upstream_oil, oil_marketing, aviation]
  expected_ripple:    [paints, tyres, adhesives, packaging_films, city_gas,
                       logistics, specialty_chemicals]
  expected_macro:     [inr, imported_inflation, cad]
  expected_marginal:  [cement, ceramics]     # acceptable either way — not counted
  expected_absent:    [banks_direct, it_services]  # false positives if present
```

`expected_marginal` matters. Cement on crude is genuinely 0.5–1.5% of EBITDA; scoring it as a mandatory hit would push you to loosen thresholds and import false positives. Marginal families are excluded from both numerator and denominator.

### A6.2 Per-axis diagnostics

The harness reports **which axis failed**, per missing family:

```
MISSING: tyres
  V shock variable modelled ............ ✓
  M mechanism edge exists .............. ✗  no edge crude → carbon_black → input tag
  C companies tagged ................... ✗  0/6 tagged
  G would have passed gates ............ n/a
  → ROOT CAUSE: mechanism gap (M). Owner: graph. Priority: high (7 listed names, ₹X cr mcap)
```

This turns "the system misses ripples" into a specific, assignable ticket. That single change in feedback quality is worth more than any prompt improvement.

### A6.3 Continuous coverage metrics

Add to the §17 dashboard:

| Metric | Target |
|---|---|
| Ripple family recall (vs expected-ripple map) | ≥ 0.80 |
| Ripple company recall within surfaced families | ≥ 0.70 |
| Sections with only 1 company where peers exist untagged | ≤ 10% |
| Unexplained empirical industries (A3 gap queue depth) | trending down |
| Tag coverage: % of industry mcap tagged, per priority tag | ≥ 0.80 for top-10 tags |
| `SECONDARY_RIPPLE` published without `mechanism_id` | **0** (hard) |

---

# A7. REVISED PHASING

Insert into the main spec's phase plan:

**Phase 3 (revised) — Ripple materialization**
- 3a. Exposure Tag Index + discovery rewrite *(as specified in §6)*
- 3b. IO table ingestion → Leontief inverse → candidate mechanism edges → human review pass
- 3c. Tag-first ledger population for the top-10 priority tags to ≥80% industry mcap
- 3d. Reverse event-study gap queue
- 3e. Coverage audit harness + expected-ripple map for 12 shock classes
- 3f. Ripple-specific gate configuration and tuning against the eval corpus

**Gate:** ripple family recall ≥ 0.80 on the expected-ripple map with SECONDARY precision ≥ 0.80 maintained; every published ripple carries a mechanism_id; the per-axis diagnostic reports zero unexplained M-gaps for the top 5 shock classes.

---

# A8. THE DIRECT ANSWER

Will the V5 spec plus this addendum find all types of direct, indirect and rippled companies?

**It will find every ripple family for which a mechanism edge and tagged companies exist, deterministically and repeatably — which is a categorical improvement over an LLM being asked to remember.** The failure mode changes from *"the model didn't think of tyres"* (invisible, unfixable, recurring) to *"tag `crude_derivative_rubber` has 0/6 companies tagged"* (visible, assignable, permanently fixed once done).

It will not be complete on day one, and any design claiming otherwise is lying about a data-coverage problem. What it will be is **measurably incomplete** — you will know exactly which families you miss, why, and what it costs to fix each one. Coverage then rises monotonically and never silently regresses, because the audit harness fails the build when it does.

That is the honest version of the goal: not a system that knows everything, but one that knows precisely what it doesn't know, and shows the user the difference.
