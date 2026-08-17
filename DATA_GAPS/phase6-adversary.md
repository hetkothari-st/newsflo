# DATA GAPS — Phase 6 — the adversary

Part of [`DATA_GAPS.md`](../DATA_GAPS.md), which is now an index over this
directory. **Section numbers are repo-wide and unchanged** — prose, code
comments and tests that cite "§7" or "DATA_GAPS section 11" still mean the
section of that number, wherever it now lives.

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

The Phase 6 reviewer's ordering, recorded here: Q9 is the first of the two to
fix once the falsifier is wired live, because its mapping does double duty —
`BASE_RATE_VIOLATION` is WARN severity (§12.1), so an unanswered Q9 clears the
PRIMARY objection gate on its own, and the same unsourced-parameter question
also stacks on the fail-open `primary.unknown_sector_proxy_passes` key in the
**V5 SERVING CUTOVER CHECKLIST** (item 2) — two independent passes for the
same unmeasured provenance until both are addressed.

*What is needed:* an owner's ruling, or a §7.2 amendment adding an
`UNSIZED` / `PROVENANCE_UNKNOWN` type to §12.1. **Owner: repo owner.**
