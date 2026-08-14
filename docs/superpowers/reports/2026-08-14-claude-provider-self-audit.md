# Claude Provider Migration — Final Self-Audit (spec §24) + Required Report (spec §25)

Repo: `C:\Users\ST269\Desktop\newsflo`. Branch: `provider-claude` (off `master` @ `93c5ca16`).
Spec: `docs/specs/NEWSFLO_CLAUDE_PROVIDER_MIGRATION_SPEC.md`.
HEAD at audit time: `85bbe03d`.

Every answer below was verified by reading the current tree at `85bbe03d` — not the plan, not the
task reports. Line numbers are from that tree. No real API call was made at any point (see the
final section for the evidence chain).

---

## Part 1 — §24 Final Provider Self-Audit (20 questions)

| # | Question | Answer |
|---|---|---|
| 1 | Can Gemini be called by the default analysis path? | **NO** |
| 2 | Can Groq become AUTHORITATIVE without explicit configuration? | **NO** |
| 3 | Can a Gemini cache result be returned for a Claude request? | **NO** |
| 4 | Can fallback output enter an AUTHORITATIVE cache? | **NO** |
| 5 | Can a degraded result be replayed as authoritative? | **NO** |
| 6 | Can authentication failure cause repeated paid retries? | **NO** |
| 7 | Can malformed JSON trigger repeated expensive retries? | **NO** |
| 8 | Can the same stage/content/version call Claude twice unnecessarily? | **NO** |
| 9 | Can the entire sector-definition corpus be sent unnecessarily? | **YES (known, ruled, deferred)** |
| 10 | Can rejected candidates trigger further paid calls? | **NO** |
| 11 | Can budget exhaustion mark a candidate verified? | **NO** |
| 12 | Can fallback bypass existing V4 publication gates? | **NO** |
| 13 | Can provider identity be lost between StageRouter and persistence? | **NO** |
| 14 | Can an old analysis cache bypass the current provider/version policy? | **NO** |
| 15 | Can live mode become enabled by this migration? | **NO** |
| 16 | Does the default router select Claude? | **YES** |
| 17 | Are all tests offline/mocked? | **YES (one scoped caveat — see below)** |
| 18 | Are API keys absent from logs? | **YES** |
| 19 | Is provider/model/quality persisted? | **YES** |
| 20 | Is the implementation token-efficient by design? | **YES (A–J + §13 satisfied; §14 PARTIAL)** |

Only Q9 is a non-clean answer, and it is a *cost* inefficiency, not an unsafe path: it cannot
weaken a financial-safety gate, cannot cause an unbounded spend (the per-article `ArticleBudget`
token ceilings still bind), and was explicitly ruled and deferred during Task 5. It is carried into
Remaining Risks. Nothing else in this audit indicates an unsafe path, so no fix was required before
declaring completion.

### 1. Can Gemini be called by the default analysis path? — **NO**

- `backend/app/analysis/impact_graph/router.py:47` — the router's only provider import is
  `from app.analysis.impact_graph.claude_json import ClaudeJSONClient, ClaudeJSONError`. There is no
  `gemini_json` import anywhere in the module, and the ladder (`router.py:389-459`) has exactly two
  dispatch targets: `_call_claude` and `_call_groq`.
- `backend/app/analysis/impact_graph/gemini_json.py:1-5` — the adapter's own docstring marks it
  **DISABLED**, "no longer imported by the default analysis path… retained as an isolated adapter."
- `backend/app/pipeline.py:1635-1653` `_build_v3_router` — the article-level constructor now passes
  `claude_api_key=settings.claude_api_key or None` and never touches any Gemini key. The
  pre-migration `protected=` / `gemini_api_key=` kwargs are gone from the signature entirely
  (`router.py:73-75`).
- Repo-wide check run for this audit: `grep -rn "gemini_json\|GeminiJSONClient" backend/app --include=*.py`
  returns only two *comment/docstring* mentions (`claude_json.py:8`, `router.py:34`) and the disabled
  module itself. Zero import sites.
- Tests: `backend/tests/test_provider_policy.py::test_gemini_is_not_importable_from_router`,
  `::test_wrong_provider_mode_fails_closed`.
- Scoped exception, not on the default path: `backend/benchmark_impact_graph.py:118-124` builds a
  Gemini client inside `run_old`, reachable only behind the explicit `--old` CLI flag
  (`benchmark_impact_graph.py:168`, default off). Audited in
  `docs/superpowers/reports/2026-08-14-token-efficiency-audit.md` ("Carry-over item"); the default
  `run_v3` path hard-raises without a Claude key and passes `groq_client=None`.

### 2. Can Groq become AUTHORITATIVE without explicit configuration? — **NO**

- `backend/app/analysis/impact_graph/router.py:91-104` — a router only becomes `provider="groq"` at
  construction when `settings.llm_fallback_allowed` is True **and** a Groq client was handed in.
  Otherwise construction raises `StageRouterError`. There is no silent third branch.
- `router.py:118` — `self.quality = "authoritative" if self.provider == "claude" else "fallback"`.
  Quality is earned at construction: a Groq-by-configuration router is `"fallback"` from its very
  first call, never "authoritative for one call then degraded".
- `router.py:435` — the mid-run fallback rung is also gated on
  `settings.llm_fallback_allowed and self._groq is not None`, and `router.py:445` forces
  `self._degrade("fallback")` when it serves.
- `backend/app/pipeline.py:1647-1650` — Groq is not even *handed* to the router unless the opt-in is
  set (`groq_client=groq_client if settings.llm_fallback_allowed else None`): unreachable by
  construction, not merely by policy.
- `backend/app/config.py:39` — `llm_fallback_allowed` defaults to `false`.
- Tests: `test_fallback_quality.py::test_groq_is_never_authoritative`,
  `test_provider_policy.py::test_claude_failure_with_fallback_disabled_fails_closed`,
  `test_fallback_quality.py::test_pipeline_router_is_claude_for_every_article` (asserts
  `router._groq is None` with the opt-in off).

### 3. Can a Gemini cache result be returned for a Claude request? — **NO**

- `backend/app/analysis/impact_graph/router.py:272-278` — the stage-cache fingerprint payload hashes
  `stage, self._primary (provider), model, prompt_version, schema_version,
  KNOWLEDGE_REGISTRY_VERSION, static_prefix, seed, schema JSON, v4_strict flag, POLICY_VERSION,
  variant`. The pre-migration payload had **no provider component** and carried Gemini model names,
  so no key a Claude run can produce will ever match a Gemini-era row. Isolation is structural, not
  a migration script — no cache purge is required.
