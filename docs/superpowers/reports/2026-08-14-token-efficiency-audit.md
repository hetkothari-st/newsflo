# Token-Efficiency & Budget Audit (spec §7 A-J, §13, §14)

Task 5 of the Claude-provider migration (`.superpowers/sdd/2026-08-14-claude-provider-migration/task-5-brief.md`).
Audit only — code changes are made ONLY where a genuine violation was found. None were found for A-J or
§13, which are already satisfied by the corrective-V4 architecture as built. §14 is PARTIAL: the
sector-definition corpus rides every stage's static prefix; deferred as a future optimization rather than
fixed this session — see the §14 section below for the full rationale. No prompt text was touched, so
`IMPACT_PROMPT_VERSION` was not bumped and the offline benchmark was not re-run (see Step 4).

## A. Never send information a stage does not need

**SATISFIED.**

- `backend/app/analysis/impact_graph/engine.py:114-125` `_facts_suffix` — full event record (facts +
  quantities + up to 12 evidence lines), used by the graph-anchoring stages only:
  `initial_shocks` (`engine.py:1628-1633`, the broad-path anchor) and `narrow_graph`
  (`engine.py:1396-1402`, the narrow-path anchor) — the two stages that "genuinely need the complete
  event record" (docstring). Every other stage builds its suffix from `_compact_suffix`.
- `backend/app/analysis/impact_graph/engine.py:128-139` `_compact_suffix` — event line + numbered
  canonical facts only, "never the prose block, never article evidence, never the whole graph"; every
  downstream stage (company mapping, ripple discovery, verification) builds its suffix from this, not
  from raw article text.
- `backend/app/analysis/impact_graph/engine.py:1037-1052` `_verify_companies` — the suffix handed to
  `VERIFY_COMPANIES_PROMPT` is `_compact_suffix(facts, extra=listing)` where `listing` is one clipped
  line per candidate (mechanism truncated to 140 chars) plus its ancestor path — metadata, not the raw
  article.
- Stage 1 (`extract_facts`, `engine.py:1303-1308`) is the only call that receives the raw article body —
  correct, since fact extraction is the stage whose job is to read it.

No stage was found receiving unrelated candidate companies, irrelevant sectors, or the raw article where
metadata would do.

## B. No deterministic rediscovery

**SATISFIED.** Ticker resolution (`backend/app/companies/candidates.py`) contains no LLM call (`grep`
for `router.call` in that file returns nothing) — candidate pools, alias matching and sector filtering
are plain DB/Python code. Section dedup and cross-alert dedup are enforced in
`backend/app/analysis/impact_graph/publication_gate.py:333-339` (`_check_duplicate_free`) and
`:576-611` (`finalize_alert_decisions`), both pure deterministic functions. Deterministic sorting/ranking
lives in `_rank_key` (`publication_gate.py:565-569`). No prompt asks the model to confirm a ticker
exists, sort companies, or format a label.

## C. Static prefixes / compact dynamic context

**SATISFIED.** `prompts.static_prefix()` (`backend/app/analysis/impact_graph/prompts.py:699-706`)
returns the byte-identical `SYSTEM_PROMPT + SECTOR_DEFINITIONS [+ stage prompt]` for every call of a
given stage, deliberately built "byte-identical across calls of the same stage" for cache locality; all
dynamic content rides `dynamic_suffix`/`compact_suffix`, never spliced into the static text. Task 2's
`cache_control` breakpoints on this static prefix were audited separately (out of scope here; not
re-verified).

## D. Cache immutable stage results

