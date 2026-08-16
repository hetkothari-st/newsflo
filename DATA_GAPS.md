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
| **What is needed** | **40 labeled events in total: 30 real crude-shock events + 10 null events** (financial news that should produce no company impact), exactly as `EXECUTION_CONTRACT.md` §2 states. Per event: expected PRIMARY companies, expected ripple families, expected ABSENT companies, expected direction per company, free-text rationale. |
| **How many labelers** | **Two independent labelers per event**, event-only, without seeing system output (`docs/v5/08_PHASE_7_eval_harness.md` labeling protocol — anchoring destroys the label's value). Disagreements resolved in `/eval/adjudicate`; anything unresolved stays `DISPUTED` and is excluded from precision denominators. |
| **Where it comes from** | Human judgment over already-ingested articles in the `articles` table. Not derivable from any external dataset and **not generatable by the system being measured** — a corpus we produced would measure our own imagination. |
| **Who must supply it** | **The repo owner (user).** Two people, roughly 5–8 person-days total. |
| **Tooling ready** | `backend/tools/eval_ui.py` (labeling + adjudication UI, port 8600), `backend/tools/eval_import.py` (CSV/JSON import for offline spreadsheet labeling), `backend/scripts/score_baseline.py` (scores and emits `BASELINE.md`). |
| **Blocked until closed** | `BASELINE.md` does not exist, so V5 Phase 0 cannot start. The scorer refuses to run on an empty corpus rather than reporting a meaningless 0% or 100%. |

**Null events are the important quarter.** Ten of the forty must be financial
news with no material listed-company impact. They are the only measurement
of whether the system can say nothing, and they are the slice most likely
to be quietly dropped because it is boring to build.

### Closing it

1. Pick the events (30 crude, 10 null) from the `articles` table and load
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

## 3. Phase 0 gate inputs that do not exist yet — OPEN

Phase 0 built the publication gate's full §7.4 structure
(`backend/config/gates.yaml` + `backend/app/core/gates.py`), but four of its
inputs have no source in this repo. **None of them is defaulted to a
plausible value.** Each arrives at the gate as `None` ("not known"), and
`config/gates.yaml` states explicitly, per tier, what an unknown means —
fail-closed for `PRIMARY`, permissive for `SECONDARY_RIPPLE`.

| Input | Gate rule | Today | Supplied by |
|---|---|---|---|
| `empirical_status` | PRIMARY requires `AGREE` or `NO_DATA` | the V4 adapter emits the literal truth, `NO_DATA` — there is no empirical calibration table | Phase 5 |
| `adv_20d_inr` (liquidity) | `min_adv_inr` | `min_adv_inr: null`, so the rule is not evaluated at all | Phase 1/2 (liquidity feed) |
| `shock_magnitude_confidence` | `< 0.5` ⇒ macro-only ⇒ company REJECTED | never supplied; unknown does not block | Phase 2 (sensitivity engine) |
| `exposure_stale` | any STALE exposure ⇒ REJECTED | hard-coded `False` **because no exposure ledger exists** — nothing can be stale | Phase 1 |

**Owner:** the V5 phases themselves, not the repo owner. Listed here so the
gate is never read as "fully evaluated" today.

## 4. Historical `alert_companies` → `company_impact` backfill — OPEN

`backend/scripts/backfill_company_impact.py` is **committed and has not been
run** against any database. Two ambiguities are deliberately unresolved:

* legacy rows predate `alerts.content_key`, so they have **no
  `analysis_version`** — the script skips them rather than invent an
  identity;
* the V4 discovery vocabulary values `EXPOSURE_RULE`, `RIPPLE_DISCOVERY`,
  `ESCALATION`, `COMPLETENESS`, `CURATED` have **no V5 twin that is not a
  guess** — those rows get `discovery_source = NULL` and
  `needs_reanalysis = 1`.

**Owner:** repo owner, whenever the historical corpus is wanted in canonical
form. Running it is a deliberate act; nothing schedules it.

---

## Not gaps

The V5 exposure ledger, transmission coefficients, pass-through curves and
empirical calibration tables (`docs/v5` Phases 1–5) are **not listed here
yet** — those phases have not started and their tables do not exist. They
join this file when their schemas land, per the fabrication guard. Phase 0
created **no** financial data: it touched no exposure, coefficient or
empirical table, and the only row any Phase 0 migration writes is the
reducer-version fence (`supported_version('r5.0.0')`), which is policy, not
data about the world.
