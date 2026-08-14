"""Stage router -- Claude-first, fail-closed (provider-migration spec
2026-08-14 §5, §9, §19, §20; supersedes the old paid-Gemini ladder).

Claude owns EVERY stage of EVERY article. There is no protected/
non-protected split any more: the per-article ArticleBudget is the cost
bound, not a paid-grant gate.

    facts            -> settings.claude_fact_model    (low thinking)
    reader summary   -> settings.claude_summary_model (low thinking)
    everything else  -> settings.claude_model         (high thinking)
    (settings.claude_stage_model_override_map wins over all three)

Provider ladder (never silent, never longer than it has to be):
    1. Claude, full dynamic_suffix           -> variant "full".
       The SDK already retried transient failures (429/5xx/connection),
       so the router does NOT add a plain retry rung.
    2. Claude, compact context -- ONLY when rung 1 raised a
       ClaudeJSONError whose .retryable_with_compact is True (schema /
       truncated: the model produced a wrong-shaped or overlong answer, a
       smaller prompt can plausibly fix it) AND the stage supplied a
       compact_suffix. Sleeps settings.claude_retry_backoff first.
       Variant "compact" -- never cache-eligible.
    3. Ladder end: Groq ONLY under the explicit LLM_FALLBACK_ALLOWED
       opt-in (provider="groq", quality="fallback", logged loudly).
       Otherwise the stage FAILS CLOSED with StageRouterError -- a
       missing/broken Claude key never silently downgrades financial
       output to a weaker model.

Auth circuit breaker: a `kind == "auth"` failure is terminal for the
WHOLE run, not one stage -- once seen, every remaining call skips the
Claude rungs entirely instead of burning calls on a dead key (mirrors the
old spend-cap breaker, which measured minutes of pointless retries).

Gemini is NOT importable here (spec §16): gemini_json.py is a disabled,
isolated adapter. The provider component in the cache fingerprint makes
pre-migration Gemini rows unmatchable by a Claude run.

The router carries the worst quality seen across a run; the engine stamps
it onto the Alert (analysis_provider / analysis_quality columns).
"""
import hashlib
import json
import logging
import time
from datetime import timedelta

from app.analysis.impact_graph.claude_json import ClaudeJSONClient, ClaudeJSONError
from app.analysis.impact_graph.publication_gate import POLICY_VERSION
from app.config import settings

logger = logging.getLogger(__name__)

# Durable stage-result cache TTL. Retries span minutes-to-hours (second
# attempt, hourly sweep, post-deploy re-queue); 3 days covers every retry
# path with margin while keeping the table small.
STAGE_CACHE_TTL_DAYS = 3

FACT_STAGES = {"extract_facts"}
SUMMARY_STAGES = {"reader_summary"}

# "degraded" is unreachable through the Claude ladder (there is no
# cheaper-model rung any more), but it stays in the order: cache envelopes
# and Alert rows written before the migration carry it, and _cache_get
# still has to rank it against the others.
_QUALITY_ORDER = {"authoritative": 0, "degraded": 1, "fallback": 2, "budget_exhausted": 3}


class StageRouterError(Exception):
    """Every rung of the ladder failed for a stage."""


