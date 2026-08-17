# DATA GAPS — The exposure ledger itself

Part of [`DATA_GAPS.md`](../DATA_GAPS.md), which is now an index over this
directory. **Section numbers are repo-wide and unchanged** — prose, code
comments and tests that cite "§7" or "DATA_GAPS section 11" still mean the
section of that number, wherever it now lives.

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
| **Rows today** | **`company_exposure`: 11** (imported 2026-08-17, see below). `company_segment`, `company_financials`, `pass_through_curve`, `company_modifier`: **0**. |
| **What is needed** | Spec §4.3 bootstrapping order. **Tier 1 first: Nifty 200 + all F&O names.** Per company: Ind AS 108 segment revenue/EBITDA, raw-material-consumed breakup, forex earnings & expenditure note, borrowings note (fixed vs floating), power & fuel line, employee cost. |
| **Where it comes from** | The companies' own filings — annual reports and quarterly results (PDF/XBRL) from BSE/NSE. Not derivable from anything already in this repo, and **not generatable by a model**: a `share_of_base` we produced from our own knowledge is precisely the fabrication the master context forbids. |
| **Who must supply it** | **The repo owner (user)**, as the acquirer of the documents and the reviewer of every proposal. The pipeline can propose; only a human can approve. Rough shape: Tier 1 is ~250 companies × ~6 disclosures. |
| **Tooling ready** | `app/ingest/filings/` (acquire → pypdf/XBRL → LLM propose → verbatim gate → `exposure_proposal`), `backend/tools/ledger_ui.py` (review console, port 8601 — APPROVE / EDIT+APPROVE / REJECT, bulk approve for deterministic extractors only), `backend/scripts/flag_stale_exposures.py` (nightly staleness), `/ledger/coverage` and `/ledger/metrics` for progress. |
| **Blocked until closed** | Phase 2 (sensitivity/materiality) and Phase 3 (tag index) are meaningless on an empty ledger. Today the system correctly abstains: with no exposure rows there are no channels, so every company reduces to `NO_MATERIAL_IMPACT` and the gate rejects (`test_staleness.py::test_the_pipeline_with_an_empty_ledger_abstains_and_publishes_nothing`). |

### The first eleven rows — imported 2026-08-17

The crude ripple bootstrap (§14) produced eleven rows and they are now IN
`company_exposure`, approved through `app.ledger.review.approve_proposal`
with `reviewed_by = 'ST269 (repo owner)'`. `test_every_ledger_table_ships_
empty` still holds where it is asserted — on a freshly migrated database —
because no migration writes these; they arrived through the review path.

| | |
|---|---|
| Rows | 11, across 9 companies, all `exposure_kind = INPUT_COST` |
| Tags | `input:base_oil` 1 · `input:bought_in_freight` 4 · `input:crude_derivative_petchem` 2 · `input:crude_derivative_rubber` 1 · `input:freight_diesel` 2 · `input:intermediated_air_capacity` 1 |
| `measurement` | **ESTIMATED on every row.** Not one share is stated in a filing; each is a ratio computed from two disclosed figures. |
| Evidence grade | capped at **D** via `materiality.yaml → exposure_measurement_grade_cap`. PRIMARY admits `[A, B, C]`, so **none of these rows can lead a publication**; SECONDARY_RIPPLE admits D. |
| Already STALE | **3 of 11** — Blue Dart, CONCOR and Delhivery cite FY2025 reports (504 days old against the 400-day INPUT_COST policy) because no FY2026 report was filed at acquisition time. Stale exposures are excluded from PRIMARY by the gate regardless. |

**What these rows do NOT yet do: anything.** Verified by running
`analyse_company` against CEAT with a crude shock on the live database — the
channel is `UNCOMPUTABLE / MISSING_ROW(pass_through)` and the engine abstains,
because `pass_through_curve` is still empty. An exposure without a
pass-through curve cannot be sized. **The binding constraint has moved from
"no exposure rows" to "no pass-through curves", and the curves are the harder
half**: a share is arithmetic over two printed figures, a pass-through is a
behavioural parameter that has to come from an earnings call, a regulator, or
a fitted estimate nobody has fitted.

**Markers are documentation, not enforcement.** Three rows carry a marker in
the proposal's `raw_payload` (`FLOOR` on both CEAT rows and on Blue Dart,
`UPPER_BOUND` on Mahindra Logistics), reachable from
`company_exposure.proposal_id`. **Nothing in Phase 2 reads them.**
`company_exposure` has no free-text column and none was added: a SQLite
`batch_alter_table` on a triggered table silently drops its triggers (0008's
warning). So the honest statement is that the enforced protection on these
rows is grade D and nothing else, and a reader who wants to know that CEAT's
0.2278 is a floor must join to the proposal.

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
