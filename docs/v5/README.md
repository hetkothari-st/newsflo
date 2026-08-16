# NEWSFLO V5 — TASK PACK

## READ FIRST

`EXECUTION_CONTRACT.md` — the governance doc. It defines what "done" means, how
changes are controlled, and the Gate Zero rule that must pass before any code.

**Do not start Phase 0 until Gate Zero (§2 of the contract) is complete.**

## How to use with Claude Code

Copy this whole folder into your repo (suggested: `docs/v5/`).

Run one phase per session. Do not paste multiple phases at once — scope dilutes depth.

```
# session 1
claude "Read docs/v5/00_MASTER_CONTEXT.md and docs/v5/01_PHASE_0_canonical_truth.md.
        Inspect the existing repo first. Write the tests in the TESTS section before
        implementing. Report data gaps honestly."

# session 2 (only after Phase 0 CI is green)
claude "Read docs/v5/00_MASTER_CONTEXT.md and docs/v5/02_PHASE_1_exposure_ledger.md. ..."
```

`00_MASTER_CONTEXT.md` is read at the start of every session. It carries the invariants
and the fabrication guard that keep later phases honest.

## Files

| File | Purpose |
|---|---|
| `EXECUTION_CONTRACT.md` | **Read first.** Definition of want, change control, plan, anti-loop rules |
| `00_MASTER_CONTEXT.md` | Invariants, fabrication guard, working method. Read every session. |
| `01_PHASE_0_canonical_truth.md` | Reducer, single writer, claims, entailment firewall |
| `02_PHASE_1_exposure_ledger.md` | Filing-sourced exposure data, review workflow |
| `03_PHASE_2_sensitivity_engine.md` | ΔEBITDA with Monte Carlo bands |
| `04_PHASE_3_ripple_discovery.md` | Tag index, IO tables, coverage harness |
| `05_PHASE_4_policy_horizon.md` | Policy modifiers, three-horizon direction |
| `06_PHASE_5_empirical_calibration.md` | Event studies, calibration, surprise |
| `07_PHASE_6_falsification_sections.md` | Adversarial stage, sections, review console |
| `08_PHASE_7_eval_harness.md` | Corpus, gates, monitoring |
| `NEWSFLO_V5_BUILD_SPEC.md` | Full architecture reference |
| `NEWSFLO_V5_ADDENDUM_RIPPLE_COVERAGE.md` | Ripple coverage reference |

## Run in parallel with the build

Corpus labeling (Phase 7 Task 7.1) and ledger population (Phase 1) are human work
on the critical path. Start both during Phase 0 or the later phases will stall.

## The one thing to watch for

Claude Code will happily produce a complete-looking system populated with plausible
invented financial data. After every phase, ask it to answer the Hollow Implementation
Check in `00_MASTER_CONTEXT.md`, and spot-check five rows of any table it populated
against a real source document.
