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

## This file is an index

The gaps themselves live in [`DATA_GAPS/`](DATA_GAPS/), one file per
topic. They were split out of this file on 2026-08-17 for one reason:
several sessions append to it at once, and a single 1,600-line document
that everybody edits at the bottom is a merge conflict on every branch.
Nothing was dropped in the move and no section was renumbered.

**Before serving V5, read the
[V5 SERVING CUTOVER CHECKLIST](DATA_GAPS/cutover-checklist.md).** It is not a
gap list — it is the set of settings that are correct while V5 is parallel and
unserved, and wrong the moment it is not.

| topic | sections | what it holds |
|---|---|---|
| [Gate Zero corpus](DATA_GAPS/gate-zero-corpus.md) | §1 · §2 | The labeled corpus everything else waits on, and the events whose article has no stored analysis. |
| [Phase 0 gate inputs and the historical backfill](DATA_GAPS/phase0-gate-inputs.md) | §3 · §4 | The four publication-gate inputs with no source, and the V4 → V5 `company_impact` backfill. |
| [The exposure ledger itself](DATA_GAPS/ledger-population.md) | §5 | The big one: `company_exposure` and everything it needs, plus the first eleven imported rows and the sub-gaps recorded with them. |
| [Phase 2 — the sensitivity engine](DATA_GAPS/phase2-sensitivity-engine.md) | §6 | The engine has never seen a real filing. |
| [Phase 3 — ripple discovery](DATA_GAPS/phase3-ripple-discovery.md) | §7 | `mechanism_edge`, `io_coefficient` and the industry mapping: the ripple machinery has no economy to run on. |
| [Phase 4 — the policy registry](DATA_GAPS/phase4-policy-registry.md) | §8 | Every modifier awaiting real parameter values, and its owner. |
| [Phase 5 — empirical cross-check and calibration](DATA_GAPS/phase5-empirical-calibration.md) | §9 (§9.1–§9.8) | No market history and no corpus; the estimator questions the owner must answer. |
| [Proposed spec amendments](DATA_GAPS/proposed-spec-amendments.md) | §9.9 | The §7.2-form amendments awaiting the owner's disposition. Split out because an amendment is reviewed and disposed of on its own cadence. |
| [Phase 6 — the adversary](DATA_GAPS/phase6-adversary.md) | §10 | The falsifier has never argued with a real record. |
| [Phase 7 — harness and monitoring](DATA_GAPS/phase7-harness-monitoring.md) | §11 | The harness has never scored anything and nothing watches production. |
| [The PRIMARY liquidity gate](DATA_GAPS/primary-liquidity-gate.md) | §12 | **Blocker on PRIMARY cutover** — the liquidity rule is unenforced. |
| [City gas distribution](DATA_GAPS/city-gas-distribution.md) | §13 | No mechanism edge and no policy modifier for the CGD buyer side. |
| [What annual reports actually disclose](DATA_GAPS/filing-disclosure-limits.md) | §14 | MEASURED: Indian annual reports do not carry the raw-material breakup the ledger needs, and the vocabulary sub-gap closed with that run. |
| [The administered-price fertilizer complex](DATA_GAPS/fertilizer-complex.md) | §15 (fertilizer) | No mechanism, no tag and no shock variable. NOTE: two sections carry the number 15 in the source file; both are preserved as written. |
| [MOSPI Supply-Use at ripple-family granularity](DATA_GAPS/mospi-supply-use.md) | §15 (MOSPI) | MEASURED: the published IO tables are too coarse for a ripple family. The second section numbered 15. |
| [The CEAT proof-of-life run](DATA_GAPS/ceat-proof-of-life.md) | §16 | MEASURED: one company, one shock, end to end — and the nine defects it exposed, none fixed. |
| [V5 SERVING CUTOVER CHECKLIST](DATA_GAPS/cutover-checklist.md) | checklist | **Read before serving V5.** Not gaps in the data — settings that are correct while V5 is parallel and unserved, and wrong the moment it is not. |
| [Not gaps](DATA_GAPS/not-gaps.md) | closing | What is deliberately absent from this file, and why. |

---

## Adding a gap

Put it in the topic file its section belongs to, and change nothing
here. A **new** topic gets its own file in `DATA_GAPS/` and exactly one
row in the table above — one line per topic file is the whole point, and
prose creeping back into this file is what the split undoes.

Section numbers are global and monotonic across the whole directory: the
next gap is §17 wherever it lands. (Two sections carry the number 15 —
`fertilizer-complex.md` and `mospi-supply-use.md`, authored in parallel.
They are preserved as written rather than renumbered, because prose and
tests elsewhere already cite them.)
