# DATA GAPS

Datasets this repo has the machinery to hold but does **not** have the data for.

Required by `docs/v5/00_MASTER_CONTEXT.md`'s fabrication guard: when a task
needs data we do not have, we build the schema, the loader and the tooling,
leave the table **empty**, and record the gap here with what is needed,
where it comes from, and who must supply it. Nothing in this repo may fill
one of these gaps with a plausible-looking value.

Status legend: **OPEN** = nothing loaded · **PARTIAL** = some rows, not
enough to rely on · **CLOSED** = complete and sourced.

---

## 1. Gate Zero labeled corpus — OPEN

The measurement that everything else in V5 waits on
(`docs/v5/EXECUTION_CONTRACT.md` §2: "no further architecture work, no
Phase 0, no refactoring, until Gate Zero passes"). Until these labels
exist, every claim about whether the system is good is an opinion.

| | |
|---|---|
| **Tables** | `eval_event`, `eval_label`, `eval_event_label`, `eval_adjudication` (migration 0010) |
| **Rows today** | 0 in all four. Shipped empty deliberately. |
| **What is needed** | **40 labeled events in total: 30 real crude-shock events + 10 null events** (financial news that should produce no company impact), exactly as `EXECUTION_CONTRACT.md` §2 states. Per event: expected PRIMARY companies, expected ripple families, expected ABSENT companies, expected direction per company, free-text rationale. |
| **How many labelers** | **Two independent labelers per event**, event-only, without seeing system output (`docs/v5/08_PHASE_7_eval_harness.md` labeling protocol — anchoring destroys the label's value). Disagreements resolved in `/eval/adjudicate`; anything unresolved stays `DISPUTED` and is excluded from precision denominators. |
| **Where it comes from** | Human judgment over already-ingested articles in the `articles` table. Not derivable from any external dataset and **not generatable by the system being measured** — a corpus we produced would measure our own imagination. |
| **Who must supply it** | **The repo owner (user).** Two people, roughly 5–8 person-days total. |
| **Tooling ready** | `backend/tools/eval_ui.py` (labeling + adjudication UI, port 8600), `backend/tools/eval_import.py` (CSV/JSON import for offline spreadsheet labeling), `backend/scripts/score_baseline.py` (scores and emits `BASELINE.md`). |
| **Blocked until closed** | `BASELINE.md` does not exist, so V5 Phase 0 cannot start. The scorer refuses to run on an empty corpus rather than reporting a meaningless 0% or 100%. |

**Null events are the important quarter.** Ten of the forty must be financial
news with no material listed-company impact. They are the only measurement
of whether the system can say nothing, and they are the slice most likely
to be quietly dropped because it is boring to build.

### Closing it

1. Pick the events (30 crude, 10 null) from the `articles` table and load
   them: `python backend/tools/eval_import.py --events events.csv`.
2. Two people label independently:
   `python backend/tools/eval_ui.py` → `http://127.0.0.1:8600/eval/label?labeler=NAME`.
3. Adjudicate the diffs at `/eval/adjudicate?event_id=…`.
4. Ensure each event's article has a stored analysis (the scorer reports
   any that do not as UNSCORED; it never triggers an analysis itself).
5. `python backend/scripts/score_baseline.py` → commit `BASELINE.md`.

---

## 2. Events whose article has no stored analysis — OPEN (dependent on §1)

The scorer measures the pipeline's **persisted** output. A labeled event
whose article was never analysed is reported as `UNSCORED` and appears in
no metric. Running the analysis pass for those articles is a deliberate,
human-initiated act (see the standing rule: no bulk auto-analysis), never
a side effect of measuring.

**Owner:** repo owner (user), during step 4 above.

---

## 3. Phase 0 gate inputs that do not exist yet — OPEN

Phase 0 built the publication gate's full §7.4 structure
(`backend/config/gates.yaml` + `backend/app/core/gates.py`), but four of its
inputs have no source in this repo. **None of them is defaulted to a
plausible value.** Each arrives at the gate as `None` ("not known"), and
`config/gates.yaml` states explicitly, per tier, what an unknown means —
fail-closed for `PRIMARY`, permissive for `SECONDARY_RIPPLE`.

| Input | Gate rule | Today | Supplied by |
|---|---|---|---|
| `empirical_status` | PRIMARY requires `AGREE` or `NO_DATA` | the V4 adapter emits the literal truth, `NO_DATA` — there is no empirical calibration table | Phase 5 |
| `adv_20d_inr` (liquidity) | `min_adv_inr` | `min_adv_inr: null`, so the rule is not evaluated at all | Phase 1/2 (liquidity feed) |
| `shock_magnitude_confidence` | `< 0.5` ⇒ macro-only ⇒ company REJECTED | never supplied; unknown does not block | Phase 2 (sensitivity engine) |
| `exposure_stale` | any STALE exposure ⇒ REJECTED | hard-coded `False` **because no exposure ledger exists** — nothing can be stale | Phase 1 |

**Owner:** the V5 phases themselves, not the repo owner. Listed here so the
gate is never read as "fully evaluated" today.

## 4. Historical `alert_companies` → `company_impact` backfill — OPEN

`backend/scripts/backfill_company_impact.py` is **committed and has not been
run** against any database. Two ambiguities are deliberately unresolved:

* legacy rows predate `alerts.content_key`, so they have **no
  `analysis_version`** — the script skips them rather than invent an
  identity;
* the V4 discovery vocabulary values `EXPOSURE_RULE`, `RIPPLE_DISCOVERY`,
  `ESCALATION`, `COMPLETENESS`, `CURATED` have **no V5 twin that is not a
  guess** — those rows get `discovery_source = NULL` and
  `needs_reanalysis = 1`.

**Owner:** repo owner, whenever the historical corpus is wanted in canonical
form. Running it is a deliberate act; nothing schedules it.

---

## 5. The exposure ledger itself — OPEN (this is the big one)

V5 Phase 1 built the schema, the extraction pipeline, the review console and
the instrumentation, and **produced no data**. Every ledger table ships with
zero rows and `tests/phase1/test_ledger_schema.py::
test_every_ledger_table_ships_empty` keeps it that way. Nothing downstream
(Phase 2's sensitivity engine, Phase 3's tag index) can be measured until
these tables have real rows — and per the phase file's DO NOT, **Phase 2 must
not start on an empty Tier 1 ledger.**

| | |
|---|---|
| **Tables** | `company_exposure`, `company_segment`, `company_financials`, `pass_through_curve`, `company_modifier` (migration 0012) |
| **Rows today** | 0 in all five. Shipped empty deliberately. |
| **What is needed** | Spec §4.3 bootstrapping order. **Tier 1 first: Nifty 200 + all F&O names.** Per company: Ind AS 108 segment revenue/EBITDA, raw-material-consumed breakup, forex earnings & expenditure note, borrowings note (fixed vs floating), power & fuel line, employee cost. |
| **Where it comes from** | The companies' own filings — annual reports and quarterly results (PDF/XBRL) from BSE/NSE. Not derivable from anything already in this repo, and **not generatable by a model**: a `share_of_base` we produced from our own knowledge is precisely the fabrication the master context forbids. |
| **Who must supply it** | **The repo owner (user)**, as the acquirer of the documents and the reviewer of every proposal. The pipeline can propose; only a human can approve. Rough shape: Tier 1 is ~250 companies × ~6 disclosures. |
| **Tooling ready** | `app/ingest/filings/` (acquire → pypdf/XBRL → LLM propose → verbatim gate → `exposure_proposal`), `backend/tools/ledger_ui.py` (review console, port 8601 — APPROVE / EDIT+APPROVE / REJECT, bulk approve for deterministic extractors only), `backend/scripts/flag_stale_exposures.py` (nightly staleness), `/ledger/coverage` and `/ledger/metrics` for progress. |
| **Blocked until closed** | Phase 2 (sensitivity/materiality) and Phase 3 (tag index) are meaningless on an empty ledger. Today the system correctly abstains: with no exposure rows there are no channels, so every company reduces to `NO_MATERIAL_IMPACT` and the gate rejects (`test_staleness.py::test_the_pipeline_with_an_empty_ledger_abstains_and_publishes_nothing`). |

### Sub-gaps recorded with it

* **The 5-real-annual-report end-to-end run — DEFERRED to the user.** The
  phase file's DoD asks the pipeline to run "end to end on 5 real annual
  reports". `data/samples/` contains none, and downloading five real annual
  reports was ruled a user action by the controller adaptation. The pipeline
  is exercised end to end against **fixture** documents instead
  (`tests/fixtures/phase1/testco_filing.json` plus a programmatically built
  PDF read through the real pypdf adapter). **Owner: repo owner.** Until it
  is done, the pypdf text-extraction quality on real Indian annual-report
  layouts is *unmeasured* — a known unknown, not a claim that it works.
* **`config/exposure_tags.yaml` (spec §6.1) does not exist.** Phase 1
  validates only the SHAPE of an `exposure_tag` (`family:leaf`); the closed
  vocabulary is Phase 3's. Until it lands, two reviewers could spell the same
  exposure differently. **Owner: Phase 3.**
* **Pass-through curves and company modifiers have no source yet.** The
  tables and their review constraints exist (`curve_needs_review` rejects an
  ESTIMATED curve without a reviewer); no curve is seeded, and the spec's
  "use the sector median curve" fallback is deliberately NOT implemented as a
  default — there is no sector median to compute from zero rows.
* **`HOLDCO_DISCOUNT` carries no coefficient.** `attach_exposure_to_listco`
  records that the modifier applies and caps the tier at `SECONDARY_RIPPLE`;
  the size of the discount is Phase 4 policy data that does not exist.
* **`company_entity_meta` / `entity_corporate_action` / `company_alias_window`
  are empty.** So parent/subsidiary chains, ownership fractions, corporate
  actions and former-name windows are unknown for every company. The resolver
  fails closed on all of them (an unlisted subsidiary with no consolidated
  segment evidence does not attach; a missing `ownership_fraction` blocks
  attachment rather than defaulting to 1.0). **Owner: repo owner**, sourced
  from exchange filings and annual-report shareholding notes.

**Gap §3's `exposure_stale` row is now half-closed:**
`app.ledger.staleness.company_exposure_is_stale` supplies a real answer where
the ledger has rows. With the ledger empty it returns `False` — the honest
answer, since nothing exists that could be stale. **Phase 2 wires it on the
V5 path**: `app.analysis.sensitivity.engine.analyse_company` asks it for the
shock's exposure tags and reports the answer twice — on
`SensitivityRun.exposure_stale` (which the caller threads into
`EventContext`) and on every CHANNEL payload it emits, which the reducer
hard-blocks on. The V4-only pipeline hook in `app/core/impact_writer.py`
still passes `False`, because that path has no exposure *tags* to ask about;
it will carry a real flag when the canonical path runs the engine.

---

## 6. Phase 2 — the sensitivity engine has never seen a real filing — OPEN

Phase 2 computes materiality from ledger rows. **The ledger is empty (§5), so
every number the engine has ever produced came from `_fixture`-marked test
data.** The code is exercised; the *system* is not measured.

| | |
|---|---|
| **What exists** | `app/analysis/sensitivity/` (channels, params, Monte Carlo, engine, presentation) + `config/materiality.yaml`. 132 tests in `backend/tests/phase2`. |
| **What is missing** | Real `company_exposure`, `pass_through_curve`, `company_modifier` and `company_financials` rows — i.e. gap §5. Until they exist, `analyse_company` returns no channels and no signals for every company in the universe, and the reducer abstains. |
| **Owner** | Repo owner (same work as §5). |

### Sub-gaps recorded with it

* **The 20 worked examples are PENDING OWNER VERIFICATION.** Every case in
  `.superpowers/sdd/2026-08-17-v5-session0/phase2-worked-examples.md` and
  `backend/tests/phase2/fixtures/worked_examples.json` was derived by the
  implementing session, not checked by a human. The tests prove the code
  agrees with that arithmetic; they do not prove the arithmetic is right.
  **Owner: repo owner**, one read-through.
* **`company_modifier` has no `measurement` column.** FILED and
  DISCLOSED_CALL band differently (±10% vs ±20%), so a modifier row must say
  how it was measured. Phase 2 reads it from the `parameters` JSON
  (`{"hedge_ratio": …, "measurement": "FILED"}`) and **refuses to use a row
  that does not carry it** rather than assuming the narrower band. Either the
  extractor must always write that key, or a later migration should promote
  it to a column. **Owner: Phase 3 or a schema review.**
* **Three ledger exposure kinds have no §5.1 formula**: `REGULATORY`,
  `LOGISTICS_ENERGY`, `CUSTOMER_CONCENTRATION`. They are real exposures and
  they are recorded, but they cannot be sized, so they are reported as
  `uncomputable_channels` and publish nothing. **Owner: spec — §5.1 does not
  define them.**
* **The interest-rate channel is not really an EBITDA effect.** Interest sits
  below EBITDA. The channel keeps the spec's field name and is divided by
  EBITDA_ttm as §5.1 defines `materiality_pct`, but the number is a change in
  the interest line. A P&L-line-aware materiality base would be more honest.
  **Owner: spec.**
* **Monte Carlo assumes parameters are independent.** Identical parameters
  share a draw; *different* parameters are drawn independently, because no
  correlation structure exists in the ledger and inventing a correlation
  matrix would be inventing data. Where two parameters genuinely co-move
  (pass-through and hedge cover, for instance) the band is therefore probably
  too wide, in the safe direction. **Owner: Phase 5 (empirical calibration).**
* **A channel whose point estimate is exactly zero emits no signal.** It is
  not a directional claim, so it is recorded (`zero_delta_channels`) and not
  published — even though its band may be non-zero. Fail-closed, and worth
  revisiting when horizon vectors land in Phase 4.
* **`driver_ranking` is a first-order estimator.** `correlation_ratio_binned_v1`
  attributes no interaction variance, so the raw indices are normalised to
  sum to 1. Changing the estimator changes a number the user sees, which is
  why it is versioned.
* **The band is not persisted in a column.** `company_impact` gains no column
  this phase (a SQLite `batch_alter_table` would drop the Phase 0 single-writer
  triggers). The block reaches the API through the serializer and is retained
  in full on the append-only `signal` rows. **Owner: whoever ports to
  Postgres, where the ALTER is safe.**

---

## 7. Phase 3 — the ripple machinery has no economy to run on — OPEN

Phase 3 built discovery, the causal graph, the input-output bootstrap, the
reverse event study and the coverage audit harness. Every one of them works.
Not one of them has any data.

The addendum's own model of the problem is
`ripple_recall ≈ V × M × C × G`, and the coverage harness now MEASURES each
axis separately. Run against this repo today it reports, for every shock
class in the map, the same answer: **V passes, M passes on the fixture graph
and is empty in production, C is zero, G is never reached.** That is the
honest state, and it is now a number rather than a feeling.

| What exists | What is missing | Owner |
|---|---|---|
| `config/exposure_tags.yaml` — 25 tags, closed, DB-enforced | nothing; this is the one Phase 3 artefact that is complete | — |
| `mechanism_edge` schema + BFS walk + review queue | **every edge.** The table is empty in production. The ~60–100 hand-authored FX / rate / realization / regulatory edges have no substitute and never will | repo owner |
| IO parser + Leontief inverse + prune + candidate-edge emitter | **the published tables.** MOSPI Supply-Use / Input-Output Transaction Tables and RBI KLEMS are not in this repo. `io_coefficient` is empty and stays empty | repo owner |
| `config/industry_mapping.yaml` shape | **the mapping itself.** Ships with `_example: true` rows the loader REFUSES. Deciding which listed industry an IOTT code refers to is domain judgement | repo owner |
| `gap_finder.py` — CAR, aggregation, sign test, ranking, persistence | **8+ years of daily returns for the listed universe**, and a dated list of historical instances per shock variable. The module never fetches (an ast scan enforces it), so both are acquisition work | repo owner |
| coverage harness + per-axis diagnostic | **the expected-ripple map.** `tests/coverage/fixtures/expected_ripple_map.yaml` is headed `PROPOSED-PENDING-OWNER-SIGN-OFF`, has four shock classes rather than the twelve to fifteen A6.1 asks for, and `signed_off_by` is `null` | repo owner (domain expert) |
| `exposure_index` view + threshold walk | **the ledger rows underneath it** (§5). The index over an empty ledger returns nothing, so MECHANISM discovery finds nothing, so every ripple family is a C-axis gap | repo owner |

### Sub-gaps recorded with it

* **The recall and precision numbers in the Phase 3 report are measured on a
  SYNTHETIC universe** (`tests/coverage/fixtures/synthetic_universe.json` —
  fake companies, round-number exposures). They prove the harness's
  arithmetic. Real ripple recall today is **0**, for every family, because C
  is zero. **Owner: repo owner** (ledger population, §5).
* **The Leontief toy verification is PENDING OWNER VERIFICATION.** The
  hand-computed inverse is written out in full at
  `.superpowers/sdd/2026-08-17-v5-session0/phase3-leontief-toy.md`; the code
  agrees with it and an independent `(I−A)·(I−A)⁻¹ = I` check runs in CI, but
  no human has checked the cofactor arithmetic. **Owner: repo owner.**
* **IO tables generate INPUT_COST and DEMAND edges only** (A2.4). They
  produce no REVENUE_REALIZATION, FX, rate or regulatory edge, and the
  module refuses to claim otherwise. The hand-authored set is the only route
  to those channels. **Owner: repo owner.**
* **Family membership is `companies.sub_sector`.** The harness decides which
  family a company belongs to by its sub-sector slug. That column is written
  by two different jobs and manual repairs revert (see the repo's own notes),
  so the mapping from ripple family to listed universe is not yet a stable
  artefact. **Owner: repo owner.**
* **Discovery is not wired to the live pipeline.** `discover()` is invoked
  with explicit shocks in tests; nothing constructs a `DiscoveryShock` from a
  real article yet, because event → shock extraction is not this phase. The
  V4 discovery path is untouched and is still what serves. **Owner: V5
  serving phase.**
* **The two A5.1 gate rules are deployed FAIL-OPEN today** —
  `unknown_materiality_delta_passes` and `unknown_sector_proxy_passes` are
  both `true` in `config/gates.yaml`. See the **V5 SERVING CUTOVER CHECKLIST**
  below; this is item 1 there, not a note here. **Owner: V5 serving phase.**
* **`coverage_gap` is empty and its UI page says so.** `/graph/gaps` renders
  "the reverse event study needs price history the repo does not have"
  instead of an empty table pretending to be a clean bill of health.

### The one table Phase 3 populates, and why it is not a breach

`valid_exposure_tag` is written by migration 0013 from
`config/exposure_tags.yaml`. It is **controlled vocabulary, not data**: a tag
name asserts that "tyres buy synthetic rubber" is a concept the schema can
express, and asserts nothing about any tyre maker, any coefficient or any
filing. The claim that a specific company carries an exposure still lives in
`company_exposure`, which still ships empty and is still filled only by a
human approving a verbatim excerpt.
`tests/phase3/test_no_fixture_data_reaches_production.py` asserts that a
migrated database's `valid_exposure_tag` contains exactly the YAML rows and
nothing else, and that `mechanism_edge`, `io_coefficient` and `coverage_gap`
are empty.

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

---

## 9. Phase 5 — the empirical cross-check has no market history, and calibration has no corpus — OPEN

Phase 5 built the event study, the transmission matrix schema, the
four-outcome cross-check with its conflict handling and review queue, the
REGIME_CHANGED annotation, the whole calibration harness (features, isotonic
fit, ECE/Brier/reliability, Mahalanobis OOD), the surprise engine and the
market-isolation boundary. Every one of them works. **Not one of them has
seen a real number.** `transmission_empirical`, `divergence_review`,
`regime_change` and `calibration_model` all ship EMPTY, and every company's
`empirical_status` in production is the literal truth: `NO_DATA`.

### 9.1 Daily price history for the listed universe, ≥ 8 years — OPEN

| what | detail |
|---|---|
| table / interface | `app.analysis.empirical.event_study.ReturnHistory` |
| what is needed | adjusted daily returns per listed company, ≥ 8 years, with a `traded` flag, a circuit flag (`UPPER`/`LOWER`) and corporate-action markers. Returns must already be adjusted for splits/bonuses/demergers, or the day must be `None` |
| where it comes from | a licensed EOD feed, or an exchange bhavcopy archive processed into adjusted returns. The repo's existing price access is yfinance, which is a live socket and is BANNED from this path by an ast test |
| who must supply it | **repo owner** (acquisition + a `ReturnHistory` adapter) |

### 9.2 Sector benchmark series and the company → benchmark map — OPEN

`sector_beta_v1` regresses a company on the benchmark `benchmark_for()`
names. Without a sector index series there is no abnormal return, only a raw
one. **Owner: repo owner.**

### 9.3 Dated shock instances per economic variable — OPEN

The level series for the top 10 shock variables (crude, INR, repo, steel,
palm oil, …) over ≥ 8 years, from which `detect_shocks` derives instances.
`config/empirical.yaml` refuses a series shorter than 2,000 observations
rather than computing a σ over two years and calling it the same threshold.
**Owner: repo owner.**

**Consequence, stated plainly: "transmission matrix built over ≥ 8 years for
the top 10 shock variables" is DEFERRED, not done.** The machinery is
complete and tested on a hand-computed fixture; the matrix is empty.

### 9.4 The labeled corpus for calibration — OPEN (same corpus as §1)

`calibrated_p` is defined as P(the published directional call is judged
CORRECT by expert review). That needs expert judgements, of which this repo
has none. Until then:

* `config/calibration.yaml` ships `enabled: false` and `calibrated_p` is
  `null` everywhere;
* `calibration_model.is_active` carries a CHECK constraint pinning it to 0,
  so an ACTIVE row cannot exist without a **migration**;
* `registry.record_model` refuses a model fitted on `_fixture` labels and
  refuses a corpus below `activation.min_corpus_size` (500);
* the ECE ≤ 0.05 ship-gate test is **skipped with its reason recorded**, not
  quietly absent.

**Owner: repo owner + a domain reviewer (Phase 7).** The ECE, Brier and
reliability numbers §13.2 asks to be reported do not exist and must not be
invented — a plausible calibration curve would make every number in the
product look validated.

### 9.5 Consensus and forward-curve feeds — OPEN

`Surprise.consensus_gap_sigma` and `Surprise.forward_curve_implied` are
`None` for every event unless a caller supplies the inputs, because there is
no consensus-estimate feed and no futures/forwards feed wired in. The
composite renormalises over the components it actually has rather than
scoring a missing consensus as zero surprise. `ALREADY_PRICED` therefore
never fires in production today. **Owner: repo owner** (a broker-estimate
feed and a futures curve source).

### 9.6 The p95 latency dashboard — DEFERRED

`latency_ms_from_first_seen` is computed from timestamps the caller supplies
and travels on the surprise payload; `config/surprise.yaml` records the §14
target (90,000 ms). **There is no metrics stack in this repo**, so nothing
aggregates a p95 and nothing dashboards it — consistent with the Phase 0/4
rulings on monitoring. "p95 publish latency instrumented and dashboarded" is
**half done**: instrumented, not dashboarded. **Owner: V5 serving phase.**

### 9.7 Estimator questions the owner must answer

`.superpowers/sdd/2026-08-17-v5-session0/phase5-estimator-design.md` carries
a **PENDING-OWNER-VERIFICATION** header. Five choices in it are defensible
and unvalidated, and each is a one-constant change:

1. **full-sample σ** for shock detection rather than rolling/EWMA (chosen for
   reproducibility; known to be inflated by crisis periods);
2. **day 0 included** in every CAR window (the shock is measured on day 0);
3. **largest-move-wins** dedupe inside a 5-day window rather than first-wins;
4. **no multiple-testing correction** — ~120,000 tests at p < 0.10 would
   yield thousands of false positives, which is why an empirical row may only
   cap a tier and queue a human, never publish anything on its own;
5. **sector-beta residual** rather than Fama-French (Indian factor series are
   themselves a dataset nobody has supplied; US factors would be fabrication).

### 9.8 Phase 5 policy changes a reviewer should know about

* **`objection_types_exempt_from_severity_cap: [EMPIRICAL_CONFLICT]` on the
  ripple tier.** Without it, the sustained MAJOR objection §10.3 requires
  would have failed the SECONDARY walk too and produced `REJECTED` — the
  auto-reject the phase file forbids. One objection type, one tier; PRIMARY
  does not exempt it.
* **`allow_out_of_distribution: false` on PRIMARY changes no verdict today**,
  because no manifold is fitted and `in_distribution` is therefore `None`
  (unknown), which passes. Absence of a model is not evidence of novelty.
  The rule is NOT marked as an `unknown_escape`, deliberately: flagging it
  would fire a warning on every primary publication forever and drown the
  cutover signal that channel exists to carry.
* **The weekly rebuild is a runnable script, not a scheduled job.**
  `backend/scripts/rebuild_transmission_matrix.py` requires a
  `ReturnHistory` and a shock series as `module:factory` arguments and exits
  non-zero without them. Registering it with the scheduler is a one-line
  change the day §9.1–9.3 land.
* **No PRODUCT UI renders any of this.** The empirical sentence
  (`empirical_line`), the confidence line (`confidence_line`) and the
  surprise badge are formatting helpers with tests; V5 still has no serving
  path (the standing Phase 0 ruling). **Owner: V5 serving phase.** The
  INTERNAL review console is a different thing and it exists:
  `/divergence/queue`, `/divergence/review` and `/divergence/resolve` on
  `tools/ledger_ui.py`, added the same additive way Phase 3 added the
  mechanism-edge pages.

### 9.9 PROPOSED SPEC AMENDMENTS (§7.2 form required) — OPEN

Changes Phase 5 believes the spec should make, recorded rather than
implemented. **None of these is in the code.** EXECUTION_CONTRACT §7.2
requires a *failing measurement* to amend a frozen value, and each entry below
names the measurement that does not yet exist.

**PROPOSED SPEC AMENDMENT 1 — admit `WEAK` to
`primary.allowed_empirical_status`.**

* *Current normative value:* BUILD_SPEC §7.4 — `{AGREE, NO_DATA}`, frozen by
  EXECUTION_CONTRACT §7.1. Deployed unchanged in `config/gates.yaml`.
* *Proposed value:* `{AGREE, NO_DATA, WEAK}`.
* *Argument:* §10.2 defines `WEAK` as "the sample exists but is not
  significant either way" — the same information content as `NO_DATA`, which
  §7.4 already admits at PRIMARY. As frozen, a company we HAVE measured and
  found inconclusive publishes strictly worse than a company we have never
  measured: running the event study can only ever demote a candidate, never
  confirm one. That is a perverse incentive against building the very matrix
  §10.1 asks for, and it lets an insignificant historical sample veto a
  fundamental read.
* *Counter-argument (why the freeze may be right):* precision-first. Until
  the matrix exists nobody knows how many PRIMARY candidates would carry
  `WEAK`, and if the answer is "most of them" the amendment is a large,
  unmeasured loosening of the strongest tier.
* **Missing prerequisite:** a failing measurement. `transmission_empirical`
  is EMPTY (§9.1–9.3), so no candidate has ever carried `WEAK` in anger and
  the precision/recall cost of either choice is unmeasured. The measurement
  becomes possible the day the matrix is populated: count PRIMARY-eligible
  candidates by empirical status, and compare expert-judged precision of the
  `WEAK` group against the `NO_DATA` group.
* *Blast radius if adopted:* one line in `config/gates.yaml`, one assertion
  in `tests/phase3/test_ripple_gates.py`, one in
  `tests/phase5/test_empirical_check.py`. Nothing structural.
* **Owner: repo owner** (spec amendment), after Phase 7's corpus.

---

## 10. Phase 6 — the adversary has never argued with a real record, and nobody has ever labelled one — OPEN

Phase 6 built the falsification stage, the deterministic section engine and
the review console. **It created no table and wrote no row.** The falsifier
has made zero LLM calls, the section engine has sectioned only fixture
records, and the eval corpus the console writes into is still empty (§1).

### 10.1 No labeled corpus, so PRIMARY precision is unmeasured — OPEN

The phase file's last DoD item is *"PRIMARY precision holds or improves while
false-positive rate drops on holdout."* **There is no holdout.** The Gate Zero
corpus (§1) has no rows, so:

* nobody knows Phase 6's PRIMARY precision before the falsifier, and
  therefore nobody can know whether it held;
* nobody knows the false-positive rate, and therefore nobody can know whether
  it dropped.

What exists instead is the **machinery** and a **fixture proof**: a BLOCKING
objection rejects, a cited rebuttal releases, a free-text one does not. That
is a proof about the mechanism, not a measurement of the product.

*What is needed:* the §1 corpus, then Phase 7's harness run twice — falsifier
off and on — reporting precision and false-positive rate per stratum.
**Owner: repo owner** (the corpus is human work).

### 10.2 No cross-model provider for the falsifier — OPEN

`config/falsifier.yaml`'s `model_discipline.provider` and `model_id` are
**null**. Spec §12.4 asks for a different model or provider than the
candidate generator *"where cost permits"*, and nobody has decided what it
costs or who pays.

While they are null the falsifier runs on the **generator's own model** and
records `SAME_MODEL_AS_GENERATOR` as a limitation on every run. That is the
honest degradation, not a silent fallback — but it means the standard failure
mode §12.4 names (correlated generator/checker error) is **present and
undiluted**, and the eval harness will have only same-model rows to report.

*What is needed:* a second provider, a budget, and the two config values.
**Owner: repo owner.**

### 10.3 The falsifier is not wired into any pipeline — DEFERRED, by design

`app/analysis/falsifier/` is not called from `app/pipeline.py`. Two reasons,
both structural rather than a matter of effort:

1. V5 has no serving path (the standing Phase 0 ruling), so there is no live
   consumer of a canonical record to protect;
2. the live V4 path carries no record set of the shape §12.2 needs. Run
   against a V4 entry, the checklist would find nine of its ten questions
   unanswerable and the adversary would object to essentially every company —
   correctly, and uselessly.

It runs when the canonical path runs. Recorded here rather than in the code
so that "the falsifier exists" is never read as "the falsifier is protecting
anything today".

### 10.4 No event record and no shock record — OPEN

Spec §3.2 describes an `event` record with a shock vector; this repo has no
`event` table. A V5 "event" is one analysis run of one article
(`app.core.impact_writer.event_id_for_article`), and the **only** place a
shock variable is written down is the empirical cross-check's signal payload
— which is empty everywhere, because the transmission matrix is empty (§9).

So the console's "the event and its shocks" panel shows the article and an
explicit *no shock variable is recorded* line. It does not infer a shock from
the headline, which is what a plausible-looking version of this panel would
do.

*What is needed:* the §3.2 event record and a shock-detection stage that
writes it. **Owner: repo owner** (scope decision — it is a phase of its own).

### 10.5 `macro_channel_count` is supplied, not computed — OPEN

§15's zero-PRIMARY block counts macro channels. A macro channel is a
**mechanism-level** statement and may never carry a company list (invariant
6), so it cannot be counted off a set of company records.
`zero_primary_state(..., macro_channel_count=N)` therefore takes it from the
caller and **defaults to 0**, which is the truthful count while nothing
produces macro-context records.

*What is needed:* a macro-context producer. Until then, the console renders
`0 macro channels`, which is a fact about this system rather than about the
event.

### 10.6 Rebuttal coverage is four objection types out of eleven — OPEN, and deliberately

`app/analysis/rebuttal.py` can answer `OFFSET_IGNORED`,
`REGIME_MODIFIER_MISSING`, `EXPOSURE_NOT_IN_LISTCO` and `EVIDENCE_STALE` —
the four whose answer is a datum a stage already holds. The other seven
(`ENTITY_WRONG`, `MECHANISM_INVALID`, `MAGNITUDE_IMMATERIAL`,
`HORIZON_MISMATCH`, `ALREADY_PRICED`, `BASE_RATE_VIOLATION`,
`SECOND_ORDER_OVERREACH`) have **no automatic rebuttal and stand by default**.

This is the §12.3 asymmetry working, not a gap in the usual sense — but it is
recorded because it has a consequence: a BLOCKING `MECHANISM_INVALID` cannot
currently be cleared by any code path, so wiring the falsifier live without
either a human rebuttal route or more rebuttal rules would reject everything
it objects to. **Owner: whoever wires the falsifier** (see 10.3).

### 10.7 The checklist-question → objection-type mapping is a judgement — OPEN

`config/falsifier.yaml`'s `checklist[].objection_type` says which objection
stands when a question cannot be answered. The taxonomy is closed (§12.1), so
there is no "we do not know" objection to map an unanswered question onto;
each of the ten is mapped to the objection whose **burden** that question
governs, with the reasoning written above each entry in the file.

Two are worth a reviewer's eye: Q1 (unsized exposure → `MAGNITUDE_IMMATERIAL`,
which asserts smallness where the honest statement is "unsized") and Q9
(unknown parameter provenance → `BASE_RATE_VIOLATION`). Both are the closest
members of a closed vocabulary rather than exact fits.

*What is needed:* an owner's ruling, or a §7.2 amendment adding an
`UNSIZED` / `PROVENANCE_UNKNOWN` type to §12.1. **Owner: repo owner.**

---

## V5 SERVING CUTOVER CHECKLIST

**Do not serve the V5 canonical path until every item here is done.** These
are not gaps in the data — they are settings that are *correct while V5 is
parallel and unserved* and *wrong the moment it is not*. They are listed
separately from the gap sections precisely so that "the ledger is still
empty" cannot be used to postpone reading them.

The dangerous state is not "V5 off" or "V5 on". It is the **partial
rollout**: some drafts carrying a computed band and some not, in the same
feed, indistinguishable to the reader.

### 1. Flip the two fail-OPEN gate keys — `config/gates.yaml`

| Key | Deployed | Must become | Blocks |
|---|---|---|---|
| `primary.unknown_materiality_delta_passes` | `true` | `false` | a band-less draft clearing the 2.0% PRIMARY materiality floor |
| `primary.unknown_sector_proxy_passes` | `true` | `false` | a draft of unknown parameter provenance clearing the PRIMARY sector-proxy ban |

Both are `true` because nothing computes a band or a parameter provenance on
the V4-fed canonical path today. **Flipping them is not a one-line change.**
Measured on 2026-08-17 by flipping both and running
`tests/phase0 tests/phase1 tests/phase2`: **5 failures**, every one of them a
fixture that reaches PRIMARY without a sensitivity block.

```
tests/phase0/test_firewall.py::test_primary_prose_has_deletion_rate_zero_on_the_fixture_corpus
tests/phase0/test_single_truth.py::test_the_fixture_primary_company_reaches_primary
tests/phase1/test_staleness.py::test_a_stale_exposure_blocks_primary_in_the_gate
tests/phase2/test_evidence_grade_cap.py::test_a_signal_set_with_no_sensitivity_block_is_unaffected
tests/phase2/test_sign_consistency_gate.py::test_the_phase0_fixture_company_is_reduced_exactly_as_before
```

The fixture work — giving those fixtures a computed band, or accepting that
they now reach SECONDARY — must be done in the **same change**. Do not flip
the keys and delete the failing assertions: three of those five exist
precisely to prove a company reaches PRIMARY, and deleting them removes the
only evidence that the flip did not simply switch PRIMARY off.

*(The Phase 3 review recorded 7 failures for the same experiment. The number
above is what this session measured on the current tip; the branch gained
`tests/phase2/test_evidence_grade_cap.py` and other fixtures in between.
Re-measure before acting rather than trusting either figure.)*

The `secondary_ripple` twins of both keys may stay `true`: a ripple already
admits weaker evidence by design.

**Owner: V5 serving phase.**

### 2. Confirm the escape warning is silent

`app/core/gate_warnings.py` emits a structured `WARNING` on the
`newsflo.gate` logger for every PRIMARY publication that passed a rule only
because one of those escapes fired, carrying
`gate_unknown_escape_rules`, `gate_tier`, `event_id` and `company_id`. It is
the audible version of the hole in item 1.

**After item 1, this warning must never fire.** If it still does, a code path
is constructing an `ImpactDraft` without a band and something is publishing
it as PRIMARY. Wire the logger into whatever alerting exists before cutover,
not after.

### 3. Re-run the coverage harness against the REAL universe

Every recall and precision number recorded anywhere in this repo was measured
on `backend/tests/coverage/fixtures/synthetic_universe.json`. Before serving,
run `audit_shock` against the production database and record the real
numbers. Expect them to be bad; the point is that they will be *specific*.

### 4. Get the expected-ripple map signed off

`backend/tests/coverage/fixtures/expected_ripple_map.yaml` is headed
`PROPOSED-PENDING-OWNER-SIGN-OFF` with `signed_off_by: null`. Until a domain
expert signs it, every recall figure is relative to the implementer's guess
at what should have surfaced.

---

## Not gaps

Transmission coefficients and empirical calibration tables (`docs/v5` Phases
4–5) are **not listed here yet** — those phases have not started and their
tables do not exist. They join this file when their schemas land, per the
fabrication guard.

Phase 0 created **no** financial data: it touched no exposure, coefficient or
empirical table, and the only row any Phase 0 migration writes is the
reducer-version fence (`supported_version('r5.0.0')`), which is policy, not
data about the world.

Phase 2 created **no** financial data either. It adds no table and no
migration; `backend/config/materiality.yaml` contains thresholds, band widths
and draw counts and **no parameter value** (a test asserts the only section
naming parameters is `param_bounds`, whose every entry is a `[0, 1]` domain
bound). Every numeral in `backend/tests/phase2/fixtures/` sits inside an
object marked `"_fixture": true`, and
`tests/phase2/test_no_fixture_data_reaches_production.py` asserts no module
under `app/`, `tools/` or `scripts/` can reach it and that the ledger tables
are empty in a freshly built database.

Phase 3 created **no** financial data either. Migration 0013 writes exactly
one kind of row — the controlled vocabulary, explained in §7 — and nothing
else; `mechanism_edge`, `io_coefficient` and `coverage_gap` are empty in a
freshly migrated database and a test asserts it. `config/discovery.yaml`
contains thresholds and a list of economic variable NAMES;
`config/industry_mapping.yaml` contains examples the loader refuses to load.
No input-output coefficient, elasticity, or industry mapping was written from
anybody's knowledge, and a test scans `app/graph/io_bootstrap/` for
coefficient literals.

Phase 1 created **no** financial data either. Migration 0012 writes zero
rows. `backend/config/freshness.yaml` contains policy numbers (how old a
disclosure may be before it is distrusted) and no company facts, and
`tests/phase1/test_ledger_schema.py` asserts it names no company and no
financial figure. Every numeral in `tests/fixtures/phase1/` is a
repeated-digit placeholder inside an object marked `"_fixture": true`, and
`tests/phase1/test_no_direct_write.py` asserts no production module can read
those fixtures.
