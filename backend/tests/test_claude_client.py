import json
from types import SimpleNamespace

import httpx
from anthropic import BadRequestError as AnthropicBadRequestError
from anthropic import RateLimitError as AnthropicRateLimitError
from openai import RateLimitError

from app.analysis.claude_client import (
    ANTHROPIC_MODEL,
    AnthropicAdapter,
    FallbackClient,
    RotatingClient,
    build_client,
)


def _rate_limit_error() -> RateLimitError:
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    response = httpx.Response(status_code=429, request=request)
    return RateLimitError("rate limited", response=response, body=None)


def _anthropic_rate_limit_error() -> AnthropicRateLimitError:
    request = httpx.Request("POST", "https://example.test/v1/messages")
    response = httpx.Response(status_code=429, request=request)
    return AnthropicRateLimitError("rate limited", response=response, body=None)


def test_build_client_returns_rotating_client_for_a_list():
    client = build_client(["key-one", "key-two"])
    assert isinstance(client, RotatingClient)


def test_build_client_returns_plain_client_for_a_single_key():
    from openai import OpenAI
    client = build_client("key-one")
    assert isinstance(client, OpenAI)


class _FailingUnderlyingClient:
    """Mimics an OpenAI client whose .chat.completions.create always raises."""
    def __init__(self, error):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._raise))
        self._error = error

    def _raise(self, **kwargs):
        raise self._error


def test_rotating_client_fails_over_to_next_key_on_rate_limit(monkeypatch):
    rotator = RotatingClient(["key-a", "key-b"], base_url="https://example.test/v1")
    sentinel = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[]))])
    rotator._clients[0] = _FailingUnderlyingClient(_rate_limit_error())
    rotator._clients[1] = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: sentinel)))

    result = rotator.chat.completions.create(model="m", messages=[])

    assert result is sentinel
    assert rotator._active == 1  # stuck on the working key


def test_rotating_client_sticks_with_working_key_on_subsequent_calls(monkeypatch):
    rotator = RotatingClient(["key-a", "key-b"], base_url="https://example.test/v1")
    calls = {"a": 0, "b": 0}

    def make(counter_key):
        def create(**kwargs):
            calls[counter_key] += 1
            return SimpleNamespace(choices=[])
        return create

    rotator._clients[0] = _FailingUnderlyingClient(_rate_limit_error())
    rotator._clients[1] = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=make("b"))))

    rotator.chat.completions.create(model="m", messages=[])
    rotator.chat.completions.create(model="m", messages=[])

    # Second call goes straight to the working key -- key-a is not retried.
    assert calls["b"] == 2


def test_rotating_client_raises_when_every_key_is_rate_limited():
    rotator = RotatingClient(["key-a", "key-b"], base_url="https://example.test/v1")
    rotator._clients[0] = _FailingUnderlyingClient(_rate_limit_error())
    rotator._clients[1] = _FailingUnderlyingClient(_rate_limit_error())

    try:
        rotator.chat.completions.create(model="m", messages=[])
        assert False, "Expected RateLimitError to propagate"
    except RateLimitError:
        pass


def test_rotating_client_does_not_rotate_on_non_rate_limit_errors():
    rotator = RotatingClient(["key-a", "key-b"], base_url="https://example.test/v1")
    rotator._clients[0] = _FailingUnderlyingClient(ValueError("something else broke"))
    rotator._clients[1] = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kw: (_ for _ in ()).throw(AssertionError("should not be called")),
    )))

    try:
        rotator.chat.completions.create(model="m", messages=[])
        assert False, "Expected ValueError to propagate without rotating"
    except ValueError:
        pass


def _gemini_api_error() -> "GeminiAPIError":
    from app.analysis.claude_client import GeminiAPIError
    return GeminiAPIError("Gemini API returned 429: quota exceeded")


def test_build_client_wraps_in_fallback_when_gemini_key_given():
    from app.analysis.claude_client import GeminiAdapter
    client = build_client("groq-key", "gemini-key")
    assert isinstance(client, FallbackClient)
    assert isinstance(client._primary, GeminiAdapter)


def test_build_client_skips_fallback_wrapper_without_gemini_key():
    client = build_client("groq-key", None)
    assert not isinstance(client, FallbackClient)


def test_fallback_client_falls_through_to_secondary_on_gemini_api_error():
    sentinel = SimpleNamespace(choices=[])
    primary = _FailingUnderlyingClient(_gemini_api_error())
    secondary = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: sentinel)))

    result = FallbackClient(primary, secondary).chat.completions.create(model="m", messages=[])

    assert result is sentinel