class StageRouter:
    def __init__(self, *, claude_api_key: str | None, groq_client=None,
                 article_id: int | None = None, budget=None, session=None,
                 claude_client=None):
        # Fail closed BEFORE anything else: a deployment that points at a
        # provider this router no longer speaks must not quietly serve
        # whatever client happens to be lying around.
        if settings.llm_provider_mode != "claude":
            raise StageRouterError(
                f"llm_provider_mode={settings.llm_provider_mode}: no live provider "
                "configured -- refusing to run analysis")
        self.article_id = article_id
        self.budget = budget
        # `claude_client` is the injected adapter (tests always inject; no
        # test in this repo may ever reach the network).
        self._claude = claude_client if claude_client is not None else (
            ClaudeJSONClient(claude_api_key) if claude_api_key else None)
        self._groq = groq_client
        self._session = session  # durable stage cache; None (tests) = no caching
        if self._claude is not None:
            self.provider = "claude"
        elif settings.llm_fallback_allowed and self._groq is not None:
            # Explicit, opted-in, loudly-announced degradation -- the only
            # way a run can start on Groq at all.
            self.provider = "groq"
            logger.warning("impact-graph router constructed on GROQ FALLBACK "
                           "(no Claude key, LLM_FALLBACK_ALLOWED=true) -- output is "
                           "quality=fallback, not authoritative, article=%s", article_id)
        else:
            raise StageRouterError(
                "no CLAUDE_API_KEY configured and fallback is disabled -- refusing to "
                "run analysis (set CLAUDE_API_KEY, or opt into the weaker Groq path "
                "explicitly with LLM_FALLBACK_ALLOWED=true)")
        # The construction-time dispatch target, and the ONLY provider
        # identity the cache is keyed on (see _fingerprint). `self.provider`
        # is the HONESTY field -- a mid-run fallback rewrites it to "groq"
        # so the Alert is stamped truthfully -- but it must never rewrite
        # which provider the NEXT stage tries first (one transient Claude
        # failure may not silently demote the rest of the run) nor which
        # key that stage looks up (that turned every later stage into a
        # guaranteed cache miss).
        self._primary = self.provider
        # Provider-identity honesty (corrective-v4 Task 15, preserved):
        # quality is EARNED, never inherited. Only a Claude-served router
        # starts authoritative; a Groq-by-configuration router is
        # "fallback" from its very first call, not after something breaks.
        self.quality = "authoritative" if self.provider == "claude" else "fallback"
        self.stage_cache_hits = 0
        # Which prompt variant actually served the current call: "full" is
        # the caller's real dynamic_suffix, "compact" is the trimmed
        # rung-3 retry. Only a "full" + authoritative result is ever cache-
        # eligible (see call()/`_cache_put`) -- a compact-context answer is
        # a different, cheaper question and must never be replayed as if it
        # were the full-context one.
        self._served_variant = "full"
        # Telemetry mirror of the same fact (spec: "sets context_compacted
        # metric"), exposed on the instance for callers/tests that want it
        # without reaching into the private variant flag.
        self.context_compacted = False
        # Auth circuit breaker (provider-migration §20, replaces the old
        # gemini_capped spend-cap breaker): a dead/revoked key is terminal
        # for the WHOLE run, not one stage -- once seen, every remaining
        # call skips the Claude rungs entirely instead of burning a call
        # per stage on a key that cannot possibly answer.
        self.claude_auth_failed = False

    # -- public ----------------------------------------------------------

    def call(self, stage: str, *, schema: dict, static_prefix: str,
             dynamic_suffix: str, compact_suffix: str | None = None,
             thinking: str = "high", max_output_tokens: int = 8192,
             context: dict | None = None, cache_seed: str | None = None) -> dict:
        """Run one stage call through the routing/degradation policy.
        Returns the parsed dict; records the worst quality reached.

        Retry-burn fix: a byte-identical stage call that already succeeded
        (this attempt, a prior failed attempt, the hourly retry sweep, or a
        pre-deploy run) replays its stored result from llm_stage_cache with
        ZERO provider traffic. Failures are never cached, and any input
        drift is a plain miss that pays normally.

        `cache_seed` (cost-opt spec P12): the caller's STABLE semantic key
        for this call -- node id + candidates + facts -- used for the cache
        fingerprint INSTEAD of the raw prompt bytes, so volatile prompt
        annotations (e.g. relationship-cache "[KNOWN BASE EXPOSURE]" lines
        that appear after a verify pass) can no longer invalidate the cache
        for a semantically identical call. `context` rides every telemetry
        row (parent_node, mechanism_id, candidate_count)."""
        context = dict(context or {})
        context.setdefault("prompt_version", self._prompt_version())
        context.setdefault("schema_version", self._schema_version())
        fingerprint = self._fingerprint(stage, schema, static_prefix,
                                        cache_seed or dynamic_suffix)
        cached = self._cache_get(fingerprint)
        if cached is not None:
            self.stage_cache_hits += 1
            logger.info("impact-graph call_skipped stage=%s reason=stage_cache_hit article=%s",
                        stage, self.article_id)
            self._record_cache_hit(stage, context)
            return cached
        # Reset per-call; only a rung that actually serves this call may
        # set it back to "compact" (see _call_claude).
        self._served_variant = "full"
        # Dispatch on the CONSTRUCTION-time provider, not self.provider --
        # see `self._primary`.
        if self._primary == "claude":
            result = self._call_claude(
                stage, schema=schema, static_prefix=static_prefix,
                dynamic_suffix=dynamic_suffix, compact_suffix=compact_suffix,
                thinking=thinking, max_output_tokens=max_output_tokens,
                context=context,
            )
        else:
            result = self._call_groq(stage, schema=schema, static_prefix=static_prefix,
                                     dynamic_suffix=dynamic_suffix)
        # Cache-poisoning guard (corrective-v4 Task 15): an ABSOLUTE check,
        # not a before/after delta -- a delta comparison only caught a
        # DOWNGRADE that happened on THIS call, so a router that entered
        # this call already degraded/fallback (e.g. non-protected, or a
        # prior stage's budget_exhausted) could still cache a "no change"
        # result as if it were fine. Only "the served result is genuinely
        # authoritative, from the full context" may ever be written back.
        if self.quality == "authoritative" and self._served_variant == "full":
            self._cache_put(fingerprint, stage, result)
        else:
            logger.info("impact-graph cache_put skipped stage=%s reason=not_authoritative_full "
                        "quality=%s served_variant=%s article=%s",
                        stage, self.quality, self._served_variant, self.article_id)
        return result

    @staticmethod
    def _prompt_version() -> str:
        from app.analysis.impact_graph.prompts import IMPACT_PROMPT_VERSION
        return IMPACT_PROMPT_VERSION

    @staticmethod
    def _schema_version() -> str:
        from app.analysis.impact_graph.schemas import IMPACT_SCHEMA_VERSION
        return IMPACT_SCHEMA_VERSION

    def _record_cache_hit(self, stage: str, context: dict) -> None:
        """A stage-cache replay is a real analytical event with ZERO cost --
        recorded so per-article accounting can prove it did not double-bill
        (cost-opt spec P1)."""
        try:
            from app.analysis.usage_log import CallUsage, record_usage
            record_usage(CallUsage(
                provider="cache", call_name=stage, stage=stage,
                model=self._fingerprint_model(stage), article_id=self.article_id,
                input_tokens=0, output_tokens=0, thinking_tokens=0,
                estimated_cost_usd=0.0, success=True, cache_hit=True,
                **{k: v for k, v in context.items() if k in (
                    "parent_node", "mechanism_id", "candidate_count",
                    "prompt_version", "schema_version")},
            ))
        except Exception:  # noqa: BLE001 -- telemetry never breaks analysis
            logger.warning("cache-hit telemetry failed", exc_info=True)

    # -- durable stage cache ----------------------------------------------

    def _fingerprint(self, stage: str, schema: dict, static_prefix: str,
                     seed: str, variant: str = "full") -> str:
        """Semantic-cache key (cost-opt spec P12): stage + PROVIDER + model
        + prompt/schema/knowledge versions + static prefix + the caller's
        semantic seed (or raw suffix when no seed was supplied). Version
        components make every prompt/registry change an EXPLICIT
        invalidation.

        Provider-migration §8 ("old Gemini cache entries must be isolated
        from Claude") is enforced by construction here, not by a migration:
        the provider and the model are BOTH hashed, so every row written by
        the pre-migration Gemini router lives under a key no Claude run can
        ever produce. No Gemini answer can be replayed as a Claude one, and
        no cache purge is needed to guarantee it.

        The provider component is `self._primary` -- the provider this
        router will actually DISPATCH to -- not the mutable `self.provider`,
        which is the Alert-stamping honesty field and flips to "groq" for
        the rest of the run after a single mid-run fallback. Hashing the
        mutable field made every later stage (still served by Claude) look
        up a groq-keyed fingerprint: a guaranteed miss on every remaining
        stage, and no replay at all when the article was retried. Keying on
        the dispatch target keeps lookups stable for the whole run; the
        absolute cache-PUT guard in call() is what stops a fallback-tainted
        run from writing anything, and it is untouched by this.

        Corrective-v4 Task 15 adds three more explicit-invalidation
        components: the strict-mode flag (v4-strict and legacy runs must
        never share a cache entry -- their publication semantics differ),
        POLICY_VERSION (a gate policy bump must invalidate every cached
        stage result it could have judged differently), and `variant`
        ("full" | "compact") -- the caller always looks up "full" (the
        cache never stores a compact-context result under any key; see
        call()), but keeping the marker in the payload documents the
        contract in the hash itself rather than leaving it implicit."""
        model = self._fingerprint_model(stage)
        try:
            from app.analysis.impact_graph.knowledge import KNOWLEDGE_REGISTRY_VERSION
        except ImportError:
            KNOWLEDGE_REGISTRY_VERSION = ""
        payload = "\x1f".join([
            stage, self._primary, model, self._prompt_version(), self._schema_version(),
            KNOWLEDGE_REGISTRY_VERSION, static_prefix, seed,
            json.dumps(schema, sort_keys=True),
            str(int(settings.impact_engine_v4_strict)), POLICY_VERSION, variant,
        ])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _cache_get(self, fingerprint: str) -> dict | None:
        if self._session is None:
            return None
        try:
            from app.models import LLMStageCache, utcnow

            row = self._session.query(LLMStageCache).filter_by(fingerprint=fingerprint).one_or_none()
            if row is None:
                return None
            age_limit = utcnow() - timedelta(days=STAGE_CACHE_TTL_DAYS)
            created = row.created_at
            if created is not None and created.tzinfo is None:
                from datetime import timezone
                created = created.replace(tzinfo=timezone.utc)
            if created is not None and created < age_limit:
                return None
            stored = json.loads(row.result_json)
            # Envelope shape (Task 15, forward safety): {"__cache_envelope":
            # 1, "quality": ..., "result": ...}. A raw dict (every row
            # written before this shipped) carries no quality of its own --
            # treated as "authoritative" legacy, matching the fact that
            # this row could only have been written back when the OLD
            # (buggy, delta-comparison) guard judged it fit to cache.
            if isinstance(stored, dict) and stored.get("__cache_envelope") == 1:
                self._degrade(stored.get("quality") or "authoritative")
                return stored.get("result")
            return stored
        except Exception:  # noqa: BLE001 -- cache trouble must never fail an analysis
            logger.warning("stage cache read failed", exc_info=True)
            return None

    def _cache_put(self, fingerprint: str, stage: str, result: dict) -> None:
        if self._session is None:
            return
        try:
            from app.models import LLMStageCache, utcnow

            if self._session.query(LLMStageCache).filter_by(fingerprint=fingerprint).one_or_none() is None:
                envelope = {"__cache_envelope": 1, "quality": self.quality, "result": result}
                self._session.add(LLMStageCache(
                    fingerprint=fingerprint, stage=stage, article_id=self.article_id,
                    model=self._fingerprint_model(stage), result_json=json.dumps(envelope),
                ))
                # Opportunistic TTL sweep -- keeps the table bounded without
                # its own scheduler job.
                self._session.query(LLMStageCache).filter(
                    LLMStageCache.created_at < utcnow() - timedelta(days=STAGE_CACHE_TTL_DAYS),
                ).delete(synchronize_session=False)
                self._session.commit()
        except Exception:  # noqa: BLE001
            self._session.rollback()
            logger.warning("stage cache write failed", exc_info=True)

    def _fingerprint_model(self, stage: str) -> str:
        """The model that identifies a cache key -- keyed on the DISPATCH
        target (`_primary`), for the same reason `_fingerprint` is: a
        mid-run fallback must not silently repoint every later Claude-served
        stage at a groq-model key."""
        if self._primary == "claude":
            return self._model_for(stage)[0]
        return settings.groq_aux_model

    def _degrade(self, quality: str) -> None:
        if _QUALITY_ORDER[quality] > _QUALITY_ORDER[self.quality]:
            self.quality = quality

    # -- claude ladder ----------------------------------------------------

    def _model_for(self, stage: str) -> tuple[str, str]:
        """(model, default thinking level) for a stage. The thinking level
        is contract parity only -- claude_json.py never sends a thinking
        block -- but it still rides telemetry, so it stays honest about
        which stages are the cheap ones."""
        override = settings.claude_stage_model_override_map.get(stage)
        if override:
            return override, "high"
        if stage in FACT_STAGES:
            return settings.claude_fact_model, "low"
        if stage in SUMMARY_STAGES:
            return settings.claude_summary_model, "low"
        return settings.claude_model, "high"

    def _claude_attempt(self, stage, *, model, schema, static_prefix, suffix,
                        thinking, max_output_tokens, variant, retries,
                        context: dict | None) -> dict:
        """One Claude rung. Sets the served variant on success -- call()
        reads self._served_variant to decide cache eligibility (Task 15: a
        compact-context answer must never be cached under the full-context
        key)."""
        result = self._claude.generate(
            model=model, schema=schema, static_prefix=static_prefix,
            dynamic_suffix=suffix, thinking=thinking,
            max_output_tokens=max_output_tokens, stage=stage,
            article_id=self.article_id, budget=self.budget,
            # Telemetry (spec: retries/fallback populated from the ladder
            # position, not left permanently None).
            context={**(context or {}), "retries": retries, "fallback": False},
        )
        self._served_variant = variant
        self.context_compacted = self.context_compacted or (variant == "compact")
        return result

    def _note_auth_failure(self, exc: ClaudeJSONError) -> None:
        if exc.kind == "auth":
            self.claude_auth_failed = True
            logger.error("impact-graph Claude auth failure -- Claude disabled for the "
                         "rest of this run (article=%s); no further calls will be made "
                         "on this key", self.article_id)

    def _call_claude(self, stage, *, schema, static_prefix, dynamic_suffix,
                     compact_suffix, thinking, max_output_tokens,
                     context: dict | None = None) -> dict:
        model, default_thinking = self._model_for(stage)
        thinking = thinking or default_thinking

        last_error: Exception | None = None
        if self.claude_auth_failed:
            # Breaker open: do not touch the API at all.
            last_error = ClaudeJSONError(
                "skipped: Claude auth already failed this run", kind="auth")
        else:
            try:
                return self._claude_attempt(
                    stage, model=model, schema=schema, static_prefix=static_prefix,
                    suffix=dynamic_suffix, thinking=thinking,
                    max_output_tokens=max_output_tokens, variant="full",
                    retries=0, context=context)
            except ClaudeJSONError as exc:
                last_error = exc
                logger.warning("impact-graph %s failed on %s (kind=%s): %s",
                               stage, model, exc.kind, exc)
                self._note_auth_failure(exc)
                # Rung 2 exists ONLY for failures a smaller prompt can fix
                # (schema / truncated). Transport, rate-limit and auth
                # failures are not the prompt's fault and the SDK already
                # retried the transient ones -- retrying here would just
                # burn a second call to fail identically.
                if exc.retryable_with_compact and compact_suffix:
                    time.sleep(settings.claude_retry_backoff)
                    try:
                        return self._claude_attempt(
                            stage, model=model, schema=schema,
                            static_prefix=static_prefix, suffix=compact_suffix,
                            thinking=thinking, max_output_tokens=max_output_tokens,
                            variant="compact", retries=1, context=context)
                    except ClaudeJSONError as retry_exc:
                        last_error = retry_exc
                        logger.warning("impact-graph %s compact retry failed on %s "
                                       "(kind=%s): %s", stage, model,
                                       retry_exc.kind, retry_exc)
                        self._note_auth_failure(retry_exc)

        # Ladder end. Groq is reachable ONLY under the explicit opt-in --
        # otherwise this stage fails closed. A weaker model must never
        # silently produce financial truth (spec §47).
        if settings.llm_fallback_allowed and self._groq is not None:
            try:
                result = self._call_groq(stage, schema=schema, static_prefix=static_prefix,
                                         dynamic_suffix=dynamic_suffix)
            except Exception as exc:  # noqa: BLE001 -- ladder end
                logger.warning("impact-graph %s groq fallback also failed: %s", stage, exc)
                raise StageRouterError(
                    f"{stage}: claude failed ({last_error}) and the explicit groq "
                    f"fallback also failed: {exc}") from exc
            self.provider = "groq"
            self._degrade("fallback")
            self._served_variant = "full"  # groq always sees the full dynamic_suffix
            # Groq's own client path records its usage inside
            # RotatingClient/GroqAdapter (app.analysis.claude_client),
            # which has no `context`-style extension point for
            # retries/fallback -- a structural gap this task does not
            # widen. This summary line is the documented substitute
            # (spec: "add a router-level summary log line instead").
            logger.info("impact-graph call_summary stage=%s provider=groq fallback=True "
                        "article=%s", stage, self.article_id)
            logger.warning("impact-graph %s served by GROQ FALLBACK (quality=fallback) "
                           "after claude failed: %s", stage, last_error)
            return result
        raise StageRouterError(
            f"{stage}: claude failed and fallback is disabled: {last_error}")

    # -- groq (explicit-opt-in route AND marked last-resort fallback) ------

    def _call_groq(self, stage, *, schema, static_prefix, dynamic_suffix) -> dict:
        if self._groq is None:
            raise StageRouterError(f"{stage}: no groq client configured")
        tool = {"type": "function", "function": {
            "name": "emit", "description": f"Record the {stage} result.", "parameters": schema,
        }}
        response = self._groq.chat.completions.create(
            model=settings.groq_aux_model, max_tokens=8192, tools=[tool],
            tool_choice={"type": "function", "function": {"name": "emit"}},
            messages=[
                {"role": "system", "content": static_prefix},
                {"role": "user", "content": dynamic_suffix},
            ],
            tier="reasoning", call_name=f"impact_{stage}",
        )
        message = response.choices[0].message
        tool_calls = message.tool_calls or []
        call = next((tc for tc in tool_calls if tc.function.name == "emit"), None)
        if call is None:
            raise StageRouterError(f"{stage}: groq returned no structured result")
        try:
            return json.loads(call.function.arguments)
        except (TypeError, ValueError) as exc:
            raise StageRouterError(f"{stage}: groq tool args were not valid JSON: {exc}") from exc