**SATISFIED.** `backend/app/analysis/impact_graph/router.py:266-317` (`_cache_get`/`_cache_put`) persist
to `LLMStageCache` keyed by a fingerprint (`router.py:229-264`) that hashes stage, provider, model,
prompt version, schema version, knowledge-registry version, static prefix, the caller's semantic seed,
schema JSON, the v4-strict flag, gate `POLICY_VERSION`, and variant (full/compact) — any truth-affecting
change is an explicit cache miss. A write only happens when `self.quality == "authoritative" and
self._served_variant == "full"` (`router.py:191-196`), so a degraded/fallback/compact answer can never
poison the cache (this is also §8's requirement, confirmed here as a side effect).

## E. Prevent duplicate stage calls for the same content/version

**SATISFIED.** `router.call()` (`router.py:137-197`) looks up the fingerprint before dispatching to any
provider; a hit returns the cached result with `self.stage_cache_hits += 1` and zero provider traffic
(`router.py:162-168`), logged as `call_skipped ... reason=stage_cache_hit`. `cache_seed` lets a caller
pin the fingerprint to a stable semantic key instead of raw prompt bytes, so an unrelated prompt
annotation (e.g. a relationship-cache note) can't force a spurious re-call for the same underlying
question (`router.py:150-156`). Pipeline-level `v3:` result-cache dedup was audited in an earlier task
(out of scope here).

## F. No rerun after deterministic rejection

**SATISFIED.** `_GraphState.rejected_tickers` (`engine.py:73`) accumulates every ticker a verifier
rejects (`engine.py:745`, `:959`, `:1074`, `:1539` — schema-invalid entries and explicit verifier
rejections both land here) and every candidate-pool builder filters it out before proposing candidates
again: `engine.py:461-464` (`_map_companies_for_node`'s candidate pool), `:847`
(ripple-frontier candidate pool), `:1450` and `:1475` (narrow single-call candidate pools). A rejected
ticker cannot re-enter any LLM stage within the same run — there is no retry loop that clears
`rejected_tickers`.

## G. No prose before validated data

**SATISFIED.** In `backend/app/pipeline.py`, the publication gate runs and `entries` are filtered to
non-`excluded` tier (`pipeline.py:889-949`) and `AlertCompany` rows are built/persisted
(`pipeline.py:973-996`) **before** `refine_alert` is ever invoked (`pipeline.py:1000-1016`). Inside
`refine_alert` (`backend/app/analysis/refinement.py:734-826`), the per-company `why` text for a gated
alert is derived deterministically from the already-gate-validated `mechanism` field
(`refinement.py:800-804`, `is_gated()` check), not generated as free prose before validation. The
`is_gated()` check is structural (checks `gate_state`/`display_tier` on the row itself,
`publication_gate.py:126-156`), not a settings-flag read, so this ordering holds regardless of the
`impact_engine_v4_strict` flag once an alert has actually gone through the gate.

## H. No separate LLM just for section-title generation

**SATISFIED.** No `generate_title`/section-title LLM call exists anywhere under `backend/app`. The two
`grep` hits for "title" outside prompts/schemas are `backend/app/routers/stock_deep_dive.py:68,130`,
which read a stored `layer["title"]` value (deterministic, already-persisted) into the API response —
not an LLM call.

## I. No separate LLM just to explain a price move

**SATISFIED for the V4/gated path**, which is the path this audit is scoped to (task brief: "V4 engine
lives in backend/app/analysis/impact_graph/"). `refinement.py:785-799,800-804`: for a gated alert, the
legacy `generate_impact_whys` call (which used to hand the model the measured `excess_move_pct` and ask
it to invent a story) is skipped entirely — `ac.why` is the gate-validated `mechanism`, sanitized
deterministically (`_sanitize_mechanism`). The legacy branch (`refinement.py:805-826`,
`generate_impact_whys`) still exists and still runs for a **non-gated** (legacy, pre-V4) alert only;
this is the explicitly user-locked 3-tier legacy behavior (project memory: "Ripple sections locked" /
"3-tier lock preserved flag-off") and is out of scope for this migration per the brief's own framing —
not touched.

## J. Counterfactual inside the verifier, not a separate call

**SATISFIED.** The counterfactual instruction is the closing paragraph of `VERIFY_COMPANIES_PROMPT`
itself (`prompts.py:527-532`, "COUNTERFACTUAL: for every company you keep, answer counterfactual...")
and `counterfactual` is a field on the same `verify_companies` schema response
(`backend/app/analysis/impact_graph/schemas.py:431-439,585-591`), consumed by
`publication_gate._check_counterfactual_valid` (`publication_gate.py:432-444`). There is no separate
kg-6/counterfactual LLM call anywhere in `engine.py` or `verification.py`.

## §14. Model context minimization (sector-definition corpus)

**PARTIAL — FUTURE optimization noted, not fixed.** Every `static_prefix()` call site in `engine.py`
(lines 597, 611, 1056, 1243, 1305, 1398, 1509, 1630, 1805, 1915 — i.e. every stage: facts, shocks, direct
companies (narrow), ripple, ripple companies (narrow), verify-companies, verify-edges, completeness,
escalation) routes through `prompts.static_prefix()` (`prompts.py:699-706`), which unconditionally
concatenates the full `SECTOR_DEFINITIONS` corpus (`backend/app/analysis/schemas.py:67-90`, ~17 sector
entries) onto `SYSTEM_PROMPT` for every one of them. There is no stage-scoped trimming today.

At least two stages plausibly don't need the full corpus: `extract_facts` (the prompt's own instructions
never reference sectors — it is pure event extraction from the article) and `verify_edges` (edge
verification is about causal-mechanism specificity, not sector taxonomy). `SECTOR_DEFINITIONS` itself is
small (~230 words / roughly 300-350 tokens), so the win is modest per call but recurs on every stage of
every article.

**Verdict: left as-is, recorded as a FUTURE optimization, not fixed now**, for two reasons specific to
this codebase's history:
1. The STRONG default in this task's brief is "DO NOT change prompts" — any change to what rides
   `static_prefix` requires bumping `IMPACT_PROMPT_VERSION` and a clean re-run of
   `tools/offline_benchmark.py` (every metric == 1.0). That is a real cost for a token saving this small,
   and risks the exact failure mode logged in project memory (`project_bundling_regression_proven.md`):
   changes to what rides a shared prefix/call shape have previously cost 35-79% company recall. Per-stage
   trimming of a static prefix is a smaller change than bundling calls, but it is still a prompt-shape
   change and deserves the same benchmark discipline before shipping, not a same-session edit.
2. `static_prefix()` is deliberately shared/byte-identical **per stage** already (comment at
   `prompts.py:699-702`) to make the `router.py` cache fingerprint and any Claude-side prompt-prefix
   caching land; trimming it per-stage does not change that property (each stage already has its own
   fixed static prefix today), so this is purely a token-size optimization, not a caching-correctness
   fix — lower priority than anything on the A-J list, all of which are SATISFIED.

No code changed for this item.

## §13. Stage budgets

**SATISFIED.**

- `backend/app/analysis/impact_graph/budget.py:17-95` `ArticleBudget`: `exceeded` (100% of
  input/output/cost ceilings) and `expansion_exhausted` (75% soft stop, "expansion... halts here so the
  REMAINING budget is reserved for verification and ranking") are the two ceilings the engine consults.
- `engine.py:1596-1616` (narrow path) and `engine.py:1711-1721` (broad `_build_graph` path): both branch
  on `budget.exceeded` immediately before the verification calls. When exceeded, verification is
  **skipped** (`_verify_companies`/`_verify_edges` never called), `router.quality = "budget_exhausted"`
  is set, and every already-collected company keeps `verified = False`
  (`engine.py:1599-1600` sets this explicitly before the budget check even runs, so the skip path never
  has to remember to do it).
- Enforcement proof (fail-closed, not just "quality is stamped"):
  `backend/app/analysis/impact_graph/publication_gate.py:456-470` `_check_verified` — availability is
  checked **first, unconditionally**, before the `independently_verified` flag is even read: "a True
  `independently_verified` flag is not a verdict, it is an upstream default... Short-circuiting on the
  flag let that default authorize display — fail-open at the one gate that exists to fail closed." A
  budget-exhausted candidate therefore reaches `REJECT_VALIDATOR_UNAVAILABLE`, never `DISPLAY_ELIGIBLE`,
  regardless of what `independently_verified` happens to hold.
- Existing test coverage for exactly this: `backend/tests/test_v4_invariants.py:439-470`
  `test_inv005_unavailable_validator_fails_closed`, parametrized over `verified in [False, True]`, case 2
  (`test_v4_invariants.py:455-460`) builds a `_graph_company(verified=verified)` result with
  `quality="budget_exhausted"`, runs it through the real persistence path (`_v3_entries`), and asserts
  `gate_state == "REJECT_VALIDATOR_UNAVAILABLE"` and `display_tier == "excluded"` for **both** values of
  `verified` — i.e. budget exhaustion cannot mark an unverified candidate verified, proven end-to-end
  through gate + persistence, not just at the dataclass level. This is the pre-existing "verifier-
  unavailable invariant" the brief asked to locate; no new INV-style test was added to
  `test_v4_invariants.py` since one already exists and already covers the budget-exhaustion path.
- New focused unit test added per the brief's Step 2:
  `backend/tests/test_budget_fail_closed.py::test_exceeded_budget_flags_without_verifying` — pins the
  `ArticleBudget` primitive itself (`exceeded`/`expansion_exhausted` both `True` once a single `record()`
  call clears tiny per-article overrides), one level below INV-005's end-to-end proof.

## Carry-over item: `benchmark_impact_graph.py` filter-stage Gemini client

**SATISFIED — not reachable from the default analysis path.**
`backend/benchmark_impact_graph.py:118-124` (`run_old`) builds a client via
`build_client(settings.groq_api_keys, settings.gemini_api_key or None, gemini_paid_api_key=...)`. This
function is **only** invoked from `main()` at `benchmark_impact_graph.py:193`
(`run = (run_old if args.old else run_v3)(event, session)`), gated behind the explicit `--old` CLI flag
(`benchmark_impact_graph.py:168`, `action="store_true"`, default off). The default path is `run_v3`
(`benchmark_impact_graph.py:62-115`), which is hard-pinned to Claude only:
`if not settings.claude_api_key: raise RuntimeError("no Claude key configured; benchmark never runs on
Groq")` (`:74-75`) and constructs `StageRouter(claude_api_key=..., groq_client=None, ...)` (`:76-79`),
passing `groq_client=None` unconditionally "so even LLM_FALLBACK_ALLOWED=true cannot route a benchmark
run through Groq." `backend/benchmark_impact_graph.py` is also not imported by any application module —
`grep -r benchmark_impact_graph backend` only matches the file itself and its own fixture
(`backend/benchmarks/impact_events.json`), confirming it is a standalone manual CLI tool, never on the
`app.pipeline` / `app.analysis.impact_graph.engine` request path. `settings.gemini_api_key` is read only
inside this opt-in legacy-comparison branch, which is exactly what it exists for (`--old` runs the
pre-migration cascade for A/B comparison) — this is not a violation of §9's "never silently call a
different provider" rule because it is neither silent (explicit `--old` flag) nor reachable from
production traffic.

## Files changed

- `docs/superpowers/reports/2026-08-14-token-efficiency-audit.md` (this report, new)
- `backend/tests/test_budget_fail_closed.py` (new, per Step 2)

No other file was modified. No VIOLATION was found in A-J, §13, or §14, so no production code changed.
`backend/tests/test_v4_invariants.py` was read but not modified — the invariant the brief asked to
locate (INV-005 / `test_inv005_unavailable_validator_fails_closed`) already exists and already covers
the budget-exhaustion path end to end.

## Step 4 — prompt/context change disclosure

**No prompt or context change was made.** `IMPACT_PROMPT_VERSION` (`prompts.py:16`, currently `"kg-6"`)
was not bumped, and `tools/offline_benchmark.py` was not re-run, per the brief's instruction to only take
this step "if any prompt/context change was made."

## Test evidence

```
cd backend && .venv/Scripts/python.exe -m pytest tests/test_budget_fail_closed.py tests/test_v4_invariants.py -v
...
49 passed, 3 warnings in 6.51s
```

All 49 tests pass, including the new `test_exceeded_budget_flags_without_verifying` and both
parametrizations of the pre-existing `test_inv005_unavailable_validator_fails_closed`.
