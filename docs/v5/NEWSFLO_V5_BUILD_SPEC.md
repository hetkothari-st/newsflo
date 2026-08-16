# NEWSFLO V5 — DEFENSIBILITY ARCHITECTURE
## Implementation specification for Claude Code

**Status:** authoritative build target. Supersedes V4 corrective implementation.
**Reading order:** §0 → §1 → §2, then implement in the phase order of §16.
**Prime directive:** every published statement must be *reconstructible* from stored structured records. If a sentence cannot be regenerated from the database without an LLM inventing anything, it must not ship.

---

# §0. THE GOAL, CORRECTLY STATED

The previous target — "no analyst can ever find a faulty finding" — is unachievable and must not be encoded as a requirement. Two senior analysts disagree about the same event daily. Directional wrongness is irreducible.

Replace it with the achievable standard:

> **No published claim may ever be indefensible.**

A claim is **indefensible** if any of the following are true:

| Failure | Description |
|---|---|
| `FABRICATED` | Contains a number, quote, date, or company fact with no stored provenance |
| `MECHANISM_INVALID` | The causal path does not physically/economically transmit to that company |
| `OFFSET_IGNORED` | A known, registered counter-channel was not considered |
| `REGIME_IGNORED` | A policy/regulatory modifier that inverts or caps the effect was not applied |
| `SELF_CONTRADICTORY` | Two fields of the same record imply opposite directions |
| `FALSE_PRECISION` | Confidence or magnitude asserted beyond what the parameter uncertainty supports |
| `ENTITY_WRONG` | Exposure sits in an unlisted subsidiary, a different listco, or a delisted entity |
| `STALE` | Underlying exposure data is older than its declared freshness horizon |

A claim that is **wrong but defensible** is acceptable and expected. A claim that is **right but indefensible** must still be blocked — it is luck, not a system.

Every gate, test, and metric in this document exists to make indefensible output *structurally impossible to persist*, not merely discouraged by prompt instructions.

---

# §1. ROOT-CAUSE DIAGNOSIS OF THE CURRENT SYSTEM

The current snapshot lists 21 symptoms. They reduce to **six root causes**. Fix the causes, not the symptoms.

### RC-1 — There is no single owner of truth
*Symptoms: Oil India bearish/bullish/positive simultaneously; DIRECT EXPOSURE · RIPPLE; stale worker mutation.*

Multiple stages each write their own version of "what happens to this company." Nothing folds them. Fix: **§7 Canonical Reducer + single-writer enforcement at the database privilege level.**

### RC-2 — Materiality is a vibe, not a computation
*Symptoms: identical confidence across candidates; HIGH/MEDIUM/LOW unanchored; no calibration.*

The system asks an LLM "how material is this?" An LLM cannot know that ONGC's realization is capped or that Asian Paints' crude-derivative input share is ~28% of RM cost. Fix: **§4 Company Exposure Ledger + §5 Sensitivity Engine**, computing ΔEBITDA from filed financials.

### RC-3 — Recall is being asked of a language model instead of an index
*Symptoms: paints, tyres, cement missing despite graph mechanisms existing.*

Discovery is anchored on companies *mentioned in the article* plus whatever the model recalls. Petrochemical feedstock exists as a graph node with no way to enumerate the companies attached to it. Fix: **§6 Exposure Tag Index** — mechanism→company becomes a deterministic query over precomputed tags.

### RC-4 — Time and regime are collapsed into a single scalar
*Symptoms: Reliance MIXED is right but arrived at by accident; OMC direction unstable; internal contradiction.*

"Crude up → OMC negative" is true for marketing margin at T+1 and false for inventory valuation at T+1, and both are dominated by whether the government permits a price revision. Fix: **§8 Horizon Vector + §9 Policy Modifier Registry.**

### RC-5 — Prose is generated freely and evidence is attached afterwards
*Symptoms: pass-through timing / pricing power / balance-sheet claims with zero evidence support.*

The LLM writes sentences, then the system tries to justify them. This ordering can never be made safe. Fix: **§11 Claim Compiler + Entailment Firewall** — prose is *compiled from records*, and any sentence not entailed by the record is deleted before persistence.

### RC-6 — Nothing ever tries to prove the system wrong
*Symptoms: no calibration, no empirical grounding, high-confidence weak claims.*

Every stage is a confirmer. Fix: **§10 Empirical Cross-Check (event studies)** and **§12 Falsification Stage** — components whose objective function is to *destroy* candidates.

---

# §2. THE THREE INDEPENDENT AXES

Both prior architectures separate fundamental impact from market reaction. That is necessary but insufficient. V5 requires **three** orthogonal axes that may never be collapsed, combined, or allowed to overwrite each other:

```
AXIS A — FUNDAMENTAL IMPACT
  What happens to this company's economics?
  Owner: Sensitivity Engine + Canonical Reducer
  Units: ΔEBITDA% (band), direction per horizon, materiality bucket

AXIS B — MARKET REACTION
  What did the stock actually do?
  Owner: Market Reaction Engine (read-only w.r.t. A)
  Units: excess move vs sector benchmark, volume z-score, significance

AXIS C — INFORMATION VALUE
  Is this news, or is it already known?
  Owner: Surprise Engine
  Units: surprise_score, novelty_score, consensus_gap, dissemination_stage
```

**Rules of engagement:**
- A must never read B. Ever. Enforced by module boundary + test.
- C must never modify A's direction or magnitude. C modulates *ranking, urgency, and UI prominence* only.
- Divergence between A and B is a **monitoring signal**, not an error. `A=POSITIVE, B=-1.4%` is either alpha or a bug; log it to a `divergence_review` queue with a threshold-based alert. Never resolve it silently.

The product promise is early-mover advantage. That promise lives in Axis C. A structurally correct impact call on a story that broke six hours ago and has been in the forward curve for a week is worth nothing, and the UI must say so rather than pretend otherwise.

---

# §3. TARGET PIPELINE

