# DATA GAPS — Phase 4 — the policy registry

Part of [`DATA_GAPS.md`](../DATA_GAPS.md), which is now an index over this
directory. **Section numbers are repo-wide and unchanged** — prose, code
comments and tests that cite "§7" or "DATA_GAPS section 11" still mean the
section of that number, wherever it now lives.

---

## 8. Phase 4 — the policy registry has no parameter values — OPEN

Phase 4 built the registry, the six transfer functions, the state store, the
deterministic application order, the horizon vector and the inventory
revaluation channel. Every one of them works. **Not one modifier has a
number in it.**

`backend/config/policy_modifiers.yaml` scaffolds the minimum India set spec
§9 names, with structure only: `applies_to_tag`, `jurisdiction`, the transfer
function type, and a `parameters._required` list naming exactly what is
missing. Every parameter value is `null`, every `owner` is the placeholder
`OWNER-REQUIRED`, and `app/analysis/policy/registry.py` loads such an entry
with status `SCAFFOLD` — which `active_for` never returns and `materialise`
never writes. So `policy_modifier` and `policy_state` **ship empty**, and the
engine's modifier stage is an identity transform in production today.

**Why there is no shortcut here.** A levy threshold, an administered ceiling
or a duty rate produced from a model's memory would be *invisible*: it would
make the output look more sophisticated rather than less, and the error would
surface months later as a confidently wrong impact call on a real company.
This is the exact failure `docs/v5/00_MASTER_CONTEXT.md`'s fabrication guard
describes, and the phase file's own DO NOT repeats it. The refusal is
enforced by the loader, not by this paragraph.

### Every modifier awaiting real parameter values

`applies_to_tag` marked **pending** has no leaf in
`config/exposure_tags.yaml` yet; the tag the vocabulary needs is named in the
YAML entry's `pending_tag`.

| modifier_id | type | acts on | parameters required | owner |
|---|---|---|---|---|
| `IN_SAED_WINDFALL_LEVY_CRUDE` | THRESHOLD_CAPTURE | `revenue:crude_realization` | `threshold_level`, `capture_fraction_above` | **OWNER-REQUIRED** |
| `IN_SAED_WINDFALL_LEVY_PRODUCT_EXPORT` | THRESHOLD_CAPTURE | `revenue:refining_gross_margin` | `threshold_level`, `capture_fraction_above` | **OWNER-REQUIRED** |
| `IN_APM_GAS_CEILING` | HARD_CAP | `revenue:gas_realization_apm` | `cap_level` | **OWNER-REQUIRED** |
| `IN_RETAIL_FUEL_REVISION_STATE` | STATE_DEPENDENT | `revenue:marketing_margin_retail_fuel` | `state_key`, `when` | **OWNER-REQUIRED** |
| `IN_FUEL_EXCISE_AND_STATE_VAT` | SUBSIDY_SHARE | `revenue:marketing_margin_retail_fuel` | `retained_fraction` | **OWNER-REQUIRED** |
| `IN_ATF_STATE_VAT` | REGIONAL_MULTIPLIER | `input:atf` | `region_multipliers` | **OWNER-REQUIRED** |
| `IN_EXPORT_DUTY_STEEL` | SUBSIDY_SHARE | pending `revenue:steel_realization` | `retained_fraction` | **OWNER-REQUIRED** |
| `IN_EXPORT_DUTY_RICE` | SUBSIDY_SHARE | pending `revenue:rice_realization` | `retained_fraction` | **OWNER-REQUIRED** |
| `IN_EXPORT_DUTY_SUGAR` | SUBSIDY_SHARE | pending `revenue:sugar_realization` | `retained_fraction` | **OWNER-REQUIRED** |
| `IN_SUGAR_EXPORT_QUOTA` | HARD_CAP | pending `revenue:sugar_realization` | `cap_level` | **OWNER-REQUIRED** |
| `IN_IMPORT_DUTY_EDIBLE_OIL` | FORMULA_PRICING | `input:palm_oil` | `administered_delta_pct` | **OWNER-REQUIRED** |
| `IN_PLI_SCHEME` | SUBSIDY_SHARE | pending `revenue:pli_incentive` | `retained_fraction` | **OWNER-REQUIRED** |
| `IN_MSP_ANNOUNCEMENT` | FORMULA_PRICING | `input:wheat` | `administered_delta_pct` | **OWNER-REQUIRED** |
| `IN_TELECOM_AGR_SPECTRUM` | STATE_DEPENDENT | pending `regulatory:telecom_agr_dues` | `state_key`, `when` | **OWNER-REQUIRED** |
| `IN_BANKING_RISK_WEIGHTS` | FORMULA_PRICING | pending `regulatory:bank_risk_weight` | `administered_delta_pct` | **OWNER-REQUIRED** |

