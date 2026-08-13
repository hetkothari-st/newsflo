"""Stage router + quality-first degradation ladder (spec doc 1 §14,
doc 2 §1-2).

For a PROTECTED article, Gemini owns every quality-critical stage:
    facts            -> settings.gemini_fact_model      (low thinking)
    everything else  -> settings.gemini_reasoning_model (high thinking)

Failure ladder (never silent):
    1. retry the same Gemini model once,
    2. retry with the compact context (when the stage supplies one),
    3. degrade to settings.gemini_fallback_model  -> quality="degraded",
    4. last resort Groq                            -> provider="groq",
                                                      quality="fallback".

For a NON-protected article the same stage contracts are served by Groq
directly (provider="groq") -- same schemas, same verification contract,
explicitly configured, never pretending to be the premium path.

The router carries the worst quality seen across a run; the engine stamps
it onto the Alert (analysis_provider / analysis_quality columns).
"""
import hashlib
import json
import logging
from datetime import timedelta

from app.analysis.impact_graph.gemini_json import GeminiJSONClient, GeminiJSONError
from app.analysis.impact_graph.publication_gate import POLICY_VERSION
from app.config import settings

logger = logging.getLogger(__name__)

# Durable stage-result cache TTL. Retries span minutes-to-hours (second
# attempt, hourly sweep, post-deploy re-queue); 3 days covers every retry
# path with margin while keeping the table small.
STAGE_CACHE_TTL_DAYS = 3

FACT_STAGES = {"extract_facts"}
SUMMARY_STAGES = {"reader_summary"}

_QUALITY_ORDER = {"authoritative": 0, "degraded": 1, "fallback": 2, "budget_exhausted": 3}


class StageRouterError(Exception):
    """Every rung of the ladder failed for a stage."""