```
                          ┌──────────────── OFFLINE / BATCH ────────────────┐
                          │  Company Exposure Ledger      (§4)              │
                          │  Sensitivity Parameters        (§5)             │
                          │  Exposure Tag Index            (§6)             │
                          │  Policy Modifier Registry      (§9)             │
                          │  Event-Study Transmission Matrix (§10)          │
                          │  Calibration Model             (§13)            │
                          └─────────────────────┬───────────────────────────┘
                                                │ (read-only at runtime)
NEWS ──▶ INGEST ──▶ NORMALIZE ──▶ DEDUP ──▶ SOURCE RELIABILITY
   │
   ├──▶ FACT EXTRACTION ────────────────▶ facts[] (FACT|DERIVED|INFERENCE|UNKNOWN)
   │
   ├──▶ EVENT NORMALIZATION ────────────▶ Event (§3.2)
   │         │
   │         ├──▶ SURPRISE ENGINE ──────▶ Axis C  (§14)
   │         │
   │         └──▶ SHOCK RESOLUTION ─────▶ shocks[] (variable, Δ, units, horizon, confidence)
   │                   │
   │                   ▼
   │            CAUSAL GRAPH TRAVERSAL  (typed edges, bounded depth d≤3)
   │                   │
   │                   ▼
   │            ┌──────────────────────────────┐
   │            │  DISCOVERY  (recall-optimal) │
   │            │  1. direct mentions          │
   │            │  2. exposure-tag index query │◀── §6  ← THE RECALL FIX
   │            │  3. supply-chain edges       │
   │            │  4. peer/competitor closure  │
   │            └──────────────┬───────────────┘
   │                           │  candidate pool (bounded, ≤N per event)
   │                           ▼
   │            ENTITY RESOLUTION (ISIN-anchored, §4.4)
   │                           ▼
   │            SENSITIVITY ENGINE (§5) ──▶ channels[] with ΔEBITDA bands
   │                           ▼
   │            POLICY MODIFIERS (§9)  ──▶ channels transformed
   │                           ▼
   │            HORIZON RESOLUTION (§8) ──▶ direction per horizon
   │                           ▼
   │            EVIDENCE BINDING (§11.1) ──▶ claim-level provenance
   │                           ▼
   │            EMPIRICAL CROSS-CHECK (§10) ──▶ agree | conflict | no-data
   │                           ▼
   │            FALSIFICATION STAGE (§12) ──▶ objections[]
   │                           ▼
   │       ╔═══════════════════════════════════════╗
   │       ║   CANONICAL REDUCER  (§7)             ║  ← pure function, SINGLE WRITER
   │       ║   signals[] → CompanyImpact           ║
   │       ╚═══════════════════┬═══════════════════╝
   │                           ▼
   │            PUBLICATION GATE (§7.4) ──▶ PRIMARY | SECONDARY_RIPPLE | MACRO_CONTEXT | REJECTED
   │                           ▼
   │            DETERMINISTIC SECTION ENGINE (§15)
   │                           ▼
   │            CLAIM COMPILER + ENTAILMENT FIREWALL (§11)
   │                           ▼
   └──────────────────────▶  API  ──▶  UI
                                ▲
   MARKET REACTION ENGINE ──────┘  (Axis B — parallel, isolated, read-only)
```

### §3.2 Event record

```jsonc
{
  "event_id": "uuid",
  "event_type": "COMMODITY_PRICE_MOVE",
  "event_category": "SUPPLY_SHOCK",
  "event_cause": "GEOPOLITICAL",          // SUPPLY|DEMAND|POLICY|REGULATORY|GEOPOLITICAL|COMPANY_ACTION|MACRO_SURPRISE|MARKET_STRUCTURE|OTHER|UNKNOWN
  "event_status": "CONFIRMED",            // RUMOURED|REPORTED|CONFIRMED|OFFICIAL|RETRACTED
  "event_time": "2026-08-16T04:12:00Z",
  "effective_time": "2026-08-16T00:00:00Z",
  "geography_scope": "GLOBAL",
  "regions": ["MIDDLE_EAST"],
  "shocks": [
    {
      "shock_id": "uuid",
      "variable": "BRENT_CRUDE",
      "delta": 6.4,
      "delta_units": "PCT",
      "level_before": 74.20, "level_after": 78.95,
      "magnitude_confidence": 0.92,
      "persistence": "TRANSIENT",         // TRANSIENT|PERSISTENT|STRUCTURAL|UNKNOWN
      "source_fact_ids": ["..."]
    }
  ],
  "fact_ids": ["..."],
  "analysis_version": "v5.0.3",
  "surprise": { /* Axis C, §14 */ }
}
```

**Hard rule:** if `shocks[]` is empty or every shock has `magnitude_confidence < 0.5`, the event may produce `MACRO_CONTEXT` at most. No PRIMARY. No SECONDARY. A shock without a magnitude cannot produce a materiality number, and materiality is mandatory for company publication.

---

# §4. COMPANY EXPOSURE LEDGER  *(build this first — everything depends on it)*

This is the durable asset and the actual moat. It is **derived from filings, not from a language model.**

### §4.1 Schema

```sql
CREATE TABLE company (
  company_id      uuid PRIMARY KEY,
  isin            text UNIQUE NOT NULL,
  nse_symbol      text, bse_code text,
  legal_name      text NOT NULL,
  listed          boolean NOT NULL,
  parent_isin     text,                    -- holdco/subsidiary chain
  status          text NOT NULL,           -- ACTIVE|SUSPENDED|DELISTED|MERGED
  free_float_mcap numeric,
  adv_20d_inr     numeric,                 -- liquidity gate input
  updated_at      timestamptz NOT NULL
);

CREATE TABLE company_exposure (
  exposure_id      uuid PRIMARY KEY,
  company_id       uuid NOT NULL REFERENCES company,
  segment_id       uuid,                   -- null = consolidated
  exposure_kind    text NOT NULL,          -- INPUT_COST|REVENUE_REALIZATION|VOLUME_DEMAND|FX_TRANSACTION|FX_TRANSLATION|INTEREST_RATE|REGULATORY|LOGISTICS_ENERGY|CUSTOMER_CONCENTRATION
  exposure_tag     text NOT NULL,          -- controlled vocabulary, see §6.1
  share_of_base    numeric NOT NULL,       -- e.g. 0.28 = 28% of the relevant base
  base_kind        text NOT NULL,          -- COGS|REVENUE|EBITDA|TOTAL_COST|DEBT|OPEX
  base_value_inr   numeric NOT NULL,
  measurement      text NOT NULL,          -- FILED|DISCLOSED_CALL|ESTIMATED|MODELLED
  source_type      text NOT NULL,          -- ANNUAL_REPORT|QUARTERLY|EXCHANGE_FILING|EARNINGS_CALL|REGULATOR|EXCHANGE_DATA
  source_url       text NOT NULL,
  source_page      text,
  as_of_date       date NOT NULL,
  freshness_days   int NOT NULL,           -- beyond this the exposure is STALE
  confidence       numeric NOT NULL,
  created_by       text NOT NULL,          -- 'ingest:ar_parser_v3' | 'human:naman' | 'llm:claude-…'
  reviewed_by      text,
  CONSTRAINT no_selfcertify CHECK (
     measurement <> 'MODELLED' OR reviewed_by IS NOT NULL
  )
);

CREATE TABLE company_modifier (
  modifier_id    uuid PRIMARY KEY,
  company_id     uuid NOT NULL REFERENCES company,
  modifier_kind  text NOT NULL,   -- HEDGE|PASS_THROUGH|CONTRACT_FLOOR|PRICE_CAP|SUBSIDY_SHARE|WINDFALL_LEVY|TAKE_OR_PAY|FORMULA_PRICING
  applies_to_tag text NOT NULL,
  parameters     jsonb NOT NULL,  -- {"hedge_ratio":0.6,"tenor_months":9} etc.
  effective_from date NOT NULL,
  effective_to   date,
  source_url     text NOT NULL,
  as_of_date     date NOT NULL,
  confidence     numeric NOT NULL
);
```

