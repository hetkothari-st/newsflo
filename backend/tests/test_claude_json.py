"""ClaudeJSONClient adapter tests (provider-migration spec sections 3, 10, 11, 16).

ZERO real API calls: the anthropic client is always injected as a fake.
"""
import pytest

import anthropic
import httpx

from app.analysis.impact_graph.claude_json import ClaudeJSONClient, ClaudeJSONError
from app.analysis import usage_log


class _Usage:
    input_tokens = 1200
    output_tokens = 340
    cache_read_input_tokens = 1000
    cache_creation_input_tokens = 0


class _ToolUse:
    type = "tool_use"
    name = "emit"

    def __init__(self, payload):
        self.input = payload


class _Response:
    def __init__(self, payload=None, stop_reason="tool_use", content=None):
        self.stop_reason = stop_reason
        self.content = content if content is not None else [_ToolUse(payload or {})]
        self.usage = _Usage()
        self.model = "claude-opus-5"


class _FakeMessages:
    def __init__(self, result=None, error=None):
        self._result, self._error = result, error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._result


class _FakeClient:
    def __init__(self, result=None, error=None):
        self.messages = _FakeMessages(result=result, error=error)


def _mk_http_response(status):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return httpx.Response(status, request=request, json={"error": {"message": "x"}})


def _client(result=None, error=None):
    fake = _FakeClient(result=result, error=error)
    return ClaudeJSONClient("test-key", client=fake), fake


def test_success_returns_tool_input_dict():
    payload = {"companies": [{"ticker": "TCS"}]}
    client, fake = _client(result=_Response(payload))
    out = client.generate(model="claude-opus-5", schema={"type": "object"},
                          static_prefix="RULES", dynamic_suffix="FACTS", stage="map_companies")
    assert out == payload
    request = fake.messages.calls[0]
    assert request["tool_choice"]["name"] == "emit"
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert request["system"][0]["text"] == "RULES"
    assert request["messages"] == [{"role": "user", "content": "FACTS"}]
    assert "thinking" not in request and "temperature" not in request


def test_success_records_claude_usage():
    usage_log.reset_usage()
    client, _ = _client(result=_Response({"companies": []}))
    client.generate(model="claude-opus-5", schema={}, static_prefix="R",
                    dynamic_suffix="F", stage="verify")
    rows = usage_log.recent_usage()
    assert rows[-1].provider == "claude"
    assert rows[-1].input_tokens == 1200
    assert rows[-1].cache_read_tokens == 1000
    assert rows[-1].success is True
    assert rows[-1].estimated_cost_usd > 0


def test_auth_error_maps_to_auth_kind():
    err = anthropic.AuthenticationError(
        message="bad key", response=_mk_http_response(401), body=None)
    client, _ = _client(error=err)
    with pytest.raises(ClaudeJSONError) as e:
        client.generate(model="m", schema={}, static_prefix="R", dynamic_suffix="F", stage="s")
    assert e.value.kind == "auth"
    assert e.value.retryable_with_compact is False


def test_rate_limit_maps_to_429():
    err = anthropic.RateLimitError(
        message="slow down", response=_mk_http_response(429), body=None)
    client, _ = _client(error=err)
    with pytest.raises(ClaudeJSONError) as e:
        client.generate(model="m", schema={}, static_prefix="R", dynamic_suffix="F", stage="s")
    assert e.value.kind == "rate_limit"
    assert e.value.status_code == 429


def test_timeout_maps_to_transport():
    err = anthropic.APITimeoutError(request=httpx.Request("POST", "https://x"))
    client, _ = _client(error=err)
    with pytest.raises(ClaudeJSONError) as e:
        client.generate(model="m", schema={}, static_prefix="R", dynamic_suffix="F", stage="s")
    assert e.value.kind == "transport"


def test_missing_tool_use_is_schema_error():
    class _Text:
        type = "text"
        text = "not structured"
    client, _ = _client(result=_Response(content=[_Text()]))
    with pytest.raises(ClaudeJSONError) as e:
        client.generate(model="m", schema={}, static_prefix="R", dynamic_suffix="F", stage="s")
    assert e.value.kind == "schema"
    assert e.value.retryable_with_compact is True


def test_max_tokens_truncation_is_truncated_kind():
    client, _ = _client(result=_Response({"x": 1}, stop_reason="max_tokens"))
    with pytest.raises(ClaudeJSONError) as e:
        client.generate(model="m", schema={}, static_prefix="R", dynamic_suffix="F", stage="s")
    assert e.value.kind == "truncated"


def test_api_key_never_in_error_message():
    err = anthropic.APIConnectionError(request=httpx.Request("POST", "https://x"))
    client, _ = _client(error=err)
    with pytest.raises(ClaudeJSONError) as e:
        client.generate(model="m", schema={}, static_prefix="R", dynamic_suffix="F", stage="s")
    assert "test-key" not in str(e.value)


def test_failure_records_failed_usage():
    usage_log.reset_usage()
    err = anthropic.RateLimitError(
        message="slow down", response=_mk_http_response(429), body=None)
    client, _ = _client(error=err)
    with pytest.raises(ClaudeJSONError):
        client.generate(model="m", schema={}, static_prefix="R", dynamic_suffix="F", stage="s")
    rows = usage_log.recent_usage()
    assert rows[-1].provider == "claude" and rows[-1].success is False


def test_max_tokens_floor_applied():
    client, fake = _client(result=_Response({}))
    client.generate(model="m", schema={}, static_prefix="R", dynamic_suffix="F",
                    stage="s", max_output_tokens=8192)
    assert fake.messages.calls[0]["max_tokens"] == 16000  # settings floor wins


def test_budget_recorded():
    class _Budget:
        def __init__(self):
            self.recorded = []
        def record(self, stage, **kw):
            self.recorded.append((stage, kw))
    budget = _Budget()
    client, _ = _client(result=_Response({}))
    client.generate(model="claude-opus-5", schema={}, static_prefix="R",
                    dynamic_suffix="F", stage="verify", budget=budget)
    stage, kw = budget.recorded[0]
    assert stage == "verify" and kw["input_tokens"] == 1200 and kw["model"] == "claude-opus-5"
