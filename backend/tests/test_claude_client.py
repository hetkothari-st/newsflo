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


def test_build_client_wraps_in_fallback_when_anthropic_key_given():
    client = build_client("groq-key", "anthropic-key")
    assert isinstance(client, FallbackClient)
    assert isinstance(client._primary, AnthropicAdapter)


def test_build_client_skips_fallback_wrapper_without_anthropic_key():
    client = build_client("groq-key", None)
    assert not isinstance(client, FallbackClient)


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