### §4.2 Pass-through curve — a function, not a scalar

Pass-through is the single most abused parameter in impact analysis. Store it as a curve:

```jsonc
"pass_through": {
  "tag": "input:crude_derivative_petchem",
  "curve": [                        // cumulative fraction recovered
    {"lag_days": 0,  "fraction": 0.00},
    {"lag_days": 30, "fraction": 0.15},
    {"lag_days": 90, "fraction": 0.55},
    {"lag_days": 180,"fraction": 0.85}
  ],
  "basis": "DISCLOSED_CALL",
  "evidence_id": "…",
  "ceiling": 0.90                   // structural max, e.g. competitive limits
}
```

If no curve exists for a company, **do not default to a plausible number.** Use the sector median curve and mark the derived channel `param_source: SECTOR_PROXY`, which caps evidence grade at C and blocks PRIMARY (§7.4).

### §4.3 Bootstrapping the ledger (practical order)

Do not attempt full coverage. Build in this order:

1. **Tier 1 — Nifty 200 + all F&O names.** Parse: segment revenue/EBITDA (Ind AS 108 segment note), raw material consumed breakup, forex earnings & expenditure note, borrowings note (fixed vs floating), power & fuel cost line, employee cost. These are structured enough for a deterministic parser plus LLM extraction with human spot-review.
2. **Tier 2 — remaining NSE mainboard with ADV > ₹5cr.** Same, lower review intensity.
3. **Tier 3 — everything else.** Sector-proxy parameters only; permanently capped below PRIMARY.

Every exposure row must survive this question: *"Where in a filing does this number appear?"* If the answer is "the model believed it," it is `MODELLED` and requires `reviewed_by`.

### §4.4 Entity resolution rules (blocking failures)

- Resolve to **ISIN**, never to ticker or name string.
- If exposure sits in an **unlisted subsidiary**, the claim attaches to the listed parent **only if** consolidated segment data shows the exposure, and materiality is computed against consolidated EBITDA with the ownership fraction applied.
- **Holdco**: an operating impact on a subsidiary transmits to the holdco with a `HOLDCO_DISCOUNT` modifier and is capped at `SECONDARY_RIPPLE`.
- Name collisions across exchanges/countries (e.g. "Castrol" India vs plc) must fail closed with `ENTITY_AMBIGUOUS` → REJECT.
- Corporate actions (merger, demerger, name change) checked against effective dates. A claim on a merged-away entity is `ENTITY_WRONG`.

---

# §5. SENSITIVITY ENGINE — MATERIALITY AS A COMPUTED NUMBER

This replaces LLM-assigned HIGH/MEDIUM/LOW. **The LLM does not assign materiality in V5.**

### §5.1 Channel computation

For each `(company, shock, exposure)` triple, compute a **channel**:

```
COST CHANNEL
  ΔEBITDA_inr = − base_value_inr
                × share_of_base
                × shock_delta_pct
                × (1 − passthrough(horizon_days))
                × (1 − hedge_ratio_effective(horizon_days))
                × segment_ownership_fraction

REVENUE / REALIZATION CHANNEL
  ΔEBITDA_inr = + base_value_inr
                × share_of_base
                × shock_delta_pct
                × realization_elasticity
                × (1 − regulatory_capture_fraction)     // see §9
                × segment_ownership_fraction

VOLUME / DEMAND CHANNEL
  ΔEBITDA_inr = + revenue_base × demand_elasticity × shock_delta_pct × contribution_margin

FX / RATE CHANNELS — analogous, using net exposure after natural hedge.

materiality_pct = Σ_channels ΔEBITDA_inr / EBITDA_ttm
```

### §5.2 Uncertainty is mandatory — this is what makes it expert-proof

Every parameter carries a distribution, not a point:

```jsonc
{"param":"pass_through_90d","point":0.55,"lo":0.35,"hi":0.75,"dist":"triangular"}
```

Run **Monte Carlo (n=2000, seeded, deterministic per event+company+analysis_version)** over all parameters. Emit:

```jsonc
"materiality": {
  "delta_ebitda_pct": {"p10": -6.0, "p50": -3.2, "p90": -1.1},
  "sign_consistency": 1.00,        // fraction of draws sharing p50's sign
  "bucket": "MEDIUM",
  "driver_ranking": [              // sensitivity attribution — what moves the answer
     {"param":"pass_through_90d","contribution":0.61},
     {"param":"crude_share_of_rm","contribution":0.24}
  ]
}
```

**Bucketing (configurable, single source of truth in `config/materiality.yaml`):**

| `|p50| of ΔEBITDA%` | bucket |
|---|---|
| ≥ 5.0% | HIGH |
| 2.0 – 5.0% | MEDIUM |
| 0.5 – 2.0% | LOW |
| < 0.5% | NO_MATERIAL_IMPACT |

**The sign-consistency rule (critical):**

- `sign_consistency ≥ 0.90` → a directional claim is permitted
- `0.60 – 0.90` → direction is `UNCERTAIN`; may publish as SECONDARY at most, and the UI must show the band
- `< 0.60` with material magnitude on both sides → `MIXED`, never a direction

This single rule eliminates an entire class of expert objections. You can no longer say "negative" when your own parameter uncertainty puts 35% of the distribution above zero.

**`driver_ranking` is a product feature, not just diagnostics.** Surface it: *"This call is 61% driven by our pass-through assumption of 55%, sourced from the Q2 FY26 earnings call."* An analyst who disagrees can see exactly which lever to argue with. That is what respect looks like.

---

# §6. EXPOSURE TAG INDEX — THE RECALL FIX

The current system misses paints, tyres and cement because discovery cannot enumerate companies attached to a mechanism. That is an indexing problem.

### §6.1 Controlled exposure vocabulary

`config/exposure_tags.yaml` — hierarchical, versioned, closed set. Extending it is a code review, never a runtime LLM decision.

