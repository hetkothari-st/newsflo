"""Proves the structural network guard added in conftest.py (provider-
migration Task 7, full-offline-verification).

conftest.py's autouse `_no_real_anthropic_client` fixture replaces
`anthropic.Anthropic` with a raising stub for the whole test session. This
file proves both directions named in the Task 3 review pointer:

1. the legitimate path -- a test that correctly injects a fake `client=` --
   is completely unaffected by the guard;
2. the path the guard exists to catch -- a test that (by mistake) lets
   ClaudeJSONClient build its own SDK client -- fails immediately and
   loudly, at construction time, instead of attempting a real HTTPS call.
"""
import pytest

from app.analysis.impact_graph.claude_json import ClaudeJSONClient


class _Usage:
    input_tokens = 1
    output_tokens = 1
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0


class _ToolUse:
    type = "tool_use"
    name = "emit"
    input = {"ok": True}


class _Response:
    stop_reason = "tool_use"
    content = [_ToolUse()]
    usage = _Usage()
    model = "claude-opus-5"


class _FakeMessages:
    def create(self, **kwargs):
        return _Response()


class _FakeClient:
    messages = _FakeMessages()


def test_injected_fake_client_is_unaffected_by_the_guard():
    """The guard must never fire for the legitimate, already-established
    pattern used by every other test in this suite: injecting a fake
    `client=` at construction so `_sdk()` never touches `anthropic.Anthropic`
    at all."""
    client = ClaudeJSONClient("test-key", client=_FakeClient())
    out = client.generate(model="claude-opus-5", schema={"type": "object"},
                          static_prefix="RULES", dynamic_suffix="FACTS",
                          stage="map_companies")
    assert out == {"ok": True}


def test_missing_fake_client_fails_closed_instead_of_reaching_the_network():
    """The exact mistake the guard defends against: a test constructs
    ClaudeJSONClient with no `client=` kwarg, so a real call would build a
    real `anthropic.Anthropic()` inside `_sdk()`. The guard must intercept
    that construction and raise immediately -- proving no test in this
    repo can ever reach api.anthropic.com even if it forgets to mock."""
    client = ClaudeJSONClient("test-key")  # no `client=` -- the bug this guards against
    with pytest.raises(AssertionError, match="anthropic.Anthropic"):
        client.generate(model="claude-opus-5", schema={"type": "object"},
                        static_prefix="RULES", dynamic_suffix="FACTS",
                        stage="map_companies")
