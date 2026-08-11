"""Gemini structured-output client for the impact-graph engine.

Unlike the legacy forced-tool-call adapter (claude_client.GeminiAdapter),
this speaks Gemini's native structured-output mode: responseMimeType=
application/json + responseSchema, so the reply IS schema-conforming JSON
(spec doc 3 §21 -- "do not ask for free-form JSON and then parse it
manually"). Thinking is configured per call level; thinking tokens are
billed as output and are tracked, never assumed (spec §22).

Prompt shape is cache-friendly by construction (spec doc 2 §4): callers
pass `static_prefix` (system rules + schema-stable definitions, identical
across calls) and `dynamic_suffix` (facts, frontier, candidates) and this
module always concatenates them in that order.
"""
import json
import logging
import time

import httpx

from app.analysis.usage_log import record_usage, usage_from_gemini
from app.config import GEMINI_THINKING_BUDGETS

logger = logging.getLogger(__name__)

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiJSONError(Exception):
    """Any API-level failure (429/5xx/auth/network) or an empty/unparseable
    structured response. Carries .status_code when an HTTP response existed."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class GeminiJSONClient:
    def __init__(self, api_key: str):
        self._api_key = api_key

    def generate(
        self, *, model: str, schema: dict, static_prefix: str, dynamic_suffix: str,
        thinking: str = "medium", max_output_tokens: int = 8192,
        stage: str | None = None, article_id: int | None = None, budget=None,
        temperature: float = 0.2,
    ) -> dict:
        """One structured-output call. Returns the parsed JSON dict.
        Raises GeminiJSONError on any failure -- retries/degradation are the
        router's job, not this client's."""
        body = {
            "contents": [{"role": "user", "parts": [{"text": dynamic_suffix}]}],
            "systemInstruction": {"parts": [{"text": static_prefix}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": schema,
                "maxOutputTokens": max_output_tokens,
                "temperature": temperature,
            },
        }
        budget_tokens = GEMINI_THINKING_BUDGETS.get(thinking)
        if budget_tokens is not None:
            body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": budget_tokens}

        url = f"{GEMINI_BASE_URL}/models/{model}:generateContent?key={self._api_key}"
        started = time.monotonic()
        try:
            response = httpx.post(url, json=body, timeout=180.0)
        except httpx.HTTPError as exc:
            # Never let the key reach a log line via an exception string.
            raise GeminiJSONError(f"Gemini request failed: {type(exc).__name__}") from exc
        latency_ms = int((time.monotonic() - started) * 1000)

        if response.status_code != 200:
            raise GeminiJSONError(
                f"Gemini returned {response.status_code}: {response.text[:500]}",
                status_code=response.status_code,
            )

        data = response.json()
        usage = usage_from_gemini(
            data, call_name=stage, model=model, tier="reasoning",
            stage=stage, thinking_level=thinking, latency_ms=latency_ms,
            article_id=article_id,
        )
        record_usage(usage)
        if budget is not None:
            budget.record(
                stage or "unknown", input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens, thinking_tokens=usage.thinking_tokens,
                cached_tokens=usage.cache_read_tokens, model=model,
            )

        candidates = data.get("candidates") or []
        content = candidates[0].get("content", {}) if candidates else {}
        parts = content.get("parts", [])
        text = next((p.get("text") for p in parts if p.get("text")), None)
        if text is None:
            finish = candidates[0].get("finishReason") if candidates else "NO_CANDIDATES"
            raise GeminiJSONError(f"Gemini returned no JSON content (finishReason={finish})")
        try:
            return json.loads(text)
        except ValueError as exc:
            raise GeminiJSONError(f"Gemini structured output was not valid JSON: {exc}") from exc
