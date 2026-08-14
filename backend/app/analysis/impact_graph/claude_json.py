"""Claude structured-output client for the impact-graph engine.

The AUTHORITATIVE provider adapter (provider-migration spec sections 3, 10).
Speaks forced tool-use: one `emit` tool whose input_schema IS the stage's
existing V4 JSON schema, `tool_choice` pinned to it -- the reply's tool
input is schema-conforming by construction, no prose parsing.

Prompt shape mirrors gemini_json.py's cache-friendly split: `static_prefix`
(byte-identical across calls of a stage) rides the system block under an
ephemeral cache_control marker so Anthropic's prompt cache serves it on
repeat calls; `dynamic_suffix` (facts, frontier, candidates) is the user
message. No thinking/temperature/top_p is ever sent -- omitting `thinking`
is valid on every current Claude model, and 4.6+ models reject sampling
params outright.

Retries live in two places, neither of them here as a loop: the SDK client
retries transient failures (429/5xx/connection, honoring Retry-After) up to
settings.claude_max_retries times; the StageRouter owns the single compact
correction rung for schema failures. This module makes exactly one
`messages.create` call per generate().
"""
import logging
import time

import anthropic

from app.analysis.impact_graph.budget import _estimate_cost
from app.analysis.usage_log import CallUsage, record_usage, usage_from_anthropic
from app.config import settings

logger = logging.getLogger(__name__)

_CONTEXT_KEYS = frozenset({
    "parent_node", "mechanism_id", "candidate_count", "prompt_version", "schema_version",
    "retries", "fallback",
})

# ClaudeJSONError.kind values that a compact-context correction retry can
# plausibly fix (the model produced a wrong-shaped or overlong answer).
# Transport/auth/rate-limit failures are not the prompt's fault.
_COMPACT_RETRYABLE_KINDS = frozenset({"schema", "truncated"})


class ClaudeJSONError(Exception):
    """Any Claude API failure or an unusable structured response."""

    def __init__(self, message: str, status_code: int | None = None,
                 kind: str = "transport"):
        super().__init__(message)
        self.status_code = status_code
        self.kind = kind

    @property
    def retryable_with_compact(self) -> bool:
        return self.kind in _COMPACT_RETRYABLE_KINDS


class ClaudeJSONClient:
    def __init__(self, api_key: str, client=None):
        self._api_key = api_key
        self._client = client  # injected fake in tests; real SDK client lazily

    def _sdk(self):
        if self._client is None:
            self._client = anthropic.Anthropic(
                api_key=self._api_key,
                timeout=settings.claude_timeout,
                max_retries=settings.claude_max_retries,
            )
        return self._client

    def generate(
        self, *, model: str, schema: dict, static_prefix: str, dynamic_suffix: str,
        thinking: str = "high", max_output_tokens: int = 8192,
        stage: str | None = None, article_id: int | None = None, budget=None,
        context: dict | None = None,
    ) -> dict:
        """One structured-output call. Returns the parsed dict. Raises
        ClaudeJSONError on any failure -- ladder policy is the router's job."""
        context = {k: v for k, v in (context or {}).items() if k in _CONTEXT_KEYS}
        max_tokens = max(max_output_tokens, settings.claude_max_output_tokens)
        started = time.monotonic()
        try:
            response = self._sdk().messages.create(
                model=model,
                max_tokens=max_tokens,
                system=[{"type": "text", "text": static_prefix,
                         "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": dynamic_suffix}],
                tools=[{"name": "emit",
                        "description": f"Record the {stage} result.",
                        "input_schema": schema}],
                tool_choice={"type": "tool", "name": "emit",
                             "disable_parallel_tool_use": True},
            )
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            self._record_failure(stage, model, thinking, started, article_id, context)
            raise ClaudeJSONError(
                f"Claude auth failure: {type(exc).__name__}",
                status_code=getattr(exc, "status_code", None), kind="auth") from exc
        except anthropic.RateLimitError as exc:
            self._record_failure(stage, model, thinking, started, article_id, context)
            raise ClaudeJSONError(
                "Claude rate limited after SDK retries",
                status_code=429, kind="rate_limit") from exc
        except (anthropic.APIConnectionError,) as exc:  # includes APITimeoutError
            self._record_failure(stage, model, thinking, started, article_id, context)
            # Never let the key reach a log line via an exception string.
            raise ClaudeJSONError(
                f"Claude request failed: {type(exc).__name__}", kind="transport") from exc
        except anthropic.APIStatusError as exc:
            self._record_failure(stage, model, thinking, started, article_id, context)
            raise ClaudeJSONError(
                f"Claude returned {exc.status_code}: {type(exc).__name__}",
                status_code=exc.status_code, kind="transport") from exc
        latency_ms = int((time.monotonic() - started) * 1000)

        parsed, parse_error = self._parse(response, stage)
        usage = usage_from_anthropic(
            response, call_name=stage, model=model, tier="reasoning",
            stage=stage, thinking_level=thinking, latency_ms=latency_ms,
            article_id=article_id, success=parse_error is None,
            returned_count=_returned_count(parsed), cache_hit=False, **context,
        )
        usage.provider = "claude"
        usage.estimated_cost_usd = _estimate_cost(
            model, usage.input_tokens or 0, usage.output_tokens or 0,
            usage.cache_read_tokens or 0,
        )
        record_usage(usage)
        if budget is not None:
            budget.record(
                stage or "unknown", input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens, thinking_tokens=None,
                cached_tokens=usage.cache_read_tokens, model=model,
            )
        if parse_error is not None:
            raise parse_error
        return parsed

    @staticmethod
    def _parse(response, stage) -> tuple[dict | None, ClaudeJSONError | None]:
        stop = getattr(response, "stop_reason", None)
        if stop == "refusal":
            return None, ClaudeJSONError(f"Claude refused stage {stage}", kind="refusal")
        if stop == "max_tokens":
            return None, ClaudeJSONError(
                f"Claude output truncated at max_tokens for stage {stage}", kind="truncated")
        block = next((b for b in getattr(response, "content", [])
                      if getattr(b, "type", None) == "tool_use"
                      and getattr(b, "name", None) == "emit"), None)
        if block is None or not isinstance(block.input, dict):
            return None, ClaudeJSONError(
                f"Claude returned no structured emit result (stop_reason={stop})",
                kind="schema")
        return block.input, None

    def _record_failure(self, stage, model, thinking, started, article_id, context) -> None:
        record_usage(CallUsage(
            provider="claude", call_name=stage, model=model, stage=stage,
            thinking_level=thinking,
            latency_ms=int((time.monotonic() - started) * 1000),
            article_id=article_id, success=False, **context,
        ))


def _returned_count(parsed: dict | None) -> int | None:
    if not isinstance(parsed, dict):
        return None
    for key in ("companies", "children", "missing_branches", "verdicts", "shocks", "accept"):
        value = parsed.get(key)
        if isinstance(value, list):
            return len(value)
    return None
