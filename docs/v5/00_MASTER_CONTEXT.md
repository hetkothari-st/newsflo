# NEWSFLO V5 — MASTER CONTEXT
## Read this before executing any task file in this directory.

You are implementing NewsFlo V5, a financial news impact engine that identifies which listed Indian companies are materially affected by a news event, through which mechanism, in which direction, at what magnitude, with what evidence.

**Reference specs (read once, keep in context):**
- `NEWSFLO_V5_BUILD_SPEC.md` — full architecture
- `NEWSFLO_V5_ADDENDUM_RIPPLE_COVERAGE.md` — ripple discovery

**Execution order:** `PHASE_0` → `PHASE_7`. Do not start a phase until the previous phase's DEFINITION OF DONE passes in CI.

---

## THE ONE RULE

> Every statement shown to a user must be reconstructible from stored structured records with provenance.

If a number, date, company fact, or causal claim cannot be traced to a database row that traces to a source URL, it must not exist in the output. This is enforced structurally (§PHASE_0 firewall), not by instruction.

---

## NON-NEGOTIABLE INVARIANTS

Encode each as a test. A build that violates any of these must fail CI.

1. Only the Canonical Reducer writes `company_impact`. Enforced by DB role privileges.
2. No LLM output may contain a numeral that reaches the user.
3. Market price movement never influences fundamental direction, materiality, evidence, or tier.
4. `directness`, `graph_distance`, `discovery_source`, and `publication_tier` are four separate fields. Never concatenated, never merged, never inferred from one another.
5. A failed PRIMARY gate does not demote to SECONDARY. Each tier gate is evaluated independently.
6. `MACRO_CONTEXT` may never carry a company list.
7. `SECONDARY_RIPPLE` requires a non-null `mechanism_id`.
8. Directional claims require `sign_consistency >= 0.60`. Below that, publish `MIXED` or `UNCERTAIN`.
9. MIXED is never collapsed into a direction.
10. Any claim of type `PASS_THROUGH`, `HEDGE`, `COMPETITIVE`, or `TIMING` requires company-named filing evidence.
11. No exposure row with `measurement = 'MODELLED'` may exist without `reviewed_by`.
12. Rejected candidates are retained with a reason and are visible in the review console.
13. **No model may write `mechanism_edge`. Ever.** Every row is authored or approved by a named human: `IO_TABLE` and `EMPIRICAL` rows are queued unreviewed and become walkable only through `edge_review.approve_edge`; `AUTHORED` rows are written by a person in the first place. No module that constructs an LLM client, and no code path fed by model output, may INSERT or UPDATE that table.

    *Why this is an invariant and not an implementation detail.* Everything V5 says about a mechanism — its section label, its directness, its distance, whether it publishes at all — is read off a `mechanism_edge` row. V4 let a model name mechanisms freely and 45 of 58 stored ids resolved to nothing, 13% of them proposing price-driven channels invariant 3 exists to refuse (`decisions/ADR-002`). V5 is immune to that **only** while this holds: the moment a model can write the table, V5 inherits V4's defect with V5's authority behind it. The immunity is conditional, so it is stated.

---

## THE FABRICATION GUARD — READ THIS TWICE

You are building a system whose entire value is provenance. The dominant failure mode of this project is that **you generate plausible data to make a module runnable.**

**You must never:**
- Populate `company_exposure`, `company_modifier`, `io_coefficient`, or `transmission_empirical` with values you produced from your own knowledge.
- Write seed/fixture data containing realistic-looking financial figures outside of clearly named test fixtures.
- Invent pass-through ratios, hedge ratios, input cost shares, segment weights, or elasticities.
- Fill a gap with a "reasonable default" and move on silently.

**When a task requires data you do not have:**
1. Build the schema, the parser, and the loader.
2. Leave the table empty.
3. Write an integration test asserting the pipeline degrades correctly on empty data (abstains, does not publish).
4. Add the required dataset to `DATA_GAPS.md` at repo root with: table, what is needed, where it comes from, who must supply it.
5. Report it explicitly in your summary. Do not bury it.

Fixtures used for tests must live under `tests/fixtures/` and every numeric value in them must carry a `"_fixture": true` marker. A test asserting no fixture data reaches production tables must exist.

---

## STACK ASSUMPTIONS

Match the existing repo. If it differs, adapt and note it.
- Python 3.11+, FastAPI, PostgreSQL, SQLAlchemy + Alembic
- pytest, hypothesis (property tests), pytest-postgresql
- LLM access via existing provider adapter / StageRouter (Claude primary)
- Existing V4 code is present. You are refactoring toward V5, not greenfielding. Preserve migrations history.

---

## WORKING METHOD FOR EVERY TASK

1. Read the phase file completely before writing code.
2. Inspect the existing repo for what already exists. Do not duplicate V4 modules — refactor them.
3. **Write the tests in the TESTS section first. They must fail.**
4. Implement until they pass.
5. Run the full suite. No regressions permitted.
6. Report: what was built, what tests pass, what data gaps were logged, what you could not complete and why.

If a task's instruction conflicts with an invariant above, the invariant wins. Stop and report the conflict rather than resolving it yourself.

---

## HOLLOW IMPLEMENTATION CHECK

Before declaring any phase complete, verify you have not built a system that *looks* finished but computes on invented inputs:

- [ ] Does every table populated by this phase trace to a real external source?
- [ ] If I truncate all tables, does the pipeline abstain rather than produce output?
- [ ] Is there any code path where a missing parameter is replaced by a hardcoded plausible value?
- [ ] Does `DATA_GAPS.md` honestly reflect what is still missing?

Answer these in your completion report. A phase that passes its tests on fabricated data is a failed phase.
