import json
from types import SimpleNamespace

import pytest

from app.analysis.cascade import _extract_facts


class FakeToolCall:
    def __init__(self, name, arguments_dict):
        self.function = SimpleNamespace(name=name, arguments=json.dumps(arguments_dict))


class ScriptedClient:
    """Returns a canned tool-call response keyed by the requested tool name
    (kwargs["tool_choice"]["function"]["name"]) -- order-independent, so a
    test can stub only the stage(s) it cares about. Raises AssertionError
    if a stage the test didn't script is actually called, surfacing an
    unexpected extra call immediately instead of a confusing downstream
    failure."""

    def __init__(self, responses: dict):
        self._responses = responses
        self.calls = []

    class _Completions:
        def __init__(self, outer):
            self._outer = outer

        def create(self, **kwargs):
            name = kwargs["tool_choice"]["function"]["name"]
            self._outer.calls.append({"name": name, "model": kwargs.get("model")})
            if name not in self._outer._responses:
                raise AssertionError(f"unscripted stage called: {name}")
            response = self._outer._responses[name]
            if isinstance(response, Exception):
                raise response
            message = SimpleNamespace(tool_calls=[FakeToolCall(name, response)])
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    @property
    def chat(self):
        return SimpleNamespace(completions=self._Completions(self))


def test_extract_facts_parses_response():
    client = ScriptedClient({
        "record_facts": {
            "facts": "Rupee fell 2% against the dollar today on weak trade data.",
            "category": "macro_policy",
            "event_type": "currency_move",
        },
    })

    result = _extract_facts(client, title="Rupee falls sharply", content="The rupee weakened 2% today.")

    assert result.facts == "Rupee fell 2% against the dollar today on weak trade data."
    assert result.category == "macro_policy"
    assert result.event_type == "currency_move"


def test_extract_facts_calls_fallback_model_only():
    from app.analysis.claude_client import FALLBACK_MODEL

    client = ScriptedClient({
        "record_facts": {"facts": "x", "category": "other", "event_type": "other"},
    })

    _extract_facts(client, title="t", content="c")

    assert client.calls == [{"name": "record_facts", "model": FALLBACK_MODEL}]


def test_extract_facts_raises_on_missing_tool_use_block():
    class NoToolCallClient:
        class _Completions:
            def create(self, **kwargs):
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None))])

        @property
        def chat(self):
            return SimpleNamespace(completions=self._Completions())

    with pytest.raises(ValueError, match="record_facts"):
        _extract_facts(NoToolCallClient(), title="Test Title", content="c")
