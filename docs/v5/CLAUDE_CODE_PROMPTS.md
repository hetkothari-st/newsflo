# NEWSFLO V5 — CLAUDE CODE SESSION PROMPTS
## Copy-paste, one session at a time, in order.

**Setup once:**
```bash
mkdir -p docs/v5 && cp -r /path/to/newsflo_v5_tasks/* docs/v5/
git add docs/v5 && git commit -m "docs: V5 spec and task pack"
```

**Rules for every session:**
- One session per phase. Never combine.
- Start each session fresh (`/clear` or new session). Context from a previous phase causes drift.
- Do not start session N+1 until session N's verification block passes.
- After every session, run the VERIFY prompt at the bottom of this file.

---

# SESSION 0 — GATE ZERO TOOLING
*(The labels themselves are human work. This session builds the tooling and the scorer.)*

```
Read docs/v5/EXECUTION_CONTRACT.md §2 and §3, and docs/v5/00_MASTER_CONTEXT.md.

Build the Gate Zero measurement tooling only. Do not touch any analysis code.

1. Schema + migration for eval_event and eval_label (see docs/v5/08_PHASE_7_eval_harness.md
   Task 7.1). Support two independent labelers per event and a DISPUTED state.

2. A minimal server-rendered labeling UI at /eval/label:
   - shows ONE event (headline + body) with no system output visible
   - labeler enters: expected PRIMARY companies, expected ripple families,
     expected absent companies, expected direction per company, free-text rationale
   - saves with labeler identity and timestamp
   - a separate /eval/adjudicate view showing both labelers side by side for
     disagreement resolution, writing DISPUTED where unresolved

3. A CSV/JSON importer so labels can be prepared offline in a spreadsheet and loaded.

4. scripts/score_baseline.py — runs the CURRENT production pipeline over all labeled
   events and emits BASELINE.md with exactly the fields listed in
   EXECUTION_CONTRACT.md §2. Report per-stratum, and separately for null events.

5. Cohen's kappa computation across the two labelers, printed in the report.

Constraints:
- Do NOT generate, seed, or infer any labels. The tables ship empty.
- Do NOT modify existing analysis code, prompts, or pipeline behaviour in any way.
  This session is read-only with respect to the current system.
- Write a test asserting score_baseline.py fails loudly on an empty corpus rather
  than reporting 0% or 100%.

When done, report: files created, how to run the labeling UI, how to run the scorer,
and confirm no analysis code was modified.
```

**Then, before Session 1:** label 40 crude events + 10 null events with two people,
run the scorer, commit `BASELINE.md`. This is human work and takes about a week.
**Do not skip it.**

---

# SESSION 1 — PHASE 0

```
Read docs/v5/00_MASTER_CONTEXT.md in full, then docs/v5/01_PHASE_0_canonical_truth.md
in full. Also read BASELINE.md so you know the current measured state.

Before writing any code:
1. Inspect the existing repo. List which V4 modules currently write company/impact
   data, which stages exist, and how sectioning and prose generation work today.
2. Give me a short plan of how you will wrap existing V4 stages as signal emitters
   WITHOUT deleting their logic.
3. Wait for my confirmation before implementing.

Then implement Phase 0 in the task order given (0.1 through 0.7).
Write the tests in the TESTS section FIRST and confirm they fail before implementing.

Absolute constraints from the master context:
- No financial data may be created. Phase 0 touches no exposure, coefficient, or
  empirical tables.
- Backfill ambiguity in Task 0.7 resolves to NULL + needs_reanalysis=true, never a guess.
- No LLM call anywhere under newsflo/core/.

When done, report against the DEFINITION OF DONE checklist item by item, then answer
the HOLLOW IMPLEMENTATION CHECK from the master context.
```

---

# SESSION 2 — PHASE 1