def test_fallback_client_uses_primary_when_it_succeeds():
    sentinel = SimpleNamespace(choices=[])
    primary = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: sentinel)))
    secondary = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kw: (_ for _ in ()).throw(AssertionError("secondary should not be called")),
    )))

    result = FallbackClient(primary, secondary).chat.completions.create(model="m", messages=[])

    assert result is sentinel


def test_fallback_client_falls_through_to_secondary_on_anthropic_rate_limit():
    sentinel = SimpleNamespace(choices=[])
    primary = _FailingUnderlyingClient(_anthropic_rate_limit_error())
    secondary = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: sentinel)))

    result = FallbackClient(primary, secondary).chat.completions.create(model="m", messages=[])

    assert result is sentinel


def test_fallback_client_falls_through_to_secondary_on_openai_rate_limit():
    sentinel = SimpleNamespace(choices=[])
    primary = _FailingUnderlyingClient(_rate_limit_error())
    secondary = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: sentinel)))

    result = FallbackClient(primary, secondary).chat.completions.create(model="m", messages=[])

    assert result is sentinel


def test_fallback_client_falls_through_to_secondary_on_anthropic_credit_failure():
    # Insufficient credit balance is anthropic.BadRequestError (400), not a
    # rate limit -- must still fall through, or a real funded-then-exhausted
    # key crashes the whole pipeline instead of degrading to Groq.
    request = httpx.Request("POST", "https://example.test/v1/messages")
    response = httpx.Response(status_code=400, request=request)
    credit_error = AnthropicBadRequestError("credit balance too low", response=response, body=None)
    sentinel = SimpleNamespace(choices=[])
    primary = _FailingUnderlyingClient(credit_error)
    secondary = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: sentinel)))

    result = FallbackClient(primary, secondary).chat.completions.create(model="m", messages=[])

    assert result is sentinel


def test_fallback_client_does_not_fall_through_on_other_errors():
    primary = _FailingUnderlyingClient(ValueError("real bug"))
    secondary = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kw: (_ for _ in ()).throw(AssertionError("secondary should not be called")),
    )))

    try:
        FallbackClient(primary, secondary).chat.completions.create(model="m", messages=[])
        assert False, "Expected ValueError to propagate without falling through"
    except ValueError:
        pass


class _FakeAnthropicToolUseBlock:
    type = "tool_use"

    def __init__(self, name, input_data):
        self.name = name
        self.input = input_data


class _FakeAnthropicMessages:
    def __init__(self, tool_input):
        self._tool_input = tool_input
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return SimpleNamespace(content=[_FakeAnthropicToolUseBlock("record_analysis", self._tool_input)])


def test_anthropic_adapter_translates_request_and_response_to_openai_shape():
    tool_input = {
        "category": "oil_energy",
        "companies": [{
            "name": "Reliance Industries", "ticker": "RELIANCE.NS", "is_direct": True, "sector": None,
            "direction": "bullish", "magnitude_low": 2.0, "magnitude_high": 4.0,
            "rationale": "Refiner margins expand.",
        }],
    }
    fake_messages = _FakeAnthropicMessages(tool_input)
    adapter = AnthropicAdapter.__new__(AnthropicAdapter)  # bypass __init__'s real Anthropic() construction
    adapter.chat = SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kw: _translate_via_fake(fake_messages, **kw),
    ))

    from app.analysis.claude_client import SYSTEM_PROMPT

    FAKE_TOOL = {
        "type": "function",
        "function": {
            "name": "record_analysis",
            "description": "test tool",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }

    result = adapter.chat.completions.create(
        max_tokens=1024,
        tools=[FAKE_TOOL],
        tool_choice={"type": "function", "function": {"name": "record_analysis"}},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Title: test\n\nContent: test"},
        ],
    )

    # Request was translated to Anthropic's shape correctly.
    assert fake_messages.last_kwargs["system"] == SYSTEM_PROMPT
    assert fake_messages.last_kwargs["tools"][0]["name"] == "record_analysis"
    assert "input_schema" in fake_messages.last_kwargs["tools"][0]
    assert fake_messages.last_kwargs["messages"] == [{"role": "user", "content": "Title: test\n\nContent: test"}]

    # Response was translated back to the OpenAI shape analyze_article expects.
    tool_call = result.choices[0].message.tool_calls[0]
    assert tool_call.function.name == "record_analysis"
    assert json.loads(tool_call.function.arguments) == tool_input


def _translate_via_fake(fake_messages, **kwargs):
    from app.analysis.claude_client import _AnthropicCompletions
    completions = _AnthropicCompletions.__new__(_AnthropicCompletions)
    completions._client = SimpleNamespace(messages=fake_messages)
    completions._model = ANTHROPIC_MODEL
    return completions.create(**kwargs)