```yaml
input:
  crude:
    crude_direct:               # crude as literal input
    crude_derivative_petchem:   # naphtha, propylene, polymers  → paints, plastics, adhesives
    crude_derivative_rubber:    # synthetic rubber, carbon black → tyres
    crude_derivative_bitumen:   # roads, infra
    atf:                        # aviation turbine fuel
    fuel_furnace_pet_coke:      # cement, ceramics, glass
    freight_diesel:             # logistics, FMCG distribution
  metals: {steel_flat:, steel_long:, aluminium:, copper:}
  agri:   {palm_oil:, wheat:, sugar:, milk:}
revenue:
  crude_realization:            # upstream producers
  refining_gross_margin:
  marketing_margin_retail_fuel:
  gas_realization_apm:
  gas_realization_market:
fx:
  usd_revenue_share:
  usd_cost_share:
  usd_debt_share:
rate:
  floating_debt_share:
  nim_asset_sensitivity:
```

### §6.2 The index

```sql
CREATE MATERIALIZED VIEW exposure_index AS
SELECT exposure_tag, exposure_kind, company_id,
       share_of_base, base_value_inr, confidence, as_of_date
FROM company_exposure
WHERE share_of_base >= 0.02;              -- prune trivia at index level

CREATE INDEX ON exposure_index (exposure_tag, share_of_base DESC);
```

### §6.3 Discovery becomes a query

```python
def discover(event) -> list[Candidate]:
    pool = {}
    # 1. explicit mentions (must still pass all downstream gates)
    pool |= resolve_mentions(event.facts)

    # 2. mechanism materialization  ← fixes paints/tyres/cement permanently
    for shock in event.shocks:
        for edge in causal_graph.traverse(shock.variable, max_depth=3):
            for tag in edge.exposure_tags:
                for row in exposure_index.query(tag, min_share=THRESH[edge.distance]):
                    pool.add(row.company_id, source=DiscoverySource.MECHANISM,
                             tag=tag, distance=edge.distance)

    # 3. supply-chain closure (customer/supplier edges, 1 hop from pool)
    # 4. peer closure: if ≥2 members of a sector are in pool, sweep the sector at higher threshold
    return bound(pool, max_candidates=250, rank_by=expected_materiality_prior)
```

`THRESH[distance]`: d1 ≥ 0.02, d2 ≥ 0.05, d3 ≥ 0.10. Rationale — indirect claims must clear a higher exposure bar to be worth a user's attention.

**Discovery source is a first-class field, distinct from directness and from evidence source.** This kills the current `basis = direct_mention` bug in snapshot §15:

```jsonc
"discovery": {"source": "MECHANISM", "via_tag": "input:crude_derivative_rubber", "graph_distance": 2},
"directness":  "INDIRECT",     // structural property of the causal path
"evidence_source": "FILING"    // where the supporting proof came from
```

Three fields. Three meanings. Never merged.

---

# §7. THE CANONICAL REDUCER — ONE TRUTH PER COMPANY PER EVENT

### §7.1 Every stage emits *signals*, never verdicts

No stage writes a company's direction, tier, or confidence. Stages append immutable signals:

```jsonc
{"signal_id":"…","event_id":"…","company_id":"…",
 "stage":"SENSITIVITY|POLICY|HORIZON|EVIDENCE|EMPIRICAL|FALSIFICATION|VERIFIER",
 "kind":"CHANNEL|MODIFIER|OBJECTION|EVIDENCE_BINDING|EMPIRICAL_CHECK",
 "payload":{…},"created_by":"…","analysis_version":"v5.0.3","created_at":"…"}
```

### §7.2 The reducer is a pure function

```python
def reduce_company_impact(signals: list[Signal], config: Config) -> CompanyImpact:
    """Pure. Deterministic. No I/O. No LLM. Same input ⇒ byte-identical output."""
```

It is the **only** code path permitted to produce a `CompanyImpact`. It must be unit-testable in isolation with fixture signal sets, and there must be a property test asserting determinism across 10k random signal permutations (order-independence).

### §7.3 CompanyImpact — the canonical record

```jsonc
{
  "event_id":"…","company_id":"…","isin":"…",

  "fundamental": {
    "direction_by_horizon": {
      "IMMEDIATE":   {"direction":"POSITIVE","materiality":"MEDIUM","delta_ebitda_pct_p50": 2.6},
      "NEAR_TERM":   {"direction":"NEGATIVE","materiality":"MEDIUM","delta_ebitda_pct_p50": -3.1},
      "STRUCTURAL":  {"direction":"UNCERTAIN","materiality":"LOW","delta_ebitda_pct_p50": -0.7}
    },
    "headline_horizon":"NEAR_TERM",
    "net_effect":"MIXED",
    "sign_consistency":0.47,
    "channels":[ /* full channel list incl. offsets, each with evidence_ids */ ],
    "policy_modifiers_applied":["SAED_WINDFALL_LEVY","OMC_PRICE_FREEZE_ACTIVE"]
  },

  "causal": {
    "path":[{"from":"BRENT_CRUDE","to":"marketing_margin","type":"MARKETING_MARGIN","distance":1}],
    "directness":"DIRECT","graph_distance":1
  },

  "evidence": {"grade":"B","claim_bindings":[…],"weakest_link":"pass_through:SECTOR_PROXY"},

  "empirical": {"status":"AGREE","n_events":34,"median_car_5d":-1.4,"iqr":[-3.2,0.1],"p_value":0.03},

  "objections":[{"type":"ALREADY_PRICED","severity":"WARN","raised_by":"falsifier","sustained":false}],

  "confidence": {"calibrated_p": 0.71, "method":"isotonic_v3", "in_distribution": true},

  "tier":"SECONDARY_RIPPLE",
  "rejection_reason": null,
  "decision_trace_id":"…",
  "analysis_version":"v5.0.3",
  "reducer_version":"r5.0.1"
}
```

### §7.4 Publication gate — deterministic, config-driven, no LLM

Evaluate in order. First failure decides.

```
HARD BLOCKS (→ REJECTED, always):
  entity_status != ACTIVE
  entity_ambiguous
  any exposure STALE beyond freshness_days
  materiality bucket == NO_MATERIAL_IMPACT
  any objection with severity == BLOCKING and sustained == true
  any unbound claim (§11.3)
  shock magnitude_confidence < 0.5   → max tier MACRO_CONTEXT

PRIMARY requires ALL:
  graph_distance ≤ 2
  directness == DIRECT (d1) or (DIRECT|INDIRECT at d2 with materiality == HIGH)
  materiality ∈ {HIGH} or (MEDIUM and evidence_grade ∈ {A,B})
  evidence_grade ∈ {A,B,C} and weakest_link != SECTOR_PROXY
  sign_consistency ≥ 0.90 at headline_horizon
  empirical.status ∈ {AGREE, NO_DATA}          // CONFLICT blocks PRIMARY
  no sustained objection of severity ≥ MAJOR
  independent verifier == PASS
  liquidity: adv_20d_inr ≥ config.min_adv      // unactionable ⇒ not primary
  event_status ∈ {CONFIRMED, OFFICIAL}          // rumours never primary

SECONDARY_RIPPLE requires ALL:
  graph_distance ≤ 3
  materiality ∈ {HIGH, MEDIUM} or (LOW and evidence_grade ∈ {A,B})
  evidence_grade ∈ {A,B,C,D}
  sign_consistency ≥ 0.60  (else must be published as MIXED/UNCERTAIN)
  no sustained BLOCKING objection

MACRO_CONTEXT:
  mechanism-level only. No company list may be attached. Ever.

ELSE → REJECTED (with reason, retained for audit)
```