`python -c "from app.analysis.policy.registry import gap_report; print(gap_report())"`
regenerates this list from the YAML, so it cannot drift silently, and
`tests/phase4/test_no_fixture_data_reaches_production.py` asserts every id
the registry is waiting on appears in this file.

### The other Phase 4 gaps

| What exists | What is missing | Owner |
|---|---|---|
| `policy_state` schema, freshness rule, staleness→PRIMARY block | **every reading.** Whether retail fuel revisions are currently permitted, the current SAED rate. Each is an observation somebody takes on a cadence; the table is empty, so every STATE_DEPENDENT modifier resolves UNKNOWN and widens | repo owner |
| REGIONAL_MULTIPLIER transfer function | **the company geography mix.** Nothing in the schema records which states a company sells into, so the multiplier is unresolvable for every real company and the modifier widens rather than applies. `apply_modifiers(region_mix=…)` is the seam | repo owner |
| THRESHOLD_CAPTURE / HARD_CAP transfer functions | **shock LEVELS.** Both compare against a level (a price per barrel, per mmbtu), and nothing constructs a `Shock` with `level_before` / `level_after` from a real article yet — event→shock extraction is not this phase. Absent levels the modifier widens and caps at C | V5 serving phase |
| INVENTORY_REVALUATION channel + `inventory_realization_fraction` | **the inventory positions and the realisation curves.** `company_exposure` can hold an `INVENTORY` row and `company_modifier` can hold the curve; neither has one, so the channel that dominates the IMMEDIATE horizon computes for nobody | repo owner (ledger population, §5) |
| three-horizon engine + `config/horizons.yaml` | nothing; the windows are policy and are stated. But the horizons only differ where a **curve** exists, and the ledger has no curves, so on real data today all three horizons would resolve to the same scalar | repo owner (§5) |

### Sub-gaps recorded with it

* **The OMC three-horizon split and the Oil India regression are measured on
  FIXTURES** (`backend/tests/phase4/fixtures/*.json` — a company that does not
  exist, an EBITDA of a round billion, a levy threshold of 100 in no unit).
  They prove the arithmetic and the record shape. They prove nothing about any
  Indian company. **Owner: repo owner** (registry parameters, above).
* **`effective_from` is filled in for two entries only** (the two SAED
  entries, `2022-07-01`), and each carries a `date_basis` naming the public
  act it refers to. Every other date is null. A date is not a financial
  parameter — but a date I am not sure of is still a fabrication. **Owner:
  repo owner.**
* **A state reading is treated as UNKNOWN beyond its own freshness window.**
  A 120-day reading says nothing about day 270, so the STRUCTURAL horizon of
  a state-dependent channel widens and caps at C rather than extrapolating
  today's regime. This is a **controller ruling**, not a line in the phase
  file; it is what makes the OMC structural horizon UNCERTAIN by mechanism
  rather than by tuning. Recorded here so a reviewer can disagree with it.
* **`allow_stale_policy_state: false` on PRIMARY changes no verdict today**,
  because `policy_state` is empty and no company depends on a stale reading.
  It starts blocking the day a state is registered and goes stale — which is
  the §9.3 behaviour, and it is fail-CLOSED unlike the two A5.1 keys.
* **Modifier chips are serialiser-level only.** `policy_modifiers` reaches the
  `CompanyImpact` payload with id, type, status, source URL and the horizons
  each status held at. Nothing renders them, because V5 has no serving path
  (the established Phase 0 ruling). **Owner: V5 serving phase.**
* **FRBM / borrowing-calendar effects on rates are NOT scaffolded.** Spec §9's
  "maintain at minimum, for India" list names them and the registry has no
  entry. They act on a rate PATH rather than on a company exposure, so the
  transfer function is not obviously one of the six and the tag is not
  obviously one of the vocabulary's — modelling them as `FORMULA_PRICING` on
  `rate:floating_debt_share` would be a guess about the mechanism, not only
  about the parameters. Scaffolding an entry whose *shape* is wrong is worse
  than an honest omission, because a shape looks decided. **Owner: repo owner
  (domain judgement first, then parameters).**
* **`review_interval_days` measures maintenance cadence, not forecast reach**
  (design note, no schema change this round). A modifier's review interval
  says how often somebody re-reads the notification; `policy_state.
  freshness_days` currently does double duty as both "how stale is this
  reading" and "how far forward does it speak", which is what the
  beyond-horizon ruling above leans on. A separate
  `policy_state.predictive_horizon_days` column would separate the two
  honestly. Recommended, deliberately not built: it is a schema change on a
  table with no rows and no owner, and inventing a predictive reach per state
  would be the same fabrication as inventing the state. **Owner: repo owner.**