```
Read docs/v5/00_MASTER_CONTEXT.md and docs/v5/02_PHASE_1_exposure_ledger.md in full.

Confirm Phase 0's definition of done is green before starting. If any Phase 0 test
fails, stop and tell me.

Implement Phase 1 tasks 1.1 through 1.5, tests first.

The single most important constraint in this phase:
You are building the machinery to collect exposure data. You are NOT producing the
data. company_exposure, company_segment, company_financials, pass_through_curve and
company_modifier all ship EMPTY. Every row must later arrive via a reviewed proposal
traceable to a filing.

Specifically:
- The verbatim containment check in Task 1.3 is mandatory. An ExposureProposal whose
  excerpt does not literally appear in the extracted source document is discarded.
  Write an adversarial test proving a fabricated excerpt is rejected.
- The empty-ledger test is the most important test in this phase: with no exposure
  rows, the pipeline must abstain and publish nothing.
- Review UI is server-rendered. No SPA, no React.

Run the extraction pipeline end to end against 5 real annual report PDFs that I will
place in data/samples/ and show me the proposals it generates, including source_page
and excerpt for each.

Report against DEFINITION OF DONE, then the HOLLOW IMPLEMENTATION CHECK, then update
DATA_GAPS.md with the ledger population scope.
```

---

# SESSION 3 — PHASE 2

```
Read docs/v5/00_MASTER_CONTEXT.md and docs/v5/03_PHASE_2_sensitivity_engine.md in full.

Precondition check: confirm company_exposure has real reviewed rows for the crude
company set. If the ledger is empty, STOP and tell me — this phase's tests are
meaningless without real data.

Implement tasks 2.1 through 2.5, tests first.

Critical constraints:
- resolve_param has exactly three outcomes: company value, sector proxy, or raise
  InsufficientParameterData. There is no fourth branch and no default value.
- Delete every code path where an LLM assigns materiality, confidence or magnitude.
  Grep for the prompts and remove them, don't just stop calling them.
- Monte Carlo seed = stable_hash(event_id, company_id, analysis_version) so bands
  are reproducible.

For the 20 hand-computed worked examples: propose the 20 cases and the expected
values first, show me your arithmetic for each, and wait for me to verify them
before you encode them as fixtures. I need to check the math myself.

Report against DEFINITION OF DONE, then HOLLOW IMPLEMENTATION CHECK.
```

**After this session:** run the first expert review (`EXECUTION_CONTRACT.md` §5) to
establish the W11 baseline.

---

# SESSION 4 — PHASE 3

```
Read docs/v5/00_MASTER_CONTEXT.md, docs/v5/04_PHASE_3_ripple_discovery.md, and
docs/v5/NEWSFLO_V5_ADDENDUM_RIPPLE_COVERAGE.md in full.

This is the phase that fixes "the system only finds directly mentioned companies".

Implement tasks 3.1 through 3.7, tests first.

Constraints:
- io_coefficient ships EMPTY until real MOSPI/RBI Supply-Use tables are ingested.
  Build the parser, the Leontief inverse, and the review queue. Do not populate
  coefficients from your own knowledge.
- Verify the Leontief inverse against a 3x3 toy matrix I can check by hand. Show me
  that matrix and the expected inverse before you write the implementation.
- SECONDARY_RIPPLE requires a non-null mechanism_id. Write the test proving no
  publication path exists for an empirically-discovered relationship without an
  authored mechanism.
- Do not tune thresholds to capture expected_marginal families. If cement on crude
  computes to LOW, LOW is the correct answer.
- Ripple precision floor of 0.80 is hard. If a recall improvement costs precision
  below that, revert it and tell me.

For the expected_ripple_map fixture: propose the families for a crude +6% shock and
wait for my sign-off. I own that list, not you.

Report against DEFINITION OF DONE with the per-axis coverage diagnostic output shown
in full, then HOLLOW IMPLEMENTATION CHECK.
```

---

# SESSION 5 — PHASE 4

```
Read docs/v5/00_MASTER_CONTEXT.md and docs/v5/05_PHASE_4_policy_horizon.md in full.

Implement tasks 4.1 through 4.4, tests first.

Constraints:
- Scaffold the policy_modifier registry schema and loader. Leave every parameter
  value NULL. Do NOT fill in levy rates, thresholds, ceilings or effective dates
  from your own knowledge — those are supplied by a named human owner and logged in
  DATA_GAPS.md.
- Unknown or stale regime state widens the uncertainty band and caps evidence grade
  at C. It never assumes a default regime.
- All three horizons are persisted and returned. Make single-horizon collapse
  structurally impossible at the schema level.
- Modifier application is deterministic and LLM-free.

Write the tests using fixture modifier parameters marked "_fixture": true so I can
verify the transfer function math independently of the real values.

Report against DEFINITION OF DONE, then HOLLOW IMPLEMENTATION CHECK, then list every
modifier awaiting real parameters with its owner field.
```

---

# SESSION 6 — PHASE 5