**Explicitly: failing PRIMARY does not demote to SECONDARY.** The secondary gate is evaluated independently from the same signals.

### §7.5 Single-writer enforcement — the stale-worker fix

Prompt discipline will not stop a legacy worker. Enforce at three levels:

1. **DB privileges.** `company_impact` is writable only by role `newsflo_reducer`. Every other service role gets `SELECT` only. Revoke and verify in a migration. The V4 incident becomes impossible, not merely detected.
2. **Version fencing.** `company_impact` carries `reducer_version` + `analysis_version` with a `CHECK` against a `supported_versions` table. Old code writing old versions is rejected by the database.
3. **Idempotency.** `UNIQUE (event_id, company_id, analysis_version)` and writes go through `INSERT … ON CONFLICT DO UPDATE WHERE excluded.reducer_run_seq > company_impact.reducer_run_seq`. Monotonic sequence prevents out-of-order overwrite under concurrency.

---

# §8. HORIZON VECTOR — RESOLVING THE OIL INDIA CONTRADICTION

A single direction per company is a modelling error. Emit three, always:

| Horizon | Window | Dominated by |
|---|---|---|
| `IMMEDIATE` | 0–5 trading days | inventory revaluation, sentiment, mark-to-market, hedging gains |
| `NEAR_TERM` | current + next quarter | margin transmission, pass-through lag, contract resets |
| `STRUCTURAL` | 2–4 quarters | capex, competitive position, demand destruction, substitution |

Each horizon runs its own channel computation with `passthrough(horizon_days)` and `hedge_ratio_effective(horizon_days)` evaluated at that horizon. This is why pass-through must be a curve (§4.2).

**Worked example — OMC on crude +6.4%:**

```
IMMEDIATE   : +  inventory gain on crude & product stock        → POSITIVE  (MEDIUM)
NEAR_TERM   : −  marketing margin squeeze (retail price frozen) → NEGATIVE  (HIGH)
STRUCTURAL  : ±  depends on price-revision permission           → UNCERTAIN (LOW)
net_effect  : MIXED,  headline_horizon = NEAR_TERM
```

`headline_horizon` selection rule: the horizon with the largest `|delta_ebitda_pct_p50| × materiality_weight`, tie-broken toward `NEAR_TERM`. UI leads with the headline horizon and shows the other two on expand. **The other horizons are never discarded** — discarding them is precisely how the current system produced three contradictory Oil India representations.

---

# §9. POLICY MODIFIER REGISTRY — THE INDIA-SPECIFIC KILLER

This does not exist in either prior document and it is the fastest way for a senior analyst to declare the system naive. Publishing "ONGC POSITIVE" on rising crude while ignoring the windfall levy and APM ceiling is an instant credibility loss.

### §9.1 Modifiers are transfer functions applied deterministically

They run **after** channel computation and **before** net-effect resolution. Never LLM-applied.

```yaml
# config/policy_modifiers.yaml
- id: SAED_WINDFALL_LEVY
  applies_to_tag: revenue:crude_realization
  jurisdiction: IN
  effective_from: 2022-07-01
  effective_to: null            # maintain actively; nullable if repealed
  type: THRESHOLD_CAPTURE
  parameters:
    threshold_usd_bbl: 75
    capture_fraction_above: 0.85   # govt captures ~85% of realization above threshold
    revision_frequency: FORTNIGHTLY
  source_url: "https://…cbic notification…"
  note: >
    Above the threshold, upstream realization upside is largely transferred to the
    exchequer. Crude upside for ONGC/OIL is materially capped and can invert on a
    net basis when combined with cost inflation.

- id: APM_GAS_CEILING
  applies_to_tag: revenue:gas_realization_apm
  type: HARD_CAP
  parameters: {ceiling_basis: "10% of Indian crude basket", cap_usd_mmbtu: 6.50}

- id: OMC_PRICE_FREEZE
  applies_to_tag: revenue:marketing_margin_retail_fuel
  type: STATE_DEPENDENT
  parameters:
    state_source: "policy_state.retail_fuel_revision_active"
    when_frozen: {pass_through_override: 0.0, duration_hint_days: 90}
  note: "Retail price revisions are administratively influenced; freeze windows collapse pass-through to zero."

- id: ATF_STATE_VAT
  applies_to_tag: input:atf
  type: REGIONAL_MULTIPLIER
```

### §9.2 Modifier types

| Type | Effect |
|---|---|
| `THRESHOLD_CAPTURE` | above a level, a fraction of the channel is transferred away |
| `HARD_CAP` | channel magnitude clipped at an administered ceiling |
| `STATE_DEPENDENT` | parameters overridden based on a tracked policy state variable |
| `SUBSIDY_SHARE` | loss/gain split across parties |
| `FORMULA_PRICING` | channel replaced by an administered formula |
| `REGIONAL_MULTIPLIER` | scaled by geography mix |

### §9.3 Non-negotiable rules

- Every modifier applied is recorded in `policy_modifiers_applied[]` and **surfaced in the UI**. Showing the analyst that you know about the windfall levy is worth more than the impact call itself.
- If a company has an exposure tag that has **any** registered modifier for the current date and the modifier's state variable is `UNKNOWN`, the channel's uncertainty band is widened by the configured factor and evidence grade is capped at C. Unknown regime ⇒ humility, not silence.
- `policy_state` (e.g. whether OMC price revisions are currently permitted, current SAED rate) is a maintained table with an owner and a staleness alert. If `policy_state` is stale past its horizon, affected companies cannot reach PRIMARY.

**Maintain at minimum, for India:** SAED/windfall levy on crude & product exports, APM/administered gas pricing, retail fuel price revision state, excise/VAT changes on fuel, export duties (steel, rice, sugar), import duties, PLI schemes, FRBM/borrowing calendar effects on rates, MSP announcements, sugar export quotas, telecom AGR/spectrum dues, banking risk-weight changes.