def _gemini_response(function_name: str, args: dict) -> httpx.Response:
    request = httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent")
    body = {
        "candidates": [{
            "content": {
                "parts": [{"functionCall": {"name": function_name, "args": args}}],
                "role": "model",
            },
            "finishReason": "STOP",
        }],
    }
    return httpx.Response(status_code=200, request=request, json=body)


def _gemini_response_no_function_call() -> httpx.Response:
    request = httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent")
    body = {"candidates": [{"content": {"parts": [{"text": "no tool call here"}], "role": "model"}, "finishReason": "STOP"}]}
    return httpx.Response(status_code=200, request=request, json=body)


def test_gemini_adapter_translates_request_and_response_to_openai_shape(monkeypatch):
    from app.analysis.claude_client import GEMINI_MODEL, GeminiAdapter

    tool_input = {
        "category": "oil_energy",
        "companies": [{
            "name": "Reliance Industries", "ticker": "RELIANCE.NS", "is_direct": True, "sector": None,
            "direction": "bullish", "magnitude_low": 2.0, "magnitude_high": 4.0,
            "rationale": "Refiner margins expand.",
        }],
    }
    captured = {}

    def fake_post(url, *, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return _gemini_response("record_analysis", tool_input)

    monkeypatch.setattr("app.analysis.claude_client.httpx.post", fake_post)

    adapter = GeminiAdapter("test-gemini-key")

    from app.analysis.claude_client import SYSTEM_PROMPT

    FAKE_TOOL = {
        "type": "function",
        "function": {
            "name": "record_analysis",
            "description": "test tool",
            "parameters": {
                "type": "object",
                "properties": {"category": {"type": "string"}},
                "required": ["category"],
            },
        },
    }

    result = adapter.chat.completions.create(
        max_tokens=1024,
        tools=[FAKE_TOOL],
        tool_choice={"type": "function", "function": {"name": "record_analysis"}},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "Title: test\n\nContent: test"},
        ],
    )

    # Request was translated to Gemini's shape correctly.
    assert f"models/{GEMINI_MODEL}:generateContent" in captured["url"]
    assert "key=test-gemini-key" in captured["url"]
    sent = captured["json"]
    assert sent["systemInstruction"]["parts"][0]["text"] == SYSTEM_PROMPT
    assert sent["contents"] == [{"role": "user", "parts": [{"text": "Title: test\n\nContent: test"}]}]
    sent_schema = sent["tools"][0]["function_declarations"][0]["parameters"]
    assert sent_schema["type"] == "OBJECT"  # uppercased from "object"
    assert sent_schema["properties"]["category"]["type"] == "STRING"  # uppercased from "string"
    assert sent["tool_config"]["function_calling_config"]["mode"] == "ANY"
    assert sent["generationConfig"]["maxOutputTokens"] == 1024

    # Response was translated back to the OpenAI shape analyze_article expects.
    tool_call = result.choices[0].message.tool_calls[0]
    assert tool_call.function.name == "record_analysis"
    assert json.loads(tool_call.function.arguments) == tool_input  # args re-serialized to a JSON string


def test_gemini_adapter_returns_empty_tool_calls_when_no_function_call(monkeypatch):
    from app.analysis.claude_client import GeminiAdapter

    monkeypatch.setattr(
        "app.analysis.claude_client.httpx.post",
        lambda url, *, json, timeout: _gemini_response_no_function_call(),
    )
    adapter = GeminiAdapter("test-gemini-key")

    result = adapter.chat.completions.create(
        max_tokens=1024,
        tools=[{"type": "function", "function": {"name": "record_analysis", "description": "d", "parameters": {"type": "object", "properties": {}, "required": []}}}],
        tool_choice={"type": "function", "function": {"name": "record_analysis"}},
        messages=[{"role": "user", "content": "test"}],
    )

    assert result.choices[0].message.tool_calls == []


def test_uppercase_schema_types_handles_real_nullable_list_typed_field():
    # Regression test for the Critical finding: build_company_tool's real,
    # in-production schema has a JSON-Schema list-valued nullable field
    # ("ticker": {"type": ["string", "null"]}), nested two levels deep
    # inside array `items`/object `properties`. A naive dict.get(result
    # ["type"], ...) on a list-valued type raises "TypeError: unhashable
    # type: 'list'" the instant it's reached -- this must not crash, and
    # must translate to Gemini's single-type-string + `nullable` shape.
    from app.analysis.cascade import build_company_tool
    from app.analysis.claude_client import _uppercase_schema_types

    schema = build_company_tool(None)["function"]["parameters"]

    result = _uppercase_schema_types(schema)  # must not raise

    company_item_properties = (
        result["properties"]["sector_companies"]["items"]
        ["properties"]["companies"]["items"]["properties"]
    )
    assert company_item_properties["ticker"] == {"type": "STRING", "nullable": True}
    # A sibling, non-nullable string field went through the ordinary path unaffected.
    assert company_item_properties["name"] == {"type": "STRING"}