- Test: `backend/tests/test_provider_cache_isolation.py::test_gemini_era_cache_row_never_matches_claude_fingerprint`
  byte-reconstructs the legacy fingerprint (`test_provider_cache_isolation.py:26-38`), inserts a
  poisoned row under it, and asserts the Claude run misses it and pays for a fresh call
  (`:55-56`).
- Also `test_provider_policy.py::test_fingerprint_includes_provider_and_model`.

### 4. Can fallback output enter an AUTHORITATIVE cache? — **NO**

- `backend/app/analysis/impact_graph/router.py:194-199` — the cache-put guard is **absolute**, not a
  before/after delta: `if self.quality == "authoritative" and self._served_variant == "full"`. Any
  run whose watermark has ever reached `fallback`/`degraded`/`budget_exhausted` writes nothing, for
  the rest of the run, even for stages Claude served perfectly.
- `router.py:311-322` `_cache_put` also stores the quality inside the envelope
  (`{"__cache_envelope": 1, "quality": ..., "result": ...}`) so a future reader can never lose it.
- Tests: `test_provider_policy.py::test_fallback_result_never_cached_as_authoritative`,
  `::test_later_claude_stage_after_a_fallback_is_never_cached` (the run-level watermark case),
  `test_provider_cache_isolation.py::test_malformed_response_is_never_cached`.

### 5. Can a degraded result be replayed as authoritative? — **NO**

- `backend/app/analysis/impact_graph/router.py:303-305` — on a cache hit the stored envelope quality
  is re-applied via `self._degrade(stored.get("quality") or "authoritative")`, so a replay inherits
  the quality it was written with; it cannot launder itself.
- `router.py:342-344` `_degrade` is monotonic against `_QUALITY_ORDER` (`router.py:65`) — quality
  only ever worsens within a run.
- The compact-variant answer is never written at all (`router.py:194`, `self._served_variant ==
  "full"` required), so there is no cheaper-context result in the cache to replay.
- Tests: `test_fallback_quality.py::test_cache_hit_propagates_stored_quality`,
  `test_provider_cache_isolation.py::test_compact_variant_result_not_cached`,
  `test_fallback_quality.py::test_compact_context_result_never_cached_under_full_key`.
- Nuance, checked and clean: `router.py:300-306` treats a *raw* (envelope-less) legacy row as
  `"authoritative"`. Every such row was written by pre-migration code under the old fingerprint
  scheme, which has no provider component — so it is structurally unmatchable by a Claude run (Q3).
  The branch is therefore unreachable in production from this branch's code; it exists only for
  correctness if some other provider mode were ever re-enabled.
  Test: `test_fallback_quality.py::test_cache_hit_of_legacy_raw_row_treated_as_authoritative`.

### 6. Can authentication failure cause repeated paid retries? — **NO**

- `backend/app/analysis/impact_graph/claude_json.py:96-100` — `AuthenticationError` /
  `PermissionDeniedError` map to `ClaudeJSONError(kind="auth")`.
- `claude_json.py:41` — `_COMPACT_RETRYABLE_KINDS = {"schema", "truncated"}`; `"auth"` is not in it,
  so `retryable_with_compact` is False (`claude_json.py:53-55`) and the compact rung at
  `router.py:417` is skipped.
- `backend/app/analysis/impact_graph/router.py:382-387` `_note_auth_failure` sets
  `self.claude_auth_failed = True` for the **whole run**; `router.py:396-399` then short-circuits
  every subsequent stage without touching the API at all.
- SDK-level retries: `claude_json.py:65-69` passes `max_retries=settings.claude_max_retries`
  (default 2, `config.py:31`); the Anthropic SDK does not retry 401/403.
- Tests: `test_provider_policy.py::test_auth_failure_trips_circuit_breaker` (asserts
  `client.calls == 1` after two `call()`s), `::test_auth_breaker_still_allows_the_explicit_groq_fallback`,
  `test_claude_json.py::test_auth_error_maps_to_auth_kind`.

### 7. Can malformed JSON trigger repeated expensive retries? — **NO**

- Structured output is forced, so "malformed JSON" is nearly unreachable in the first place:
  `backend/app/analysis/impact_graph/claude_json.py:90-94` sends one `emit` tool whose
  `input_schema` **is** the stage's V4 schema, with
  `tool_choice={"type": "tool", "name": "emit", "disable_parallel_tool_use": True}`. There is no
  prose parsing (`claude_json.py:141-156` reads `block.input` directly).
- When it does fail, the ladder allows **exactly one** correction rung:
  `backend/app/analysis/impact_graph/router.py:417-430` — the compact retry runs only if
  `exc.retryable_with_compact` (schema/truncated) **and** the caller supplied a `compact_suffix`,
  sleeps `settings.claude_retry_backoff` first, and a second failure ends the ladder. There is no
  loop anywhere: `claude_json.py:18-20` documents "exactly one `messages.create` call per
  generate()".
- Transport/rate-limit/auth kinds get **zero** router retries (the SDK already retried transients) —
  `router.py:412-417` comment + `test_provider_policy.py::test_transport_failure_gets_no_compact_retry`
  (asserts `client.calls == 1`).
- Tests: `test_provider_policy.py::test_schema_failure_gets_one_compact_retry` (asserts the exact
  call sequence `["FACTS", "COMPACT"]`), `test_claude_json.py::test_missing_tool_use_is_schema_error`,
  `::test_max_tokens_truncation_is_truncated_kind`.

### 8. Can the same stage/content/version call Claude twice unnecessarily? — **NO**

- `backend/app/analysis/impact_graph/router.py:163-171` — `call()` computes the fingerprint and
  consults `_cache_get` **before** any dispatch; a hit returns the stored result with
  `stage_cache_hits += 1`, a `call_skipped … reason=stage_cache_hit` log line, and zero provider
  traffic.
- `router.py:156` — the `cache_seed` parameter lets a caller pin the key to a stable semantic key
  (node id + candidates + facts) instead of raw prompt bytes, so a volatile prompt annotation cannot
  force a spurious re-call for the same underlying question.
- Durability across attempts: the cache is a DB table (`LLMStageCache`) with a 3-day TTL
  (`router.py:56`), so a retry, the hourly sweep, or a post-deploy re-queue replays for free.
- Article-level dedup on top: `backend/app/pipeline.py:133-151` `_v3_cache_key`.
- Tests: `test_provider_cache_isolation.py::test_duplicate_claude_call_served_from_cache` (asserts
  `client.calls == 1` for two identical `call()`s), `test_stage_cache.py` (whole file).

### 9. Can the entire sector-definition corpus be sent unnecessarily? — **YES (known, ruled, deferred)**

This is the single non-clean answer, and it is a token-cost item, not a safety item.

