# DATA GAPS — Phase 7 — harness and monitoring

Part of [`DATA_GAPS.md`](../DATA_GAPS.md), which is now an index over this
directory. **Section numbers are repo-wide and unchanged** — prose, code
comments and tests that cite "§7" or "DATA_GAPS section 11" still mean the
section of that number, wherever it now lives.

---

## 11. Phase 7 — the harness has never scored anything, and nothing watches production — OPEN

Phase 7 built the evaluation harness, the metric suite, a runnable
shipping-gate evaluator and the nine Task 7.4 monitoring signals. **It
measured nothing.** Every number the harness can produce needs the corpus in
§1, which is empty; every signal monitoring can produce needs a running V5
path, which does not exist. What ships is machinery plus a fixture proof of
each mechanism, and each unmeasurable thing refuses loudly instead of
returning 0.0 or 1.0.

### 11.1 No corpus, so twelve of the fourteen gates have never been evaluated — OPEN

Same corpus as §1, and it is the blocker for the whole phase — **but not for
all of it**, and the distinction matters. Two gates are answered by RUNNING a
Phase 0 suite rather than by a corpus metric, and both pass today:

| gate | answered by | today |
|---|---|---|
| `reducer_determinism` | `tests/phase0/test_reducer_purity.py::test_reducer_output_is_byte_identical_across_10k_permutations` | **PASS** |
| `market_fundamental_isolation` | `tests/phase0/test_market_isolation.py::test_mutating_market_data_leaves_company_impact_byte_identical` | **PASS** |

They are not gaps and must not be counted as ones. Everything below is about
the other twelve.

| | |
|---|---|
| **What is needed** | The §1 corpus (Task 7.1 asks for 300 events, ≥ 50 of them null, every stratum represented, two independent labelers each, κ reported). `EXECUTION_CONTRACT.md` §2 scopes the first pass to 40 (30 crude + 10 null) — that is Gate Zero, not Task 7.1's full corpus, and Phase 7's `corpus_integrity()` reports both bars. |
| **Rows today** | 0 in `eval_event`, `eval_label`, `eval_event_label`, `eval_adjudication`. |
| **Consequence** | `eval.harness.corpus_integrity()` and `load_expectations()` raise `HarnessRefusal`. `tests/phase7/test_corpus_integrity.py` and `test_null_events.py` SKIP their corpus assertions with that reason in the skip message. **Twelve of the fourteen shipping gates are REFUSED** — eleven for want of this corpus, and `p95_publish_latency_seconds` because nothing times the V5 path (§11.5) — so the evaluator exits 1. The two delegated gates PASS. |
| **How to run it once the corpus exists** | Point `NEWSFLO_EVAL_CORPUS_DB` at the labeled database and the skipped tests run for real. |
| **Owner** | **repo owner** (labeling is human work). |

### 11.2 The no-regression baseline ships absent — OPEN

`backend/eval/baselines/main.json` does not exist, deliberately.
`backend/eval/baselines/README.md` says why and how to write the first one.
A placeholder baseline would exit zero and make every future merge look
non-regressive against a measurement nobody made.
**Owner: repo owner**, after §11.1.

### 11.3 There is no CI, so no gate is enforced on anything — DEFERRED

The phase file says *"CI-enforced. A PR failing any gate cannot merge."*
This repo has no CI system at all — no workflow, no pipeline, nothing that
runs on a push. `backend/eval/shipping_gates.py` is a runnable evaluator with
distinct exit codes (0 pass · 1 failed or unmeasurable · 2 cannot run ·
**3 hard zero violated**) and its header records the wiring:

```
python -m eval.shipping_gates --metrics metrics.json
```

The evaluator RUNS the two delegated Phase 0 suites itself (a pytest
subprocess with `ENABLE_SCHEDULER=false`), so those two gates need no CI to be
answered — `--skip-delegated` turns them into `DELEGATED_NOT_RUN`, which still
blocks and is never reported as unmeasured.

*What is needed:* one CI step running that command on every PR touching
analysis code, failing the build on any non-zero exit.
**Owner: repo owner** (choosing and provisioning CI is an infrastructure
decision, not a code change).

### 11.4 Dashboards and alerting are DEFERRED — OPEN

There is no metrics stack: no `prometheus_client`, no scraper, no Grafana,
no alertmanager (Phase 0's firewall counter and Phase 1's coverage metrics
both hand-rolled the exposition format for the same reason). Phase 7 ships
`backend/eval/monitoring.py` — every Task 7.4 signal as a function — and a
read-only `/monitoring.json` on the ledger console. **`alert` on a signal is
a computed flag, not a page. Nobody is paged by anything in this repo.**

*What is needed:* a metrics backend, a scrape of `/monitoring.json` (or a
proper exporter), retention so drift is visible over months, and alert routes
for `policy_state_staleness`, `exposure_staleness_p90` and the
rejection-reason collapse. **Owner: repo owner.**

### 11.5 Eight of the ten monitoring signals cannot be computed today — OPEN

Not a defect in the signals: there is nothing running to measure. Each
refuses with its own reason rather than reporting a healthy-looking zero.

