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
        self.quality = "authoritative"
        self.stage_cache_hits = 0

    # -- public ----------------------------------------------------------

    def call(self, stage: str, *, schema: dict, static_prefix: str,
             dynamic_suffix: str, compact_suffix: str | None = None,
             thinking: str = "high", max_output_tokens: int = 8192) -> dict:
        """Run one stage call through the routing/degradation policy.
        Returns the parsed dict; records the worst quality reached.

        Retry-burn fix: a byte-identical stage call that already succeeded
        (this attempt, a prior failed attempt, the hourly retry sweep, or a
        pre-deploy run) replays its stored result from llm_stage_cache with
        ZERO provider traffic. Failures are never cached, and any input
        drift is a plain miss that pays normally."""
        fingerprint = self._fingerprint(stage, schema, static_prefix, dynamic_suffix)
        cached = self._cache_get(fingerprint)
        if cached is not None:
            self.stage_cache_hits += 1
            logger.info("impact-graph call_skipped stage=%s reason=stage_cache_hit article=%s",
                        stage, self.article_id)
            return cached
        if self.protected and self._gemini is not None:
            result = self._call_protected(
                stage, schema=schema, static_prefix=static_prefix,
                dynamic_suffix=dynamic_suffix, compact_suffix=compact_suffix,
                thinking=thinking, max_output_tokens=max_output_tokens,
            )
        else:
            result = self._call_groq(stage, schema=schema, static_prefix=static_prefix,
                                     dynamic_suffix=dynamic_suffix)
        self._cache_put(fingerprint, stage, result)
        return result

    # -- durable stage cache ----------------------------------------------

    def _fingerprint(self, stage: str, schema: dict, static_prefix: str,
                     dynamic_suffix: str) -> str:
        model, _ = self._model_for(stage) if (self.protected and self._gemini) \
            else (settings.groq_aux_model, "")
        payload = "\x1f".join([
            stage, model, static_prefix, dynamic_suffix,
            json.dumps(schema, sort_keys=True),
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
            return json.loads(row.result_json)
        except Exception:  # noqa: BLE001 -- cache trouble must never fail an analysis
            logger.warning("stage cache read failed", exc_info=True)
            return None

    def _cache_put(self, fingerprint: str, stage: str, result: dict) -> None:
        if self._session is None:
            return
        try:
            from app.models import LLMStageCache, utcnow

            if self._session.query(LLMStageCache).filter_by(fingerprint=fingerprint).one_or_none() is None:
                self._session.add(LLMStageCache(
                    fingerprint=fingerprint, stage=stage, article_id=self.article_id,
                    model=self._fingerprint_model(stage), result_json=json.dumps(result),
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

    def _call_protected(self, stage, *, schema, static_prefix, dynamic_suffix,
                        compact_suffix, thinking, max_output_tokens) -> dict:
        model, default_thinking = self._model_for(stage)
        thinking = thinking or default_thinking
        attempts = [
            (model, dynamic_suffix, thinking, None),
            (model, dynamic_suffix, thinking, None),  # plain retry
        ]
        if compact_suffix:
            attempts.append((model, compact_suffix, thinking, None))
        attempts.append((settings.gemini_fallback_model, compact_suffix or dynamic_suffix,
                         "medium", "degraded"))

        last_error: Exception | None = None
        for attempt_model, suffix, level, degrade_to in attempts:
            try:
                result = self._gemini.generate(
                    model=attempt_model, schema=schema, static_prefix=static_prefix,
                    dynamic_suffix=suffix, thinking=level,
                    max_output_tokens=max_output_tokens, stage=stage,
                    article_id=self.article_id, budget=self.budget,
                )
                if degrade_to:
                    self._degrade(degrade_to)
                    logger.warning("impact-graph %s served DEGRADED by %s", stage, attempt_model)
                return result
            except GeminiJSONError as exc:
                last_error = exc
                logger.warning("impact-graph %s failed on %s: %s", stage, attempt_model, exc)

        # Last resort: Groq, loudly marked. Never merged silently.
        if self._groq is not None:
            try:
                result = self._call_groq(stage, schema=schema, static_prefix=static_prefix,
                                         dynamic_suffix=dynamic_suffix)
                self.provider = "groq"
                self._degrade("fallback")
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
        return json.loads(call.function.arguments)