class StageRouter:
    def __init__(self, *, protected: bool, gemini_api_key: str | None,
                 groq_client=None, article_id: int | None = None, budget=None,
                 session=None):
        self.protected = protected
        self.article_id = article_id
        self.budget = budget
        self._gemini = GeminiJSONClient(gemini_api_key) if gemini_api_key else None
        self._groq = groq_client
        self._session = session  # durable stage cache; None (tests) = no caching
        self.provider = "gemini" if (protected and self._gemini) else "groq"
        # Provider-identity honesty (corrective-v4 Task 15): a NON-protected
        # article is served by Groq from the very first call, by explicit
        # configuration -- never "authoritative" from construction onward.
        # Only a protected article routed to Gemini starts authoritative;
        # everything else earns a lower quality, it never inherits one.
        self.quality = "authoritative" if self.provider == "gemini" else "fallback"
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
        # Spend-cap circuit breaker (2026-08-12): a monthly-cap 429 is
        # terminal for the WHOLE run, not one stage -- once seen, every
        # remaining call skips the Gemini rungs entirely instead of
        # hammering a dead cap through the full ladder (measured: a capped
        # broad article burned minutes of 4-rung retries across ~10 stages).
        self.gemini_capped = False

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
        # set it back to "compact" (see _call_protected).
        self._served_variant = "full"
        if self.protected and self._gemini is not None:
            result = self._call_protected(
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
        """Semantic-cache key (cost-opt spec P12): stage + model + prompt/
        schema/knowledge versions + static prefix + the caller's semantic
        seed (or raw suffix when no seed was supplied). Version components
        make every prompt/registry change an EXPLICIT invalidation.

        Corrective-v4 Task 15 adds three more explicit-invalidation
        components: the strict-mode flag (v4-strict and legacy runs must
        never share a cache entry -- their publication semantics differ),
        POLICY_VERSION (a gate policy bump must invalidate every cached
        stage result it could have judged differently), and `variant`
        ("full" | "compact") -- the caller always looks up "full" (the
        cache never stores a compact-context result under any key; see
        call()), but keeping the marker in the payload documents the
        contract in the hash itself rather than leaving it implicit."""
        model, _ = self._model_for(stage) if (self.protected and self._gemini) \
            else (settings.groq_aux_model, "")
        try:
            from app.analysis.impact_graph.knowledge import KNOWLEDGE_REGISTRY_VERSION
        except ImportError:
            KNOWLEDGE_REGISTRY_VERSION = ""
        payload = "\x1f".join([
            stage, model, self._prompt_version(), self._schema_version(),
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
        if self.protected and self._gemini is not None:
            return self._model_for(stage)[0]
        return settings.groq_aux_model

    def _degrade(self, quality: str) -> None:
        if _QUALITY_ORDER[quality] > _QUALITY_ORDER[self.quality]:
            self.quality = quality

    # -- protected ladder -------------------------------------------------

    def _model_for(self, stage: str) -> tuple[str, str]:
        override = settings.gemini_stage_model_override_map.get(stage)
        if override:
            return override, "high"
        if stage in FACT_STAGES:
            return settings.gemini_fact_model, "low"
        if stage in SUMMARY_STAGES:
            return settings.gemini_summary_model, "low"
        return settings.gemini_reasoning_model, "high"

    @staticmethod
    def _is_spend_cap_error(exc: GeminiJSONError) -> bool:
        return exc.status_code == 429 and "spending cap" in str(exc).lower()

    def _call_protected(self, stage, *, schema, static_prefix, dynamic_suffix,
                        compact_suffix, thinking, max_output_tokens,
                        context: dict | None = None) -> dict:
        model, default_thinking = self._model_for(stage)
        thinking = thinking or default_thinking
        # 5-tuples: (model, suffix, thinking_level, degrade_to, variant).
        # `variant` tracks whether the rung's suffix is the caller's real
        # dynamic_suffix ("full") or the trimmed compact_suffix ("compact")
        # -- call() reads self._served_variant after this returns to decide
        # cache eligibility (Task 15: a compact-context answer must never
        # be cached under the full-context key).
        attempts = [
            (model, dynamic_suffix, thinking, None, "full"),
            (model, dynamic_suffix, thinking, None, "full"),  # plain retry
        ]
        if compact_suffix:
            attempts.append((model, compact_suffix, thinking, None, "compact"))
        attempts.append((settings.gemini_fallback_model, compact_suffix or dynamic_suffix,
                         "medium", "degraded", "compact" if compact_suffix else "full"))

        last_error: Exception | None = None
        if self.gemini_capped:
            attempts = []
            last_error = GeminiJSONError("skipped: monthly spend cap already hit this run",
                                         status_code=429)
        for idx, (attempt_model, suffix, level, degrade_to, variant) in enumerate(attempts):
            try:
                result = self._gemini.generate(
                    model=attempt_model, schema=schema, static_prefix=static_prefix,
                    dynamic_suffix=suffix, thinking=level,
                    max_output_tokens=max_output_tokens, stage=stage,
                    article_id=self.article_id, budget=self.budget,
                    # Telemetry (spec: retries/fallback populated from the
                    # ladder position, not left permanently None): this
                    # attempt's index IS the retry count that preceded it,
                    # and any rung past the first is "not the primary rung".
                    context={**(context or {}), "retries": idx, "fallback": idx > 0},
                )
                if degrade_to:
                    self._degrade(degrade_to)
                    logger.warning("impact-graph %s served DEGRADED by %s", stage, attempt_model)
                self._served_variant = variant
                self.context_compacted = self.context_compacted or (variant == "compact")
                return result
            except GeminiJSONError as exc:
                last_error = exc
                logger.warning("impact-graph %s failed on %s: %s", stage, attempt_model, exc)
                if self._is_spend_cap_error(exc):
                    self.gemini_capped = True
                    logger.warning("impact-graph spend cap hit -- Gemini disabled for the "
                                   "rest of article=%s", self.article_id)
                    break

        # Last resort: Groq, loudly marked. Never merged silently.
        if self._groq is not None:
            try:
                result = self._call_groq(stage, schema=schema, static_prefix=static_prefix,
                                         dynamic_suffix=dynamic_suffix)
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
                            "retries=%s article=%s", stage, len(attempts), self.article_id)
                logger.warning("impact-graph %s served by GROQ FALLBACK (quality=fallback)", stage)
                return result
            except Exception as exc:  # noqa: BLE001 -- ladder end, report the Gemini error
                logger.warning("impact-graph %s groq fallback also failed: %s", stage, exc)
        raise StageRouterError(f"{stage}: every ladder rung failed: {last_error}")

    # -- groq (non-protected route AND marked last-resort fallback) --------

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