---

# §10. EMPIRICAL CROSS-CHECK — MAKING THE GRAPH FALSIFIABLE

The causal graph currently asserts relationships that are never tested. Build an event-study layer that says whether history agrees.

### §10.1 Transmission matrix (offline, rebuilt weekly)

1. Construct a historical shock series for each economic variable (crude, INR, repo, steel, palm oil, etc.) covering ≥8 years.
2. Define shock events: |move| > 1.5σ of the variable's daily distribution, deduplicated to one per 5-day window.
3. For every company × shock class, compute cumulative abnormal return (CAR) over +1d, +5d, +20d using a market-and-sector-adjusted model (Fama-French style or simple sector-beta residual — start simple, document the estimator).
4. Store the distribution:

```sql
CREATE TABLE transmission_empirical (
  company_id uuid, shock_variable text, shock_sign text, horizon text,
  n_events int, median_car numeric, iqr_lo numeric, iqr_hi numeric,
  p_value numeric, estimator_version text, computed_at timestamptz,
  PRIMARY KEY (company_id, shock_variable, shock_sign, horizon, estimator_version)
);
```

### §10.2 The check

```python
def empirical_check(impact, row) -> Literal["AGREE","CONFLICT","WEAK","NO_DATA"]:
    if row is None or row.n_events < 10:            return "NO_DATA"
    if row.p_value > 0.10:                           return "WEAK"
    return "AGREE" if sign(row.median_car) == sign(impact.headline_direction) else "CONFLICT"
```

### §10.3 How conflict is handled — carefully

`CONFLICT` **blocks PRIMARY** but does **not** auto-reject. Reasons:

- Empirical history can be dominated by a regime that no longer applies (pre-windfall-tax ONGC behaved differently).
- The market may have been wrong historically — that is literally the alpha the product claims to find.

So: `CONFLICT` → cap at `SECONDARY_RIPPLE`, attach an objection of severity `MAJOR`, and route to the review queue. If a human reviewer marks the conflict `REGIME_CHANGED` with a reason, PRIMARY becomes available for that shock class going forward.

This is also a strong UI feature: *"Our fundamental read is positive; in 34 comparable historical shocks this name's 5-day abnormal return was −1.4% (IQR −3.2 to +0.1). We are taking the other side of history here, and here's why."* No 20-year analyst dismisses that. It is exactly how they think.

---

# §11. CLAIM COMPILER + ENTAILMENT FIREWALL — THE ANTI-FABRICATION LAYER

This directly fixes snapshot §8 (specific claims about pass-through timing, pricing power, balance-sheet amplification generated with zero evidence).

### §11.1 Claims are records before they are sentences

```jsonc
{
  "claim_id":"…","company_id":"…","event_id":"…",
  "claim_type":"COST_EXPOSURE",   // controlled: COST_EXPOSURE|REVENUE_EXPOSURE|PASS_THROUGH|HEDGE|MATERIALITY|OFFSET|REGULATORY|TIMING|COMPETITIVE
  "fact_class":"DERIVED",         // FACT|DERIVED|INFERENCE|UNKNOWN
  "structured": {"tag":"input:crude_derivative_petchem","share_of_base":0.28,"base_kind":"COGS"},
  "evidence_ids":["ev_…"],
  "binding_status":"BOUND",       // BOUND|SECTOR_PROXY|UNBOUND
  "created_by":"sensitivity_engine"
}
```

**Binding rules:**
- `claim_type ∈ {PASS_THROUGH, HEDGE, COMPETITIVE, TIMING}` requires evidence of `source_type ∈ {ANNUAL_REPORT, QUARTERLY, EARNINGS_CALL, EXCHANGE_FILING}` naming that company. No exceptions. These are the four claim types the current system fabricates most.
- Any claim containing a numeral must trace to a stored numeric field. Numerals may not originate in generated text.
- `binding_status == UNBOUND` on any claim attached to a company ⇒ that company is `REJECTED` (hard block, §7.4).

### §11.2 Prose is compiled, not written

```
CompanyImpact + Claims  ──▶  Template renderer (deterministic)  ──▶  base prose
                                        │
                                        ▼
                        LLM rewrite pass (fluency ONLY)
                        Constraint: may not add facts, numbers,
                        entities, causal steps, or qualifiers.
                                        │
                                        ▼
                            ENTAILMENT FIREWALL
```

### §11.3 Entailment firewall

Split rewritten prose into sentences. For each sentence, verify it is entailed by `{CompanyImpact, Claims, Evidence}`:

1. **Deterministic checks first** (cheap, catch most): every numeral in the sentence must appear in the record set (within rounding tolerance); every company/entity name must be in the resolved entity set; every date must exist in the record set.
2. **LLM entailment judge** for semantic additions, run with the record set as context and a strict binary output. Never the same model instance that wrote the prose.

Any sentence failing either check is **deleted**, not rewritten. If deletion leaves the output below minimum viable length, fall back to the deterministic template prose verbatim. Log every deletion to `firewall_deletions` — a rising deletion rate is your early warning that a prompt or model change has degraded.

**Ship gate: firewall deletion rate on the eval corpus must be 0 for PRIMARY companies.**

---

# §12. FALSIFICATION STAGE — AN ADVERSARY, NOT A VERIFIER

The current "verifier" confirms. V5 adds a component whose objective is to **destroy** the candidate. Run it *before* the reducer, as a signal producer.

### §12.1 Objection taxonomy (controlled)

| Type | Default severity |
|---|---|
| `ENTITY_WRONG` | BLOCKING |
| `MECHANISM_INVALID` | BLOCKING |
| `EXPOSURE_NOT_IN_LISTCO` | BLOCKING |
| `OFFSET_IGNORED` | MAJOR |
| `REGIME_MODIFIER_MISSING` | MAJOR |
| `MAGNITUDE_IMMATERIAL` | MAJOR |
| `HORIZON_MISMATCH` | MAJOR |
| `EVIDENCE_STALE` | MAJOR |
| `ALREADY_PRICED` | WARN |
| `BASE_RATE_VIOLATION` | WARN |
| `SECOND_ORDER_OVERREACH` | WARN |

### §12.2 The mandatory analyst checklist

The falsifier must answer all ten, in structured form, with the record set in context. Unanswerable ⇒ objection.

1. Which exact business line or segment is exposed, and what share of consolidated EBITDA is it?
2. Which P&L or balance-sheet line moves, and in which direction?
3. What is the transmission lag, and what evidence sets it?
4. What contractual, hedging, formula-pricing, or regulatory mechanism blunts this?
5. Is the exposure inside the listed entity, or in an unlisted/JV/associate arm?
6. Is there an offsetting channel of comparable magnitude in the opposite direction?
7. Was this event already visible in forward curves, consensus estimates, or prior reporting?
8. Does the direction hold at all three horizons? If not, which dominates and why?
9. Is any parameter driving >50% of the result sourced from a sector proxy rather than the company?
10. If this event were reversed, would the claimed effect substantially reverse? (counterfactual)