| Signal | Why it refuses | Closed by |
|---|---|---|
| `firewall_deletion_rate` | **the denominator is not persisted** — see §11.6 | §11.6 |
| `exposure_staleness_p90` | the exposure ledger is empty | §5 |
| `policy_state_staleness` | no regime state is registered | §8 |
| `calibration_drift` | calibration is disabled and locked; no fitted model | §9.4 |
| `rejection_reason_histogram` | no canonical record exists; V5 is unserved | §10.3 |
| `publish_latency_p95` | nothing times the V5 path | §9.6 |
| `frontier_calls_per_event` | no V5 FRONTIER (falsifier) call has ever been recorded | §10.2, §10.3 |
| `small_calls_per_event` | no V5 SMALL-model (entailment judge) call has ever been recorded | §10.3 |

`divergence_queue_volume` and `coverage_gap_depth` DO report — they are
counts over tables that exist, and zero is a genuine measurement there.

The frontier and small-model counts are **separate signals on purpose**
(review round 1, M-1): the entailment judge is spec §18's rung 3 and the
falsifier is rung 4, and §18 gates only the frontier ratio. Folding the
judge into the frontier count would make a cheap system look like it was
breaching the one budget that is gated; dropping it would make
small-model spend the place cost hides.

### 11.6 The firewall does not persist the sentences it examined — OPEN

`firewall_deletion` stores every DELETED sentence. Nothing stores the number
of sentences EXAMINED — the firewall counts those in-process and
`app/output/firewall.py::metrics_text` exposes them per-process only. So the
deletion **rate**, which is both a Task 7.4 signal and a spec §17.2 shipping
gate (`= 0` on PRIMARY prose), cannot be computed from the database: a rate
built from the deletions alone is 1.0 forever.

Today `eval.monitoring.firewall_deletion_rate()` reports the COUNT and
refuses the rate unless a caller supplies the denominator it measured; the
harness supplies it from its own firewall runs, so the shipping gate is
computable in the harness and not in production.

*What is needed:* a persisted `sentences_examined` counter (a column on a
per-event prose record, or a small counters table) written by whatever
serves the compiled path. Small, and blocked behind V5 having a serving path
at all. **Owner: repo owner / whoever wires V5 serving.**

### 11.7 Four metrics the label schema cannot express — OPEN

Session 0's `eval_label` (unmodified, per this phase's constraints) carries
`expected_tier`, `expected_direction`, `expected_mechanism` and
`expected_materiality`. It carries **no** expected directness, graph
distance, evidence grade or section. So four of Task 7.2's metrics exist as
tested functions and are reported by the harness as UNAVAILABLE with the
reason, rather than as 100% because nothing disagreed:

`directness_accuracy` · `distance_accuracy` · `evidence_accuracy` ·
`section_accuracy` (a section key includes a horizon bucket, which no label
states).

*What is needed:* a decision. Either the labeling protocol grows those
fields — which makes labeling meaningfully slower and is a real cost — or
the four metrics are formally dropped from the suite. **They must not stay
in the suite reported as blank forever.** **Owner: repo owner.**

### 11.8 Calibration ECE/Brier: machinery only — OPEN

`eval.metrics.calibration_ece` / `calibration_brier` delegate to Phase 5's
implementations and return `None` over an empty set. Calibration is disabled
and structurally locked, so no record carries a calibrated probability and
the ECE shipping gate (`≤ 0.05`) is REFUSED, not passed. Closed by §9.4.
**Owner: repo owner.**

### 11.9 The cascade router is the harness's, not production's — OPEN

`backend/eval/cascade.py` implements spec §18's routing (deterministic
short-circuit → cache → small model → frontier for PRIMARY-eligible
falsification, MIXED resolution and gate-boundary marginals) and proves the
budget on a 250-candidate fixture against the **deployed** publication gate:
228 of 250 eliminated pre-LLM (91.2%), 12 frontier calls (4.8%, against a
budget of 10%).

It lives under `eval/` because there is no production caller to route for:
V5 has no serving path and the falsifier is deliberately unwired (§10.3).
When V5 is wired into a pipeline this module moves under `app/` and the
pipeline calls it. **Until then, no production request has ever been routed
by it, and the 91.2% is a property of the gate measured on a fixture pool —
not a measurement of a real event's candidate distribution.**

*What is needed:* wire it at V5 cutover; re-measure the ratio on real events.
**Owner: repo owner / whoever wires V5 serving.**

### 11.10 Ripple-family recall counts SECONDARY_RIPPLE rows only — OPEN, and deliberately

A family reached solely by a PRIMARY company is usually a company the
article named, and counting it would let the ripple-coverage metric be
satisfied by exactly the behaviour it exists to measure (V4 surfaced
mentioned companies and missed exposed ones). Session 0's scorer makes the
same choice, and the two must agree or the same corpus produces two
different recalls.

*Recorded here rather than buried:* it is a judgement, it penalises a system
that correctly promotes a ripple company to PRIMARY, and an owner may
reasonably rule the other way. **Owner: repo owner** (a ruling, not data).
