"""Per-call LLM token accounting (docs: cost-optimization phase 6).

Called from the client adapters rather than from each call site, so every
provider path is instrumented by construction and a new call site cannot
forget to report itself. Two sinks:

- a structured log line, always. This is what makes a production run's cost
  auditable after the fact without turning anything on in advance.
- an ``llm_call_usage`` row, only when settings.llm_usage_db_logging is set
  (the measurement harness sets it). Off by default so ordinary runs and
  the test suite don't accumulate rows nobody reads.

Nothing here may raise. Cost telemetry failing must never take an analysis
run down with it, so every path is wrapped and degrades to a warning.
"""
import logging
from dataclasses import dataclass
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class CallUsage:
    """One LLM call's cost. Token fields are Optional because a provider
    may report no usage block at all -- None means "not reported", which is
    different from 0 ("reported, and it was zero")."""
    provider: str
    call_name: Optional[str] = None
    model: Optional[str] = None
    tier: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cache_read_tokens: Optional[int] = None
    cache_write_tokens: Optional[int] = None
    # -- Impact-graph v3 telemetry (spec 2026-08-11 §15). All optional and
    # None for legacy call paths that don't report them.
    stage: Optional[str] = None
    thinking_level: Optional[str] = None
    thinking_tokens: Optional[int] = None
    latency_ms: Optional[int] = None
    retries: Optional[int] = None
    estimated_cost_usd: Optional[float] = None
    article_id: Optional[int] = None

    @property
    def cache_status(self) -> str:
        if self.cache_read_tokens is None:
            return "unknown"
        return "hit" if self.cache_read_tokens > 0 else "miss"


# In-process tally, so a harness can run N articles and read the totals
# straight back without a database. Bounded: this is a long-lived server
# process, and an unbounded list of every call it ever made is a leak.
_MAX_RECENT = 2000
_recent: list[CallUsage] = []


def recent_usage() -> list[CallUsage]:
    """Every call recorded in this process since the last reset (most
    recent last), capped at the last _MAX_RECENT."""
    return list(_recent)


def reset_usage() -> None:
    _recent.clear()


def record_usage(usage: CallUsage) -> None:
    """Record one call. Never raises."""
    try:
        _recent.append(usage)
        if len(_recent) > _MAX_RECENT:
            del _recent[:-_MAX_RECENT]
        logger.info(
            "llm_call call=%s provider=%s model=%s tier=%s input_tokens=%s output_tokens=%s "
            "cache_read_tokens=%s cache_write_tokens=%s cache=%s stage=%s thinking=%s "
            "thinking_tokens=%s latency_ms=%s retries=%s est_cost_usd=%s article_id=%s",
            usage.call_name, usage.provider, usage.model, usage.tier,
            usage.input_tokens, usage.output_tokens,
            usage.cache_read_tokens, usage.cache_write_tokens, usage.cache_status,
            usage.stage, usage.thinking_level, usage.thinking_tokens,
            usage.latency_ms, usage.retries, usage.estimated_cost_usd, usage.article_id,
        )
        if settings.llm_usage_db_logging:
            _persist(usage)
    except Exception:  # pragma: no cover - defensive, telemetry never breaks a run
        logger.warning("llm usage recording failed", exc_info=True)


def _persist(usage: CallUsage) -> None:
    """Write one row on its own short-lived session. Deliberately NOT the
    caller's session: an analysis run's transaction must not gain a
    telemetry row it would roll back on failure -- the cost was incurred
    whether or not the analysis succeeded, and that is exactly the run
    whose cost you most want a record of."""
    from app.db import SessionLocal
    from app.models import LLMCallUsage

    session = SessionLocal()
    try:
        session.add(LLMCallUsage(
            call_name=usage.call_name, provider=usage.provider, model=usage.model,
            tier=usage.tier, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens, cache_write_tokens=usage.cache_write_tokens,
        ))
        session.commit()
    except Exception:
        session.rollback()
        logger.warning("llm usage row could not be persisted", exc_info=True)
    finally:
        session.close()


def _int_or_none(value) -> Optional[int]:
    return int(value) if isinstance(value, (int, float)) else None


def usage_from_anthropic(response, **fields) -> CallUsage:
    usage = getattr(response, "usage", None)
    return CallUsage(
        provider="anthropic",
        input_tokens=_int_or_none(getattr(usage, "input_tokens", None)),
        output_tokens=_int_or_none(getattr(usage, "output_tokens", None)),
        cache_read_tokens=_int_or_none(getattr(usage, "cache_read_input_tokens", None)),
        cache_write_tokens=_int_or_none(getattr(usage, "cache_creation_input_tokens", None)),
        **fields,
    )


def usage_from_gemini(payload: dict, **fields) -> CallUsage:
    metadata = (payload or {}).get("usageMetadata") or {}
    # Gemini reports the cached slice as a subset of promptTokenCount, and
    # only when its implicit cache actually served part of the prompt.
    # thoughtsTokenCount is the thinking-model reasoning spend, billed as
    # output (spec 2026-08-11 §15 requires it tracked, not assumed).
    return CallUsage(
        provider="gemini",
        input_tokens=_int_or_none(metadata.get("promptTokenCount")),
        output_tokens=_int_or_none(metadata.get("candidatesTokenCount")),
        cache_read_tokens=_int_or_none(metadata.get("cachedContentTokenCount")),
        thinking_tokens=_int_or_none(metadata.get("thoughtsTokenCount")),
        **fields,
    )


def usage_from_openai(response, **fields) -> CallUsage:
    usage = getattr(response, "usage", None)
    details = getattr(usage, "prompt_tokens_details", None)
    return CallUsage(
        provider="groq",
        input_tokens=_int_or_none(getattr(usage, "prompt_tokens", None)),
        output_tokens=_int_or_none(getattr(usage, "completion_tokens", None)),
        cache_read_tokens=_int_or_none(getattr(details, "cached_tokens", None)),
        **fields,
    )