### §12.3 Sustaining an objection

An objection is `sustained` unless a **rebuttal signal** exists that cites a specific record field or evidence id. Rebuttals are produced by the sensitivity/evidence stages, not by the falsifier itself, and not by free-form argument. Default is that the objection stands — the burden of proof sits on publication, which is the correct asymmetry for this product.

### §12.4 Model discipline

Run the falsifier with a **different prompt lineage and, where cost permits, a different model or provider** than the candidate generator. Correlated errors between generator and checker are the standard failure mode of LLM self-verification. Record `provider/model` on both; the eval harness must report precision separately for same-model vs cross-model verification runs.

---

# §13. CONFIDENCE AS A CALIBRATED PROBABILITY

Current confidence is an LLM-emitted number that is near-constant. Delete it.

### §13.1 Definition

`calibrated_p` = P(the published directional call at the headline horizon is judged CORRECT by expert review).

### §13.2 Method

Feature vector per candidate (all deterministic, no LLM score):

```
materiality_p50, band_width, sign_consistency, graph_distance, directness,
evidence_grade, weakest_link_kind, n_bound_claims, param_proxy_fraction,
empirical_status, empirical_n, empirical_p, objection_count_by_severity,
event_status, shock_magnitude_confidence, surprise_score, sector_id,
exposure_freshness_days
```

Fit **isotonic regression** (or logistic + Platt scaling — pick one, version it) on the labeled corpus (§17). Report:

- reliability diagram, per tier and per sector
- Expected Calibration Error (ECE) and Brier score
- **out-of-distribution detection**: if the feature vector lies outside the training manifold (simple Mahalanobis or isolation-forest gate), set `in_distribution=false`, and the gate caps the tier at SECONDARY_RIPPLE. Novel event types must not inherit confidence from unrelated history.

### §13.3 UI contract

Never show a bare number. Show the band and the driver:

> **NEGATIVE · NEAR TERM · −3.2% EBITDA (range −6.0% to −1.1%) · confidence 0.71**
> *Most sensitive to: pass-through assumption (55%, from Q2 FY26 call).*

---

# §14. SURPRISE ENGINE (AXIS C)

Answers "is this actually news?" — the first objection any professional raises.

```jsonc
"surprise": {
  "consensus_gap_sigma": 1.8,        // (actual − consensus) / historical σ, where consensus exists
  "forward_curve_implied": 0.4,      // fraction of the move already in futures/forwards pre-event
  "novelty_score": 0.85,             // 1 − max cosine similarity to events in prior 7d
  "dissemination_stage": "EARLY",    // EARLY|SPREADING|SATURATED  (source count × time since first report)
  "first_seen_at": "…",
  "latency_ms_from_first_seen": 41000,
  "information_value": 0.72          // composite, config-weighted
}
```

**Rules:**
- Axis C **never** alters direction or materiality. It is not a fundamental input.
- It drives feed ranking, an `ALREADY WIDELY REPORTED` badge, and the `ALREADY_PRICED` objection at WARN.
- `latency_ms_from_first_seen` is the product's core SLO. Instrument it end-to-end and put it on a dashboard. Define and enforce a budget: **p95 ≤ 90 seconds from first ingest to published impact** for events matching a cached shock template; degrade gracefully (publish event + macro context first, companies as they clear the gate) rather than blocking the feed on a slow candidate.

---

# §15. DETERMINISTIC SECTION ENGINE

Section identity is a pure function. LLMs have no role here.

```python
section_key = (publication_tier, economic_effect, mechanism_id, horizon_bucket)
```

Rendered label comes from `config/section_taxonomy.yaml`, keyed by `mechanism_id`. Ordering: tier → |median materiality| desc → alphabetical.

**Invariants (enforced by test):**
- A section may contain only companies whose `(tier, effect, mechanism, horizon)` matches its key exactly.
- `MIXED` companies get their own section. Reliance is never placed inside "NEGATIVE — OIL MARKETING & REFINING". This is snapshot §12's bug and it is a data-model fix, not a prompting fix.
- Empty sections are omitted. Never fabricate a section to look complete.
- The literal string "DIRECT EXPOSURE · RIPPLE" and any construction mixing directness with tier is banned; add a lint test asserting no UI string concatenates a directness value with a tier value.

**Zero-PRIMARY is a first-class, well-designed state.** Render explicitly:

```
NO PRIMARY IMPACT IDENTIFIED
We found no company with a direct, evidenced, material exposure to this event.
   • 3 second-order effects below  • 2 macro channels  • 14 candidates rejected (view)
```

Making rejection visible is a feature. It is the single clearest signal to a professional user that the system has judgement rather than enthusiasm.

---

# §16. IMPLEMENTATION PHASES

Ship in this order. Each phase has a gate; do not proceed until it passes.

### Phase 0 — Credibility floor *(highest value per unit effort)*
- Canonical Reducer as a pure function; all stages converted to signal emitters
- DB privilege lockdown + version fencing + idempotent upsert (§7.5)
- Claim records + binding rules + Entailment Firewall (§11)
- Ban directness/tier string mixing; separate `discovery.source` / `directness` / `evidence_source`
- **Gate:** zero fabricated numerals on the eval corpus; zero internal contradictions (single-truth property test passes); stale-worker write attempt is rejected by the database in an integration test.

### Phase 1 — Exposure Ledger
- Schema + annual-report/quarterly parsers + LLM extraction with human review workflow
- Tier 1 coverage: Nifty 200 + F&O universe
- Pass-through curves for the top 40 companies by expected coverage
- **Gate:** ≥90% of Tier 1 companies have ≥3 exposure rows with `measurement ∈ {FILED, DISCLOSED_CALL}`; a random sample of 50 rows spot-checked to source by a human at ≥95% accuracy.

### Phase 2 — Sensitivity Engine + Materiality
- Channel math, Monte Carlo bands, driver ranking, bucketing
- Remove LLM materiality assignment entirely
- **Gate:** materiality reproduces hand-computed values on 20 worked examples within tolerance; confidence values are no longer near-constant (variance test).

### Phase 3 — Exposure Tag Index + Ripple Materialization
- Tag vocabulary, materialized index, discovery rewrite
- **Gate:** the crude-shock regression test surfaces paints, tyres, and cement candidates; SECONDARY recall on the eval corpus ≥ 0.70.

