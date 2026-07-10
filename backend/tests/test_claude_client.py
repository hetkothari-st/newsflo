import json
from types import SimpleNamespace

import httpx
from openai import RateLimitError

from app.analysis.claude_client import RotatingClient, analyze_article, build_client


def _rate_limit_error() -> RateLimitError:
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    response = httpx.Response(status_code=429, request=request)
    return RateLimitError("rate limited", response=response, body=None)


class FakeToolCall:
    def __init__(self, name, arguments_dict):
        self.function = SimpleNamespace(name=name, arguments=json.dumps(arguments_dict))


class FakeCompletions:
    def __init__(self, response_input):
        self._response_input = response_input

    def create(self, **kwargs):
        message = SimpleNamespace(tool_calls=[FakeToolCall("record_analysis", self._response_input)])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeChat:
    def __init__(self, response_input):
        self.completions = FakeCompletions(response_input)


class FakeClient:
    def __init__(self, response_input):
        self.chat = FakeChat(response_input)


def test_analyze_article_parses_direct_mention():
    fake_output = {
        "category": "oil_energy",
        "companies": [{
            "name": "Reliance Industries", "ticker": "RELIANCE.NS", "is_direct": True, "sector": None,
            "direction": "bullish", "magnitude_low": 2.0, "magnitude_high": 4.0,
            "rationale": "Top refiner benefits from crude price spike.",
        }],
    }
    client = FakeClient(fake_output)

    result = analyze_article(client, title="US strikes Iran oil sites", content="crude oil markets react")

    assert result.category == "oil_energy"
    assert result.companies[0].ticker == "RELIANCE.NS"
    assert result.companies[0].direction == "bullish"


def test_analyze_article_parses_sector_mention():
    fake_output = {
        "category": "oil_energy",
        "companies": [{
            "name": "oil refiners", "ticker": None, "is_direct": False, "sector": "oil_gas",
            "direction": "bullish", "magnitude_low": 1.0, "magnitude_high": 2.0,
            "rationale": "Sector-wide margin expansion.",
        }],
    }
    client = FakeClient(fake_output)

    result = analyze_article(client, title="Crude prices spike globally", content="")

    assert result.companies[0].is_direct is False
    assert result.companies[0].sector == "oil_gas"


class FakeCompletionsNoToolCall:
    """Fake completions that returns no tool_calls."""
    def create(self, **kwargs):
        message = SimpleNamespace(tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeClientNoToolUse:
    def __init__(self):
        self.chat = SimpleNamespace(completions=FakeCompletionsNoToolCall())


def test_analyze_article_raises_on_missing_tool_use_block():
    """Test that a clear ValueError is raised when the response has no tool call."""
    client = FakeClientNoToolUse()
    article_title = "Test Article Title"

    try:
        analyze_article(client, title=article_title, content="Some content")
        assert False, "Expected ValueError to be raised"
    except ValueError as e:
        assert "Claude response contained no tool_use block" in str(e)
        assert article_title in str(e)


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