def test_uppercase_schema_types_rejects_unsupported_list_shapes():
    from app.analysis.claude_client import _uppercase_schema_types

    try:
        _uppercase_schema_types({"type": ["string", "number"]})
        assert False, "Expected ValueError for a list-valued type with no 'null' member"
    except ValueError:
        pass


def test_gemini_adapter_raises_gemini_api_error_on_non_2xx_response(monkeypatch):
    from app.analysis.claude_client import GeminiAdapter, GeminiAPIError

    def fake_post(url, *, json, timeout):
        request = httpx.Request("POST", url)
        return httpx.Response(status_code=429, request=request, json={"error": {"message": "quota exceeded"}})

    monkeypatch.setattr("app.analysis.claude_client.httpx.post", fake_post)
    adapter = GeminiAdapter("test-gemini-key")

    try:
        adapter.chat.completions.create(
            max_tokens=1024,
            tools=[{"type": "function", "function": {"name": "record_analysis", "description": "d", "parameters": {"type": "object", "properties": {}, "required": []}}}],
            tool_choice={"type": "function", "function": {"name": "record_analysis"}},
            messages=[{"role": "user", "content": "test"}],
        )
        assert False, "Expected GeminiAPIError to be raised"
    except GeminiAPIError:
        pass


def test_gemini_adapter_raises_gemini_api_error_on_network_failure(monkeypatch):
    # httpx.post can raise before any response exists at all (DNS failure,
    # refused connection, connect/read timeout -- all httpx.HTTPError
    # subclasses). This must not propagate as the raw httpx exception --
    # it has to become a GeminiAPIError so FallbackClient's except tuple
    # still catches it and degrades to Groq.
    from app.analysis.claude_client import GeminiAdapter, GeminiAPIError

    def fake_post(url, *, json, timeout):
        raise httpx.ConnectTimeout("connection timed out", request=httpx.Request("POST", url))

    monkeypatch.setattr("app.analysis.claude_client.httpx.post", fake_post)
    adapter = GeminiAdapter("test-gemini-key")

    try:
        adapter.chat.completions.create(
            max_tokens=1024,
            tools=[{"type": "function", "function": {"name": "record_analysis", "description": "d", "parameters": {"type": "object", "properties": {}, "required": []}}}],
            tool_choice={"type": "function", "function": {"name": "record_analysis"}},
            messages=[{"role": "user", "content": "test"}],
        )
        assert False, "Expected GeminiAPIError to be raised"
    except GeminiAPIError:
        pass


def test_gemini_adapter_returns_empty_tool_calls_on_safety_block(monkeypatch):
    # A Gemini safety block (or a MAX_TOKENS truncation) yields a candidate
    # with finishReason set but NO "content" key at all -- this must degrade
    # to the same empty-tool_calls path as an ordinary response with no
    # function call, not raise a raw KeyError.
    from app.analysis.claude_client import GeminiAdapter

    def fake_post(url, *, json, timeout):
        request = httpx.Request("POST", url)
        return httpx.Response(
            status_code=200, request=request,
            json={"candidates": [{"finishReason": "SAFETY", "index": 0}]},
        )

    monkeypatch.setattr("app.analysis.claude_client.httpx.post", fake_post)
    adapter = GeminiAdapter("test-gemini-key")

    result = adapter.chat.completions.create(
        max_tokens=1024,
        tools=[{"type": "function", "function": {"name": "record_analysis", "description": "d", "parameters": {"type": "object", "properties": {}, "required": []}}}],
        tool_choice={"type": "function", "function": {"name": "record_analysis"}},
        messages=[{"role": "user", "content": "test"}],
    )

    assert result.choices[0].message.tool_calls == []


def test_fallback_client_falls_through_to_secondary_on_gemini_network_failure():
    # GeminiAPIError raised for a network-failure reason (not just an
    # HTTP-status reason, already covered by
    # test_fallback_client_falls_through_to_secondary_on_gemini_api_error)
    # must still trigger the same fallthrough to the secondary client.
    from app.analysis.claude_client import GeminiAPIError

    sentinel = SimpleNamespace(choices=[])
    primary = _FailingUnderlyingClient(GeminiAPIError("Gemini API request failed: ConnectTimeout"))
    secondary = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: sentinel)))

    result = FallbackClient(primary, secondary).chat.completions.create(model="m", messages=[])

    assert result is sentinel
