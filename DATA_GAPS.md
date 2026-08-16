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
| **What is needed** | **50 labeled events: 40 crude-shock events + 10 null events** (financial news that should produce no company impact). Per event: expected PRIMARY companies, expected ripple families, expected ABSENT companies, expected direction per company, free-text rationale. |
| **How many labelers** | **Two independent labelers per event**, event-only, without seeing system output (`docs/v5/08_PHASE_7_eval_harness.md` labeling protocol — anchoring destroys the label's value). Disagreements resolved in `/eval/adjudicate`; anything unresolved stays `DISPUTED` and is excluded from precision denominators. |
| **Where it comes from** | Human judgment over already-ingested articles in the `articles` table. Not derivable from any external dataset and **not generatable by the system being measured** — a corpus we produced would measure our own imagination. |
| **Who must supply it** | **The repo owner (user).** Two people, roughly 5–8 person-days total. |
| **Tooling ready** | `backend/tools/eval_ui.py` (labeling + adjudication UI, port 8600), `backend/tools/eval_import.py` (CSV/JSON import for offline spreadsheet labeling), `backend/scripts/score_baseline.py` (scores and emits `BASELINE.md`). |
| **Blocked until closed** | `BASELINE.md` does not exist, so V5 Phase 0 cannot start. The scorer refuses to run on an empty corpus rather than reporting a meaningless 0% or 100%. |

**Null events are the important half.** Ten of the fifty must be financial
news with no material listed-company impact. They are the only measurement
of whether the system can say nothing, and they are the slice most likely
to be quietly dropped because it is boring to build.

### Closing it

1. Pick the events (40 crude, 10 null) from the `articles` table and load
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

## Not gaps

The V5 exposure ledger, transmission coefficients, pass-through curves and
empirical calibration tables (`docs/v5` Phases 1–5) are **not listed here
yet** — those phases have not started and their tables do not exist. They
join this file when their schemas land, per the fabrication guard.
