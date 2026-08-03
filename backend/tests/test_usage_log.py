"""Phase 6 of the cost-optimization plan: per-call token accounting.

Instrumentation lives in the client adapters, not the call sites, so this
checks that each provider's usage block is read correctly, that a missing
one degrades to "unknown" rather than a crash, and that recording can never
take a run down with it.
"""
import logging
from types import SimpleNamespace

from app.analysis.claude_client import GroqAdapter, _AnthropicCompletions, _GeminiCompletions
from app.analysis.usage_log import (
    CallUsage, record_usage, recent_usage, reset_usage,
    usage_from_anthropic, usage_from_gemini, usage_from_openai,
)
from app.config import settings


def test_anthropic_usage_includes_the_cache_breakdown():
    response = SimpleNamespace(usage=SimpleNamespace(
        input_tokens=1200, output_tokens=340,
        cache_read_input_tokens=900, cache_creation_input_tokens=0,
    ))
    usage = usage_from_anthropic(response, call_name="extract_facts", model="m", tier="reasoning")
    assert (usage.input_tokens, usage.output_tokens) == (1200, 340)
    assert usage.cache_read_tokens == 900
    assert usage.cache_status == "hit"


def test_gemini_usage_reads_the_usage_metadata_block():
    payload = {"usageMetadata": {
        "promptTokenCount": 2000, "candidatesTokenCount": 500, "cachedContentTokenCount": 0,
    }}
    usage = usage_from_gemini(payload, call_name="identify_sectors", model="m", tier="reasoning")
    assert (usage.input_tokens, usage.output_tokens) == (2000, 500)
    assert usage.cache_status == "miss"


def test_openai_usage_reads_prompt_and_completion_tokens():
    response = SimpleNamespace(usage=SimpleNamespace(
        prompt_tokens=800, completion_tokens=120,
        prompt_tokens_details=SimpleNamespace(cached_tokens=256),
    ))
    usage = usage_from_openai(response, call_name="classify_relevance", model="m", tier="cheap")
    assert (usage.input_tokens, usage.output_tokens, usage.cache_read_tokens) == (800, 120, 256)


def test_missing_usage_block_reports_unknown_rather_than_zero():
    """A provider that reports nothing is not the same as one reporting a
    cache miss -- conflating them would silently understate cost."""
    usage = usage_from_anthropic(SimpleNamespace(usage=None))
    assert usage.input_tokens is None
    assert usage.cache_status == "unknown"
    assert usage_from_gemini({}).input_tokens is None
    assert usage_from_openai(SimpleNamespace()).input_tokens is None


def test_record_usage_logs_a_structured_line(caplog):
    reset_usage()
    with caplog.at_level(logging.INFO, logger="app.analysis.usage_log"):
        record_usage(CallUsage(
            provider="gemini", call_name="extract_facts", model="gemini-flash-latest",
            tier="reasoning", input_tokens=1000, output_tokens=200, cache_read_tokens=768,
        ))
    line = caplog.text
    assert "call=extract_facts" in line
    assert "input_tokens=1000" in line
    assert "output_tokens=200" in line
    assert "cache=hit" in line


def test_record_usage_accumulates_for_a_measurement_run():
    reset_usage()
    record_usage(CallUsage(provider="gemini", call_name="a", input_tokens=10, output_tokens=1))
    record_usage(CallUsage(provider="gemini", call_name="b", input_tokens=20, output_tokens=2))
    assert [u.call_name for u in recent_usage()] == ["a", "b"]
    assert sum(u.input_tokens for u in recent_usage()) == 30
    reset_usage()
    assert recent_usage() == []


def test_record_usage_never_raises(monkeypatch):
    """Telemetry failing must not take an analysis run with it."""
    monkeypatch.setattr(settings, "llm_usage_db_logging", True)
    monkeypatch.setattr("app.analysis.usage_log._persist", lambda usage: 1 / 0)
    record_usage(CallUsage(provider="gemini", call_name="a"))  # must not raise


def test_db_persistence_is_off_by_default(monkeypatch):
    calls = []
    monkeypatch.setattr("app.analysis.usage_log._persist", lambda usage: calls.append(usage))
    record_usage(CallUsage(provider="gemini", call_name="a"))
    assert calls == []


# --- the adapters report without the call sites having to ---

def test_gemini_adapter_records_usage(monkeypatch):
    reset_usage()

    class _Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "candidates": [{"content": {"parts": []}}],
                "usageMetadata": {"promptTokenCount": 1500, "candidatesTokenCount": 100},
            }

    monkeypatch.setattr(
        "app.analysis.claude_client.httpx.post", lambda url, json=None, timeout=None: _Response(),
    )
    _GeminiCompletions("key", "gemini-flash-latest").create(
        max_tokens=10,
        tools=[{"function": {"name": "t", "description": "d", "parameters": {"type": "object"}}}],
        messages=[{"role": "user", "content": "u"}], call_name="identify_sectors", tier="reasoning",
    )
    recorded = recent_usage()[-1]
    assert recorded.provider == "gemini"
    assert recorded.call_name == "identify_sectors"
    assert recorded.model == "gemini-flash-latest"
    assert recorded.input_tokens == 1500


def test_anthropic_adapter_records_usage():
    reset_usage()

    class _Client:
        messages = SimpleNamespace(create=staticmethod(lambda **kw: SimpleNamespace(
            content=[], usage=SimpleNamespace(input_tokens=900, output_tokens=80),
        )))

    _AnthropicCompletions(_Client(), model="claude-sonnet-4-5").create(
        max_tokens=10, tools=[{"function": {"name": "t", "description": "d", "parameters": {}}}],
        messages=[{"role": "user", "content": "u"}], call_name="event_summary", tier="reasoning",
    )
    recorded = recent_usage()[-1]
    assert (recorded.provider, recorded.call_name, recorded.input_tokens) == ("anthropic", "event_summary", 900)


def test_groq_adapter_records_usage():
    reset_usage()
    inner = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kw: SimpleNamespace(usage=SimpleNamespace(prompt_tokens=400, completion_tokens=30)),
    )))
    GroqAdapter(inner).chat.completions.create(
        model="openai/gpt-oss-20b", messages=[], call_name="classify_relevance", tier="reasoning",
    )
    recorded = recent_usage()[-1]
    assert (recorded.provider, recorded.call_name, recorded.model) == (
        "groq", "classify_relevance", "openai/gpt-oss-20b",
    )
    assert recorded.output_tokens == 30
