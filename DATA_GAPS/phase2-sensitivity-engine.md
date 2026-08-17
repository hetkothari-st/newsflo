# DATA GAPS — Phase 2 — the sensitivity engine

Part of [`DATA_GAPS.md`](../DATA_GAPS.md), which is now an index over this
directory. **Section numbers are repo-wide and unchanged** — prose, code
comments and tests that cite "§7" or "DATA_GAPS section 11" still mean the
section of that number, wherever it now lives.

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