```
Read docs/v5/00_MASTER_CONTEXT.md and docs/v5/06_PHASE_5_empirical_calibration.md in full.

Implement tasks 5.1 through 5.5, tests first.

Constraints:
- Empirical CONFLICT caps tier at SECONDARY_RIPPLE and queues for review. It never
  auto-rejects and never overrides the fundamental call.
- If the labeled corpus is not yet large enough to fit calibration, ship with
  calibration DISABLED and calibrated_p = null. Do not fit on synthetic or
  self-generated labels. Disabled is correct; fake is not.
- Axis C (surprise) and Axis B (market) must be provably unable to affect direction
  or materiality. Write the ast-scan tests and the mutation tests proving it.
- Document your CAR estimator choice and version it.

Show me the estimator design and the shock-detection thresholds before implementing
the event study, so I can sanity-check the methodology.

Report against DEFINITION OF DONE, then HOLLOW IMPLEMENTATION CHECK.
```

---

# SESSION 7 — PHASE 6

```
Read docs/v5/00_MASTER_CONTEXT.md and docs/v5/07_PHASE_6_falsification_sections.md in full.

Implement tasks 6.1 through 6.3, tests first.

Constraints:
- The falsifier must run on a different prompt lineage from the candidate generator,
  and a different model where config permits. Record provider/model on both.
- An objection is sustained unless a rebuttal cites a specific record field or
  evidence id. Free-form argument is not a rebuttal. Default is that the objection
  stands.
- Section identity is a pure function with no LLM involvement.
- Reliance on a crude shock must land in MIXED — INTEGRATED ENERGY, never inside a
  directional OMC section. Write that as a named regression test.
- The review console must show the rejected set with reasons. It is not optional.

Report against DEFINITION OF DONE, then HOLLOW IMPLEMENTATION CHECK.
```

**After this session:** run the second expert review. W11 must be ≤ 2 unanswerable
objections per 20 events.

---

# SESSION 8 — PHASE 7

```
Read docs/v5/00_MASTER_CONTEXT.md and docs/v5/08_PHASE_7_eval_harness.md in full.

Implement tasks 7.1 through 7.5, tests first.

Constraints:
- Wire all shipping gates into CI. The three hard-zero gates (fabricated numerals,
  internal contradictions, false PRIMARY on null events) must fail the build on any
  violation. No warnings, no soft failures.
- Implement the no-regression rule against the main branch baseline.
- Verify the cost cascade: assert frontier_calls / candidates <= 0.10 on the corpus.
- Report every metric per stratum and per sector, never aggregate only.

Then run the full harness against the current corpus and give me the complete
scorecard versus BASELINE.md and versus the twelve W-criteria in
docs/v5/EXECUTION_CONTRACT.md §3.

Report against DEFINITION OF DONE, then HOLLOW IMPLEMENTATION CHECK.
```

---

# VERIFY — RUN AFTER EVERY SESSION

```
Before I accept this phase, answer these precisely:

1. Walk the HOLLOW IMPLEMENTATION CHECK from docs/v5/00_MASTER_CONTEXT.md, item by item.

2. List every database table this phase populated with more than 5 rows. For each,
   state the external source of that data. If the source is "generated by me",
   say so explicitly.

3. Show me any place in the code where a missing value is replaced by a default,
   fallback, or plausible estimate. Quote the lines.

4. If I truncated every table this phase created, what would the pipeline output?
   Show me the actual test that proves it.

5. Which items in the DEFINITION OF DONE are NOT fully met? Be specific. Do not
   round up.

6. What did you have to guess, assume, or work around? List everything, including
   things you think are unimportant.

7. Show me the current contents of DATA_GAPS.md.
```

---

# WHEN A SESSION GOES WRONG

If output looks complete but you suspect it's hollow:

```
Pick 5 rows at random from [table] and, for each, show me the exact source document,
page, and verbatim text the value came from. If you cannot produce that for any row,
delete the row and add it to DATA_GAPS.md.
```

If it starts drifting from the spec:

```
Stop. Re-read docs/v5/00_MASTER_CONTEXT.md. List every invariant your current
implementation violates. Fix those before continuing with anything else.
```

If it proposes an architecture change mid-phase:

```
That change goes through EXECUTION_CONTRACT.md §7.2. Fill in the form: which
W-criterion it improves, the failing metric, the root cause axis, and evidence that
the cause is architectural rather than a data gap. Don't implement anything until
I've reviewed it.
```
