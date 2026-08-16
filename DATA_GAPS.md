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

Phase 1 created **no** financial data either. Migration 0012 writes zero
rows. `backend/config/freshness.yaml` contains policy numbers (how old a
disclosure may be before it is distrusted) and no company facts, and
`tests/phase1/test_ledger_schema.py` asserts it names no company and no
financial figure. Every numeral in `tests/fixtures/phase1/` is a
repeated-digit placeholder inside an object marked `"_fixture": true`, and
`tests/phase1/test_no_direct_write.py` asserts no production module can read
those fixtures.
