# DATA GAPS — Phase 5 — empirical cross-check and calibration

Part of [`DATA_GAPS.md`](../DATA_GAPS.md), which is now an index over this
directory. **Section numbers are repo-wide and unchanged** — prose, code
comments and tests that cite "§7" or "DATA_GAPS section 11" still mean the
section of that number, wherever it now lives.

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

**§9.9 (PROPOSED SPEC AMENDMENTS) now lives in
[`proposed-spec-amendments.md`](proposed-spec-amendments.md).** It is still
§9.9 and still Phase 5's; it is a separate file because an amendment is
disposed of by the owner on its own cadence, not with the data gaps around
it.