### Phase 4 — Policy Modifiers + Horizon Vector
- Registry, `policy_state` table with owner and staleness alerts, transfer functions
- Three-horizon computation and headline selection
- **Gate:** ONGC on crude +6% correctly reflects the windfall levy and does not print naive POSITIVE·HIGH; OMC produces the MIXED horizon split of §8.

### Phase 5 — Empirical Cross-Check + Calibration
- Event-study pipeline, transmission matrix, conflict handling, review queue
- Calibration fit + reliability diagrams + OOD gate
- **Gate:** ECE ≤ 0.05 on holdout; every CONFLICT is either downgraded or human-annotated.

### Phase 6 — Falsification + Review Console
- Adversarial stage with cross-model discipline, checklist, rebuttal logic
- Reviewer UI: event, candidates, rejected set, evidence, causal paths, one-click labels
- **Gate:** PRIMARY precision improves or holds while false-positive rate drops on holdout.

### Phase 7 — Eval harness, monitoring, SLO
- Full metric suite in CI, drift monitors, divergence queue, latency dashboard
- **Gate:** all §17 shipping gates green; no release may merge that regresses PRIMARY precision.

---

# §17. EVALUATION AND SHIPPING GATES

### §17.1 The corpus (build this in parallel with Phase 1 — it is the bottleneck)

- **300 historical events**, stratified: commodity, policy/regulatory, company action, macro data, geopolitical, earnings, and **50 null events** (financial news with no material listed-company impact — the single most valuable adversarial slice).
- Labels per company: `CORRECT | WRONG_COMPANY | WRONG_DIRECTION | WRONG_MECHANISM | WRONG_MATERIALITY | WRONG_TIER | WRONG_SECTION | INSUFFICIENT_EVIDENCE | DISPUTED`
- **Two independent labelers minimum**, with Cohen's κ reported. Disagreements go to `DISPUTED` and are excluded from precision denominators but tracked separately — an honest system reports its own ambiguity rate.
- Labelers must see the *event only* when producing expected sets, to avoid anchoring on system output.

### §17.2 Shipping gates (all must pass; CI-enforced)

| Metric | Gate |
|---|---|
| PRIMARY precision | ≥ 0.95 |
| PRIMARY wrong-direction rate | ≤ 0.02 |
| PRIMARY false-positive on **null events** | **= 0** (hard) |
| SECONDARY_RIPPLE recall | ≥ 0.70 |
| SECONDARY_RIPPLE precision | ≥ 0.80 |
| Fabricated-numeral rate | **= 0** (hard) |
| Firewall deletion rate on PRIMARY prose | = 0 |
| Internal contradiction rate | **= 0** (hard) |
| Calibration ECE | ≤ 0.05 |
| Section assignment accuracy | ≥ 0.98 |
| Reducer determinism (10k permutations) | 100% |
| Market/fundamental isolation test | pass |
| p95 publish latency (cached template) | ≤ 90s |

The three hard-zero gates are the definition of "defensible." Everything else is quality; those three are integrity.

### §17.3 Continuous monitoring (post-ship)

- Firewall deletion rate — spikes indicate model/prompt regression
- A/B divergence queue volume — spikes indicate either alpha or a broken channel
- Exposure staleness distribution — the ledger rots silently; alert at p90
- `policy_state` staleness — a stale windfall-levy rate is a correctness bug, not a data bug
- Calibration drift by month; refit quarterly
- Rejection-reason histogram — if `NO_MATERIAL_IMPACT` collapses toward zero, a threshold has been misconfigured

---

# §18. LLM USAGE POLICY

**LLMs are permitted for:** fact extraction from unstructured text; event normalization and classification under ambiguity; exposure extraction from filings *proposed for human review*; candidate mechanism hypothesis generation; the falsification checklist; prose fluency rewriting under §11.2 constraints; entailment judging.

**LLMs are forbidden from:** assigning materiality; assigning confidence; assigning publication tier; defining section identity; performing deduplication where structured identity exists; computing any arithmetic; resolving entities where an ISIN mapping exists; applying policy modifiers; writing to `company_impact`; producing any numeral that reaches the user.

**Cost architecture (cascade, evaluate in order):**

```
1. deterministic short-circuit   — index lookup, cached shock template, prior identical event  → 0 tokens
2. stage-result cache            — keyed (stage, input_hash, model_id, prompt_version)
3. small/fast model              — extraction, classification, entailment judging
4. frontier model                — only for candidates that are marginal at the gate boundary,
                                   MIXED resolution, and PRIMARY-eligible falsification
```

Prompt structure: cacheable static prefix (safety rules, taxonomy, schema, reasoning rules) + dynamic suffix (event, candidate, evidence, graph context). Never place dynamic content before static content — it destroys the prefix cache.

**Budget rule:** frontier-model calls per event must be bounded and monitored. A 250-candidate pool must not produce 250 frontier calls; the deterministic layers must eliminate ≥90% before any LLM sees a candidate.

---

# §19. ABSOLUTE PROHIBITIONS

Encode these as tests, not as documentation.

1. Never let market movement influence fundamental direction, materiality, tier, or evidence.
2. Never use ticker or name similarity as entity resolution.
3. Never use sector membership alone as company-level evidence.
4. Never let a `MODELLED` exposure self-certify without human review.
5. Never collapse MIXED into a direction to make the UI tidier.
6. Never let a failed PRIMARY auto-demote into SECONDARY.
7. Never attach a company list to `MACRO_CONTEXT`.
8. Never allow an LLM to emit a numeral that reaches the user.
9. Never publish a directional claim when `sign_consistency < 0.60`.
10. Never publish an upstream-realization call in India without evaluating the windfall-levy and administered-pricing modifiers.
11. Never allow any process other than the reducer to write `company_impact`.
12. Never display a confidence number without its band and dominant driver.
13. Never hide the rejected set from the review console.
14. Never merge directness, causal distance, discovery source, and publication tier into one field or one string.

---

# §20. WHAT THIS BUYS YOU

An expert reviewing V5 output sees, for every company on screen:

- a named mechanism and the exact P&L line it moves
- a magnitude with an uncertainty band, in EBITDA percentage terms
- the filing the exposure came from, with a date
- the pass-through assumption and its source, flagged as the dominant driver
- the regulatory modifiers that were applied
- direction at three horizons rather than one flattened guess
- what history did in 34 comparable shocks, including when the system disagrees with history
- the objections that were raised and why they were overruled
- a calibrated probability that has been measured against outcomes
- and, one click away, the fourteen candidates that were rejected and why

They will still disagree with some calls. That is the job. But they will not be able to say the system is naive, fabricating, or internally inconsistent — and that is the only version of "unfaultable" that a real system can honestly deliver.