- `backend/app/analysis/impact_graph/prompts.py:699-706` `static_prefix()` unconditionally
  concatenates the full `SECTOR_DEFINITIONS` corpus (`backend/app/analysis/schemas.py:67-90`, ~17
  entries, ~300–350 tokens) onto `SYSTEM_PROMPT` for **every** stage — all ten call sites in
  `engine.py` (597, 611, 1056, 1243, 1305, 1398, 1509, 1630, 1805, 1915). At least `extract_facts`
  and `verify_edges` plausibly do not need it.
- Ruled and deferred in Task 5 with full rationale:
  `docs/superpowers/reports/2026-08-14-token-efficiency-audit.md` §14 ("PARTIAL — FUTURE
  optimization noted, not fixed"). Two reasons: (a) any change to what rides `static_prefix` is a
  prompt-shape change requiring an `IMPACT_PROMPT_VERSION` bump and a clean offline-benchmark re-run
  — the exact class of change that previously cost 35–79% company recall
  (project memory: bundling regression); (b) it is a pure size optimization, not a caching-correctness
  fix, since each stage's prefix is already byte-identical per stage.
- Bounded, not unbounded: the per-article `ArticleBudget` token ceilings still cap total spend
  (`backend/app/analysis/impact_graph/budget.py:49-63`).
- Carried to Remaining Risks (R4).

### 10. Can rejected candidates trigger further paid calls? — **NO**

- `backend/app/analysis/impact_graph/engine.py:73` — `_GraphState.rejected_tickers` accumulates every
  verifier rejection (written at `engine.py:745`, `:959`, `:1074`, `:1539`).
- Every candidate-pool builder filters it before proposing again: `engine.py:461-464`
  (`_map_companies_for_node`), `:847` (ripple frontier), `:1450` and `:1475` (narrow path). There is
  no retry loop that clears the set, so a rejected ticker cannot re-enter any LLM stage in the run.
- Verified in `docs/superpowers/reports/2026-08-14-token-efficiency-audit.md` §F.

### 11. Can budget exhaustion mark a candidate verified? — **NO**

- `backend/app/analysis/impact_graph/engine.py:1596-1616` (narrow) and `:1711-1721` (broad): on
  `budget.exceeded` the verification calls are **skipped**, `router.quality = "budget_exhausted"` is
  set, and every collected company keeps `verified = False` (set explicitly at `engine.py:1599-1600`
  *before* the budget check, so the skip path cannot forget).
- Fail-closed enforcement at the gate:
  `backend/app/analysis/impact_graph/publication_gate.py:456-470` `_check_verified` checks
  `verification_available` **first and unconditionally**, before `independently_verified` is read —
  "a True `independently_verified` flag is not a verdict, it is an upstream default." A
  budget-exhausted candidate therefore reaches `REJECT_VALIDATOR_UNAVAILABLE`, never
  `DISPLAY_ELIGIBLE`.
- Tests: `backend/tests/test_v4_invariants.py:439-470`
  `test_inv005_unavailable_validator_fails_closed`, parametrized over `verified in [False, True]`,
  runs a `quality="budget_exhausted"` result through the real persistence path and asserts
  `gate_state == "REJECT_VALIDATOR_UNAVAILABLE"` / `display_tier == "excluded"` for **both**;
  plus `backend/tests/test_budget_fail_closed.py::test_exceeded_budget_flags_without_verifying`.

### 12. Can fallback bypass existing V4 publication gates? — **NO**

- The gate has **no provider branch at all**: `grep -n "provider" backend/app/analysis/impact_graph/publication_gate.py`
  returns zero matches. Fallback output walks the identical 13-gate `GATE_SEQUENCE`
  (`publication_gate.py:473-487`) as Claude output — the gate cannot distinguish them, so it cannot
  be softened for them.
- Fallback is additionally *penalised*: `publication_gate.py:527-543` `_primary_authorized` returns
  False when `quality == "fallback"` unless `ctx.fallback_primary_allowed`, whose default is
  `settings.impact_allow_fallback_primary = false` (`publication_gate.py:219-222`,
  `backend/app/config.py:319-320`). `quality == "degraded"` is unconditionally barred from primary
  (`publication_gate.py:540-541`).
- `publication_gate.py:447-453` `_check_quality_valid` rejects any unrecognized or `"failed"`
  quality outright with `REJECT_VALIDATOR_UNAVAILABLE`.
- No change was made to `publication_gate.py` on this branch (`git diff 93c5ca16..HEAD --stat` does
  not list it).

### 13. Can provider identity be lost between StageRouter and persistence? — **NO**

Three hops, each pinned by a test:

1. Router → `backend/app/analysis/impact_graph/router.py:92,118` set `provider`/`quality`;
   `backend/tests/test_provider_traceability.py::test_router_exposes_claude_identity`.
2. Router → engine result: `::test_engine_stamps_router_identity_onto_result` asserts
   `result.analysis_provider == "claude"` / `analysis_quality == "authoritative"`.
3. Result → Alert row: `backend/app/models.py:342-343` (`Alert.analysis_provider`,
   `Alert.analysis_quality`), written via `backend/app/pipeline.py:883`;
   `::test_provider_survives_to_alert_columns` asserts both columns end up `"claude"` /
   `"authoritative"` through the real `process_new_articles` path.
4. Plus the audit trail: `backend/app/pipeline.py:803-829` `_analysis_model_for_provider` now maps
   `"claude" → settings.claude_model` (`pipeline.py:824-825` — this was a real gap found in Task 6
   review, where `CompanyDecisionRecord.model` persisted the literal string `"claude"`).
   `::test_analysis_model_for_provider_maps_claude` and
   `::test_provider_model_survives_to_decision_record` (asserts `decision.model == settings.claude_model`
   and `!= "claude"`).

### 14. Can an old analysis cache bypass the current provider/version policy? — **NO**

Both cache layers are version-keyed, and a stale row is an automatic miss rather than a
special-cased branch:

- Stage cache: `backend/app/analysis/impact_graph/router.py:272-278` hashes provider, model,
  `IMPACT_PROMPT_VERSION`, `IMPACT_SCHEMA_VERSION`, `KNOWLEDGE_REGISTRY_VERSION`, the
  `impact_engine_v4_strict` flag, gate `POLICY_VERSION`, and the full/compact variant. Plus a 3-day
  TTL enforced on read (`router.py:289-295`).
- Article result cache: `backend/app/pipeline.py:133-151` `_v3_cache_key` =
  `v3:{POLICY_VERSION}:{IMPACT_PROMPT_VERSION}:{IMPACT_SCHEMA_VERSION}:{KNOWLEDGE_REGISTRY_VERSION}:{strict_flag}:{content_hash}`
  — a row under the old two-part `v3:<hash>` scheme simply never matches.
- Tests: `test_fallback_quality.py::test_v3_result_cache_invalidates_on_policy_bump`,
  `::test_v3_result_cache_expires_after_ttl`,
  `::test_fingerprint_includes_policy_version_and_strict_flag`,
  `test_provider_cache_isolation.py::test_gemini_era_cache_row_never_matches_claude_fingerprint`.

### 15. Can live mode become enabled by this migration? — **NO**

- `git diff 93c5ca16..HEAD | grep -n "ANALYSIS_PAUSED\|analysis_paused\|scheduler"` returns **no
  matches** — the branch touches neither the setting nor the scheduler.
- `git diff --stat 93c5ca16..HEAD` does not list `backend/app/scheduler.py` at all. The two
  enforcement points (`backend/app/scheduler.py:103` and `:186`, both `if settings.analysis_paused:`)
  are byte-identical to `master`.
- `backend/app/config.py:121` `analysis_paused` is unchanged by this branch.
- No new scheduler job, cron entry, or auto-start path was added anywhere on the branch (the full
  file list is 18 files: 5 app files, 11 test files, 1 benchmark CLI, 1 doc).

### 16. Does the default router select Claude? — **YES**

- `backend/app/config.py:36` — `llm_provider_mode` defaults to `"claude"`; anything else makes
  `StageRouter.__init__` raise before it can serve (`router.py:79-82`).
- `backend/app/analysis/impact_graph/router.py:87-92` — with a Claude key present the router is
  `provider="claude"`, `quality="authoritative"` (`:118`), and `call()` dispatches on
  `self._primary == "claude"` (`router.py:177`).
- `backend/app/pipeline.py:1635-1653` — every article gets this router; there is no per-article
  provider branch left.
- Tests: `test_provider_policy.py::test_default_router_selects_claude`,
  `test_fallback_quality.py::test_pipeline_router_is_claude_for_every_article`,
  `::test_claude_router_starts_authoritative`.

### 17. Are all tests offline/mocked? — **YES**, with one scoped caveat

- Structural guard, not convention: `backend/tests/conftest.py` autouse fixture
  `_no_real_anthropic_client` monkeypatches `anthropic.Anthropic` to a function that raises
  `AssertionError` for the entire session. Proven in both directions by
  `backend/tests/test_no_real_anthropic_guard.py::test_injected_fake_client_is_unaffected_by_the_guard`
  and `::test_missing_fake_client_fails_closed_instead_of_reaching_the_network`.
- Key guard: `conftest.py` autouse `_fake_claude_key` forces
  `settings.claude_api_key = "test-claude-key-not-real"` on **every** test, so a developer's real
  `CLAUDE_API_KEY`/`ANTHROPIC_API_KEY` in the shell can never be picked up by a test run.
- Lazy construction means the guard covers the whole surface:
  `backend/app/analysis/impact_graph/claude_json.py:59-70` — `__init__` only stores the key; the real
  SDK client is built inside `_sdk()`, on the first `generate()`, only when no fake `client=` was
  injected.
- Tripwire greps re-run for this audit: no test opens a socket toward Anthropic; the one
  `api.anthropic.com` literal (`tests/test_claude_json.py:55`) constructs an in-memory
  `httpx.Request`/`Response` to synthesize an `APIStatusError` fixture and is never sent.
- **Caveat (parked, in Remaining Risks R6):** `backend/app/analysis/claude_client.py:8` imports
  `from anthropic import Anthropic`, so `AnthropicAdapter.__init__`
  (`backend/app/analysis/claude_client.py:515`) resolves `Anthropic` through the module-local name
  and the conftest guard cannot intercept it. That adapter belongs to the legacy translation /
  relevance chain, which is explicitly **out of migration scope**, and no test in the repo constructs
  it for real (the one test that touches it bypasses `__init__` via `__new__`). The guard's "zero
  real calls" claim is therefore exact for the impact-graph surface and by-inspection for that
  legacy adapter.

### 18. Are API keys absent from logs? — **YES**

- `backend/app/analysis/impact_graph/claude_json.py:96-115` — every exception branch re-raises with
  `type(exc).__name__` or a status code, never the exception's own string and never the key. The
  explicit comment at `:108` reads "Never let the key reach a log line via an exception string."
- The adapter never logs the key: `grep -n "api_key" backend/app/analysis/impact_graph/*.py` shows
  the key only at `claude_json.py:59-60` (stored) and `:66` (passed to the SDK constructor) — no
  logger call receives it.
- Telemetry lines log provider/model/tier/tokens only —
  `backend/app/analysis/usage_log.py:89-100`.
- The key is never part of a URL for this provider (contrast the disabled
  `gemini_json.py:88`, which puts the key in a query string — another reason it stays disabled).
- Test: `backend/tests/test_claude_json.py::test_api_key_never_in_error_message`.

### 19. Is provider/model/quality persisted? — **YES**

- Alert level: `backend/app/models.py:342-343` — `analysis_provider`, `analysis_quality` columns,
  written at `backend/app/pipeline.py:883` / `:957` / `:984`.
- Per-call level: `backend/app/models.py:1121+` `LLMCallUsage` — provider, model, tier, tokens,
  cost, stage, cache_hit, per row. `backend/app/analysis/impact_graph/claude_json.py:119-130` builds
  the row, overrides `usage.provider = "claude"` (`:125`), and prices it via `_estimate_cost`
  (`:126-129`).
- Decision-record level: `CompanyDecisionRecord.provider` / `.model`, with the model resolved by
  `backend/app/pipeline.py:803-829` `_analysis_model_for_provider`
  (`"claude" → settings.claude_model`, `pipeline.py:824-825`).
- Tests: the four in `backend/tests/test_provider_traceability.py`, plus
  `test_claude_json.py::test_success_records_claude_usage`.
- Naming caveat carried to Remaining Risks (R5): `usage_log.usage_from_anthropic`
  (`backend/app/analysis/usage_log.py:147`) defaults `provider="anthropic"`; the impact-graph adapter
  overrides it to `"claude"`, but the legacy `claude_client.py` chains keep writing `"anthropic"`.

### 20. Is the implementation token-efficient by design? — **YES** (A–J and §13 satisfied; §14 PARTIAL)

Full evidence in `docs/superpowers/reports/2026-08-14-token-efficiency-audit.md`; re-checked at
`85bbe03d`:

- **A** minimal sufficient context — only `initial_shocks`/`narrow_graph` get the full event record
  (`engine.py:114-125`); every other stage uses `_compact_suffix` (`engine.py:128-139`). Only
  `extract_facts` sees the raw article (`engine.py:1303-1308`).
- **B** no deterministic rediscovery — ticker resolution, dedup, ranking are pure Python/DB
  (`companies/candidates.py`, `publication_gate.py:333-339`, `:565-611`).
- **C** static prefix / compact dynamic — `prompts.static_prefix()` is byte-identical per stage
  (`prompts.py:699-706`) and rides the system block under a `cache_control: ephemeral` marker
  (`claude_json.py:87-88`) so Anthropic's prompt cache can serve it.
- **D/E** immutable-result caching + duplicate-call prevention — Q3/Q8 above.
- **F** no rerun after deterministic rejection — Q10.
- **G** no prose before validated data — gate + `AlertCompany` persistence precede `refine_alert`
  (`pipeline.py:889-996` then `:1000-1016`).
- **H/I/J** no separate LLM for section titles, price-move explanation, or counterfactual — the
  counterfactual is a field on the `verify_companies` schema itself
  (`prompts.py:527-532`, `schemas.py:431-439`).
- **§13** stage budgets — `budget.py:17-95`, hard `exceeded` at 100% and `expansion_exhausted` soft
  stop at 75% reserving budget for verification.
- **§14** PARTIAL — the sector corpus (Q9 / R4).
- Structural additions from this branch: forced tool use removes retry-on-unparseable-prose entirely
  (`claude_json.py:90-94`), and the ladder is at most 2 Claude calls per stage
  (`router.py:401-430`).

---

## Part 2 — §25 Required Final Report

### 1. Gemini locations disabled/commented out

| Location | Action |
|---|---|
| `backend/app/analysis/impact_graph/gemini_json.py:1-5` | Module marked **DISABLED**; kept as an isolated, unimported adapter (commit `7dbafebb`). |
| `backend/app/analysis/impact_graph/router.py` | All Gemini imports, the `protected=`/`gemini_api_key=` constructor kwargs, and the entire paid-Gemini ladder (plain-retry rung, cheaper-model rung, spend-cap breaker) removed. `router.py:34` documents the rule. |
| `backend/app/pipeline.py:1635-1653` | `_build_v3_router` no longer reads `settings.gemini_paid_api_key` / `gemini_api_key`, and no longer calls `grant_paid_analysis` for provider selection. |
| `backend/benchmark_impact_graph.py:62-79` | Default `run_v3` path hard-pinned to Claude: raises without a Claude key, passes `groq_client=None`. Gemini survives only behind the explicit `--old` flag (`:118-124`, `:168`). |
| `backend/tests/test_fallback_quality.py` | Gemini-ladder rung tests deleted (not ported) — those rungs no longer exist; replaced by `test_provider_policy.py`. |

`settings.gemini_*` fields remain in `config.py` because the legacy `claude_client.py` chains and the
`--old` benchmark still reference them; nothing on the analysis path reads them.

### 2. Claude adapter files

- `backend/app/analysis/impact_graph/claude_json.py` (new, 175 lines, commit `f4abd399`) —
  `ClaudeJSONClient` + `ClaudeJSONError`. Forced tool use (`emit` tool, `input_schema` = the stage's
  V4 schema, `tool_choice` pinned, parallel tool use disabled), `cache_control: ephemeral` on the
  static prefix, lazy SDK construction, six-way error taxonomy
  (`auth` / `rate_limit` / `transport` / `schema` / `truncated` / `refusal`), usage + budget
  recording, no thinking/temperature/top_p sent.
- `backend/app/analysis/usage_log.py:144-153` `usage_from_anthropic` (pre-existing) is reused for
  token accounting.

### 3. StageRouter changes

`backend/app/analysis/impact_graph/router.py` (commit `7dbafebb`, fixed in `72e45773`):

- Constructor signature `(*, claude_api_key, groq_client=None, article_id=None, budget=None,
  session=None, claude_client=None)` — `protected`/`gemini_api_key` gone (`:73-75`).
- Fail-closed on `llm_provider_mode != "claude"` before anything else (`:79-82`).
- Fail-closed on no key + no explicit fallback (`:100-104`).
- `self._primary` (immutable dispatch target) split from `self.provider` (mutable honesty field)
  (`:105-113`) — the `72e45773` fix; the fingerprint keys on `_primary` so a mid-run fallback cannot
  turn every later stage into a guaranteed cache miss.
- Ladder: Claude full → (schema/truncated only) Claude compact → explicit-opt-in Groq → else
  `StageRouterError` (`:389-459`).
- Run-scoped auth circuit breaker `claude_auth_failed` (`:136`, `:382-387`, `:396-399`).
- Stage-typed model selection `_model_for` (`:348-360`) with override map.
- Provider component added to the cache fingerprint (`:273`) and to `_fingerprint_model` (`:333-340`).

### 4. Provider configuration

`backend/app/config.py` (commit `94a73b30`):

| Setting | Env var | Default |
|---|---|---|
| `claude_api_key` (`:17-19`) | `CLAUDE_API_KEY` → falls back to `ANTHROPIC_API_KEY` | `""` |
| `llm_provider_mode` (`:36`) | `LLM_PROVIDER_MODE` | `"claude"` |
| `llm_fallback_allowed` (`:39`) | `LLM_FALLBACK_ALLOWED` | `false` |
| `claude_timeout` (`:29`) | `CLAUDE_TIMEOUT` | `180` s |
| `claude_max_retries` (`:31`) | `CLAUDE_MAX_RETRIES` | `2` (SDK-level) |
| `claude_retry_backoff` (`:33`) | `CLAUDE_RETRY_BACKOFF` | `2` s (router compact rung) |

### 5. Model configuration

| Setting | Env var | Default | Used for |
|---|---|---|---|
| `claude_model` (`config.py:23`) | `CLAUDE_MODEL` | `claude-opus-5` | every reasoning stage |
| `claude_fact_model` (`:24`) | `CLAUDE_FACT_MODEL` | `claude-haiku-4-5` | `extract_facts` |
| `claude_summary_model` (`:25`) | `CLAUDE_SUMMARY_MODEL` | `claude-haiku-4-5` | `reader_summary` |
| `claude_max_output_tokens` (`:28`) | `CLAUDE_MAX_OUTPUT_TOKENS` | `16000` (floor) | `claude_json.py:81` takes `max(stage request, floor)` |
| `claude_stage_model_overrides` (`:40-51`) | `CLAUDE_STAGE_MODEL_OVERRIDES` | `""` | `stage=model,stage=model` map, wins over all three |

Pricing seeded at `config.py:441-442`: `claude-opus-5` $5/$25 per Mtok (`cache_read` 0.5),
`claude-haiku-4-5` $1/$5 (`cache_read` 0.1); overridable via `CLAUDE_PRICING_JSON`
(`config.py:450-455`). Stage routing lives in `router.py:348-360`
(`FACT_STAGES`/`SUMMARY_STAGES` at `:58-59`).

### 6. Cache changes

- Provider + model added to the stage-cache fingerprint (`router.py:272-278`) — the structural
  Gemini/Claude isolation, with no migration or purge needed.
- Fingerprint keys on `_primary`, not the mutable `provider` (`router.py:333-340`) — fix `72e45773`.
- Cache-put guard remains absolute (`router.py:194-199`): `authoritative` **and** `full` variant only.
- Envelope shape `{"__cache_envelope": 1, "quality", "result"}` preserved (`router.py:318`), with
  quality re-applied on read (`:303-305`).
- 3-day TTL + opportunistic sweep unchanged (`router.py:56`, `:289-295`, `:325-327`).
- Anthropic prompt-cache breakpoint added on the static system prefix
  (`claude_json.py:87-88`) — provider-side, distinct from the DB stage cache.

### 7. Retry changes

Three bounded layers, no loops:

1. **SDK** — transient only (429/5xx/connect, honors `Retry-After`), `max_retries=2`
   (`claude_json.py:65-69`, `config.py:31`).
2. **Router** — exactly one compact-context correction rung, only for `schema`/`truncated`, only
   when a `compact_suffix` exists, after a `claude_retry_backoff` sleep (`router.py:417-430`).
   Transport/rate-limit/auth get zero router retries.
3. **Breaker** — `auth` is terminal for the whole run (`router.py:382-387`, `:396-399`).

Removed: the pre-migration plain-retry rung and cheaper-model rung.

### 8. Concurrency changes

**None — deliberately.** No concurrency primitive exists anywhere in the analysis path:
`grep -rn "ThreadPool\|asyncio\|concurrent.futures\|threading" backend/app/analysis/impact_graph/`
and the same grep over `backend/app/pipeline.py` / `backend/app/scheduler.py` both return zero
matches. Stages run sequentially within an article, articles run sequentially within a run
(spec §12's bounded-concurrency requirement is satisfied by there being no concurrency to bound).
This branch introduced none.

### 9. Token-efficiency changes

- **Structural (this branch):** forced tool use eliminates prose parsing and the whole
  retry-on-unparseable class (`claude_json.py:90-94`); the ladder is at most 2 Claude calls per stage
  (down from the old 3-rung Gemini ladder + plain retry); the `cache_control` breakpoint on the
  static prefix enables provider-side prompt caching (`claude_json.py:87-88`); the `max_tokens` floor
  (`claude_json.py:81`) prevents a truncation-then-retry cycle; cheap models for
  `extract_facts`/`reader_summary` (`router.py:356-359`).
- **Audited, already satisfied, unchanged:** A–J and §13 — see Q20 and
  `docs/superpowers/reports/2026-08-14-token-efficiency-audit.md`.
- **Deferred:** §14 sector-corpus trimming (Q9 / R4). No prompt text was changed anywhere on this
  branch, so `IMPACT_PROMPT_VERSION` was **not** bumped (`prompts.py:16`, still `"kg-6"`).

### 10. Telemetry

- Per-call `LLMCallUsage` rows with `provider="claude"` (`claude_json.py:125`), model, stage,
  tier, thinking level, latency, input/output/cache-read/cache-write tokens, estimated cost,
  success, `returned_count`, and the `_CONTEXT_KEYS` set — `parent_node`, `mechanism_id`,
  `candidate_count`, `prompt_version`, `schema_version`, `retries`, `fallback`
  (`claude_json.py:33-36`, `:119-130`).
- Failures are recorded too, not silently dropped (`claude_json.py:158-164` `_record_failure`).
- Cache hits recorded as zero-cost events so per-article accounting can prove no double-billing
  (`router.py:212-228`, `provider="cache"`, `cache_hit=True`).
- Ladder position rides every row: `retries=0` on the full rung, `retries=1` on the compact rung
  (`router.py:376`).
- `context_compacted` exposed on the router (`router.py:130`, set at `:379`).
- Groq fallback has no `context` extension point in its own client, so the router emits a summary
  line instead: `router.py:453-456` (`call_summary … provider=groq fallback=True`) plus a loud
  `WARNING`.
- Structured log line for every call at `usage_log.py:89-100`; DB persistence gated on
  `settings.llm_usage_db_logging`.

### 11. Tests added

| File | Tests | Commit |
|---|---|---|
| `backend/tests/test_claude_provider_config.py` | 5 — defaults, `CLAUDE_API_KEY` precedence over `ANTHROPIC_API_KEY`, override-map parsing, pricing seeded | `94a73b30` |
| `backend/tests/test_claude_json.py` | 11 — success path, usage recording, each error-kind mapping, key-never-in-message, max-tokens floor, budget recording | `f4abd399` |
| `backend/tests/test_provider_policy.py` | 14 — default selects Claude, fail-closed at construction, fail-closed on failure, explicit fallback marks fallback, one compact retry, no transport retry, auth breaker, Gemini not importable, wrong-mode fail-closed, fingerprint provider/model, mid-run-fallback traces (2), breaker+fallback | `7dbafebb`, `72e45773` |
| `backend/tests/test_provider_cache_isolation.py` | 4 — Gemini-era row never matches, duplicate call served from cache, malformed never cached, compact never cached | `da089d90` |
| `backend/tests/test_budget_fail_closed.py` | 1 — exceeded budget flags without verifying | `60aece51` |
| `backend/tests/test_provider_traceability.py` | 4 — router identity, engine stamping, Alert columns, decision-record model | `2a2f10f7` |
| `backend/tests/test_no_real_anthropic_guard.py` | 2 — guard does not fire on injected fakes; guard fires on a missing fake | `85bbe03d` |
| `backend/tests/conftest.py` | 2 autouse fixtures — `_fake_claude_key`, `_no_real_anthropic_client` | `7dbafebb`, `85bbe03d` |
| `backend/tests/test_fallback_quality.py`, `test_impact_graph.py`, `test_stage_cache.py` | rewritten for the Claude ladder; Gemini-rung tests deleted | `7dbafebb` |

**41 new tests**, all mocked at the client or router boundary.

### 12. Test results

Re-run by this audit at `85bbe03d` (Windows venv, from `backend/`):

```
cd backend && .venv/Scripts/python.exe -m pytest -q
→ 2101 passed, 2 skipped, 7 warnings in 102.97s
```

```
cd backend && .venv/Scripts/python.exe -m pytest \
    tests/test_provider_policy.py tests/test_provider_cache_isolation.py \
    tests/test_provider_traceability.py tests/test_no_real_anthropic_guard.py \
    tests/test_claude_json.py tests/test_claude_provider_config.py \
    tests/test_budget_fail_closed.py tests/test_fallback_quality.py \
    tests/test_stage_cache.py -q
→ 62 passed in 3.77s
```

Baseline on `master` was 2099 passed / 2 skipped; the +2 are the network-guard tests from `85bbe03d`.
Zero regressions across the whole suite from the router signature change.

Offline suite (run in Task 7 at this same HEAD, not re-run here):
`.venv/Scripts/python.exe tools/run_offline_suite.py` → **6/6 steps PASS**; `tools/offline_benchmark.py`
metrics **all 1.0** (company_precision 43/43, company_recall 33/33, false_positive_rate 0/59,
primary_feed_precision 33/33, fundamental_direction_accuracy 33/33, mixed 5/5, mechanism 6/6,
causal_distance 36/36, materiality 9/9, section 26/26, abstention_precision 3/3, entity 23/23,
evidence 30/30, rejection_recall 19/19, explanation_faithfulness 86/86;
`market_measurement_accuracy` N/A 0/0, expected).

### 13. Exact default provider/model path

```
scheduler (gated by ANALYSIS_PAUSED)          app/scheduler.py:103,186
  → pipeline.process_new_articles             app/pipeline.py
    → _build_v3_router(session, article, groq_client)   app/pipeline.py:1635-1653
        claude_api_key = settings.claude_api_key        app/config.py:17-19
        groq_client    = None  (unless LLM_FALLBACK_ALLOWED)
      → StageRouter.__init__                  app/analysis/impact_graph/router.py:73-136
          assert settings.llm_provider_mode == "claude"     (:79-82, else StageRouterError)
          self._claude  = ClaudeJSONClient(key)             (:87-88)
          self.provider = "claude"; self._primary = "claude"(:92, :113)
          self.quality  = "authoritative"                   (:118)
    → analyze_article_v3(router, ...)         app/analysis/impact_graph/engine.py
      → router.call(stage=...)                router.py:140-200
          fingerprint → LLMStageCache lookup  (:163-171)  [hit ⇒ 0 provider calls]
          dispatch on self._primary == "claude"           (:177)
          model = _model_for(stage)                       (:348-360)
              extract_facts   → settings.claude_fact_model    = claude-haiku-4-5
              reader_summary  → settings.claude_summary_model = claude-haiku-4-5
              everything else → settings.claude_model         = claude-opus-5
              (CLAUDE_STAGE_MODEL_OVERRIDES wins over all three)
        → ClaudeJSONClient.generate           claude_json.py:72-139
            anthropic.Anthropic(timeout=180, max_retries=2)  (:65-69)
            messages.create(
              system=[{text: static_prefix, cache_control: ephemeral}],   (:87-88)
              messages=[{role: user, content: dynamic_suffix}],           (:89)
              tools=[{name: "emit", input_schema: <stage V4 schema>}],    (:90-92)
              tool_choice={type: tool, name: emit,
                           disable_parallel_tool_use: true})              (:93-94)
            → parse tool_use.input            (:141-156)
            → record LLMCallUsage(provider="claude") + ArticleBudget      (:119-136)
          cache-put iff quality=="authoritative" and variant=="full"      router.py:194-199
    → publication gate (13 gates)             publication_gate.py:473-487
    → Alert.analysis_provider="claude" / analysis_quality="authoritative" pipeline.py:883
```

### 14. Fallback behavior

- **Default: disabled.** `settings.llm_fallback_allowed = false` (`config.py:39`). A Claude stage
  failure raises `StageRouterError` (`router.py:458-459`) and the article's analysis fails rather
  than being served by a weaker model. No Groq client is even handed to the router
  (`pipeline.py:1647-1650`).
- **When explicitly enabled** (`LLM_FALLBACK_ALLOWED=true`): the ladder's last rung calls Groq
  `settings.groq_aux_model` (`llama-3.3-70b-versatile`) via forced tool use (`router.py:463-486`).
  The result sets `self.provider = "groq"`, `self.quality = "fallback"` (`:444-445`), emits a
  `call_summary … fallback=True` line and a `WARNING` (`:453-456`), is **never** written to the stage
  cache (the absolute guard at `:194`) — and the taint is run-scoped, so no later Claude-served stage
  in that run is cached either. Dispatch keeps going to Claude (`_primary` unchanged) so one
  transient failure does not demote the rest of the run.
- Fallback output still walks all 13 publication gates (`publication_gate.py:473-487`), and is barred
  from the primary tier unless `IMPACT_ALLOW_FALLBACK_PRIMARY=true`
  (`publication_gate.py:542-543`, default false).
- A configuration-only Groq router (no Claude key + opt-in on) is `quality="fallback"` from its very
  first call, never "authoritative" (`router.py:118`).

### 15. Remaining risks

**R1 — The paid-grant daily article gate no longer bounds analysis spend (HIGH attention before live
mode).** Pre-migration, an article had to win `grant_paid_analysis` (`pipeline.py:1139-1159`: eligible
provider + `gemini_paid_daily_article_budget` per IST day) before it could use the expensive chain.
`_build_v3_router` no longer consults it (`pipeline.py:1635-1653`) — Claude serves **every** article.
The only remaining spend bounds are the per-article `ArticleBudget` and `ANALYSIS_PAUSED`. There is
now **no daily or run-level ceiling of any kind.** `grant_paid_analysis` still exists and still gates
the legacy `claude_client` cascade via `select_analysis_client` (`pipeline.py:1162-1183`) — that path
is unchanged, which can make it look like the gate is still protecting analysis. It is not.

**R2 — The per-article USD ceiling is disabled by default, and the token ceilings now cost ~2.2×
more.** `budget.py:49-59` `_over()` skips any ceiling that is falsy, and
`gemini_max_cost_per_article_usd` defaults to `"0"` (`config.py:355`) — so only the token ceilings
bind: 100 000 input / 24 000 output per article (`config.py:353-354`). Under Gemini pricing
($2/$12 per Mtok) that worst case was ≈$0.49/article; under `claude-opus-5` ($5/$25, `config.py:441`)
the identical ceiling is ≈$1.10/article. **Recommendation before any live run: set
`GEMINI_MAX_COST_PER_ARTICLE` to a real number** (the setting name is a legacy misnomer — it is
provider-agnostic and is what `_estimate_cost` bills Claude against). Also note the ceiling env vars
are still named `GEMINI_MAX_*`, which is a footgun for whoever configures this.

**R3 — Anthropic's prompt cache has a ~5-minute TTL.** The `cache_control: ephemeral` breakpoint on
the static prefix (`claude_json.py:87-88`) gives strong within-article reuse (all ~10 stages of one
article run back-to-back), but cross-article reuse of the same stage prefix only lands if the next
article of that stage arrives inside the TTL window. With sequential single-article processing and
`ANALYSIS_PAUSED` on, expect the cache to help within an article and mostly *not* across articles.
Cache writes also bill at 1.25× input, so a low-throughput run can be marginally *more* expensive
than no caching at all. Worth measuring `cache_read_tokens` vs `cache_write_tokens` on the first live
batch (both are already recorded — `usage_log.py:150-151`).

**R4 — §14 sector-corpus trimming is deferred (PARTIAL).** The full `SECTOR_DEFINITIONS` corpus rides
every stage's static prefix (`prompts.py:699-706`), including stages that plausibly do not need it
(`extract_facts`, `verify_edges`). ~300–350 tokens × every stage × every article. Not fixed because
it is a prompt-shape change requiring an `IMPACT_PROMPT_VERSION` bump and a clean offline-benchmark
re-run, and this codebase has a measured history of prompt/call-shape changes costing 35–79% company
recall. Full rationale: `docs/superpowers/reports/2026-08-14-token-efficiency-audit.md` §14.

**R5 — Provider naming is split across layers.** New impact-graph rows record `provider="claude"`
(`claude_json.py:125`); legacy `claude_client.py` chains record `provider="anthropic"`
(`usage_log.py:147`); the stage cache-hit rows record `provider="cache"` (`router.py:219`). Any
cross-table cost query must union `"claude"`, `"anthropic"`, and `"cache"` or it will silently
under-report. Cosmetic leftovers in the same family: `models.py:664`'s stale
`CompanyDecisionRecord.provider  # gemini | groq` comment, and ~12 test files with inert
`provider="gemini"` fixtures.

**R6 — `AnthropicAdapter` is outside the network guard (parked ruling, Task 7).**
`backend/app/analysis/claude_client.py:8` does `from anthropic import Anthropic`, so
`AnthropicAdapter.__init__` (`claude_client.py:515`) resolves the class through the module-local name
and the conftest `monkeypatch.setattr(anthropic, "Anthropic", …)` guard cannot intercept it. That
adapter serves the legacy translation/relevance chain, explicitly out of migration scope, and no
current test constructs it for real (the one test that touches it bypasses `__init__` via `__new__`).
**Cost if wrong:** a future test that constructs `AnthropicAdapter` for real could open a connection
to api.anthropic.com with a bogus key. Cheap future fix: change that line to `import anthropic` +
`anthropic.Anthropic(...)`, which brings it under the same guard.

**R7 — `claude_client.py`'s Groq chains are out of scope and unchanged.** Relevance scoring,
refinement, and translation still run on their existing Groq/Anthropic routing
(`app/analysis/claude_client.py`, `app/analysis/refinement.py`). This migration replaced the
*impact-graph analysis* provider only. Anyone reading "Newsflo now runs on Claude" should know those
three chains do not.

**R8 — Model IDs are unverified against the live API, by design.** `claude-opus-5` and
`claude-haiku-4-5` (`config.py:23-25`) are configuration strings; with zero real API calls made, no
test proves those IDs resolve at Anthropic. A wrong ID surfaces as a `transport`-kind
`ClaudeJSONError` on the first live call — which fails closed correctly, but would fail the whole
first batch. Worth a single manual smoke call (outside any automated run) before enabling live mode.

**R9 — Deferred cosmetic minors from the task ledger.** Blank-line style after
`claude_stage_model_override_map` (`config.py:50-52`); `thinking` default `"high"` vs the old Gemini
`"medium"` (contract-parity only — `claude_json.py` never sends a thinking block, `router.py:349-352`);
the `f"Record the {stage} result."` tool description reading oddly when `stage=None`
(`claude_json.py:91`); `budget.record`-on-parse-failure is behaviorally correct but untested;
`test_provider_cache_isolation.py:33` hardcodes the `gemini-3.1-pro-preview` literal (drift-tolerant,
docstring may stale). None affect correctness.

### 16. Confirmation that live mode remains OFF

Confirmed, three independent ways:

1. `git diff 93c5ca16..HEAD | grep -n "ANALYSIS_PAUSED\|analysis_paused\|scheduler"` → **no matches**.
2. `git diff --stat 93c5ca16..HEAD` lists 18 files; `backend/app/scheduler.py` is **not** among them.
   Both enforcement points (`scheduler.py:103`, `scheduler.py:186`) are byte-identical to `master`.
3. `backend/app/config.py:121` `analysis_paused` is untouched by this branch, as is every
   scheduler-interval setting. No new job, cron entry, or auto-start path was added anywhere.

No automated analysis was started at any point during this migration.

---

### DEFAULT PROVIDER

Claude

### DEFAULT MODEL

claude-opus-5 (reasoning stages); claude-haiku-4-5 (extract_facts, reader_summary)

### FALLBACK

Disabled by default (LLM_FALLBACK_ALLOWED=false → fail closed with StageRouterError).
When explicitly enabled: Groq llama-3.3-70b-versatile, marked quality="fallback",
never cached as authoritative, still subject to every V4 gate.

### LIVE MODE

OFF (ANALYSIS_PAUSED=true untouched; scheduler untouched)

### REAL API CALLS MADE DURING THIS TASK

ZERO

---

## Zero-real-calls evidence chain

1. **Structural guard.** `backend/tests/conftest.py` autouse `_no_real_anthropic_client` replaces
   `anthropic.Anthropic` with a raiser for the entire session; proven in both directions by
   `backend/tests/test_no_real_anthropic_guard.py`.
2. **No key in the test environment.** `conftest.py` autouse `_fake_claude_key` forces
   `settings.claude_api_key = "test-claude-key-not-real"` on every test, overriding whatever is in
   the developer's shell.
3. **Every LLM boundary is injected.** All 41 new tests pass a fake `claude_client=` / `client=` /
   monkeypatched `analyze_article_v3`.
4. **Tripwire greps** (Task 7, re-checked here): the only `api.anthropic.com` string in `tests/` is a
   literal argument to an in-memory `httpx.Request` used to synthesize an `APIStatusError` fixture
   (`tests/test_claude_json.py:55`); it never reaches a socket. All key literals in tests are
   synthetic (`ck-1`, `ak-1`, `ak-2`, `k`, `test-key`, `test-claude-key-not-real`).
5. **This task itself** made no code change and ran only `git`, `grep`, and `pytest` — all offline.
   The only network-capable component (the Anthropic SDK) was never invoked outside the guard.
6. **Scoped exception, disclosed:** R6 above — `AnthropicAdapter` (`claude_client.py:515`) is not
   covered by the guard's interception. It was not constructed during this task and no test
   constructs it for real, but the "structural zero-calls" claim is scoped to the impact-graph
   surface, not to that legacy adapter.
