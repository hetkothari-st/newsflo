import json
from types import SimpleNamespace

from app.analysis.refinement import generate_event_summary


class FakeToolCall:
    def __init__(self, name, arguments_dict):
        self.function = SimpleNamespace(name=name, arguments=json.dumps(arguments_dict))


class QueuedFakeClient:
    """Returns queued responses in order, one per call to
    chat.completions.create -- lets a test script a first response and a
    distinct retry response, matching the reject-and-regenerate-once
    pattern every generation function in this module follows. Raises
    AssertionError if more calls happen than responses were queued."""

    def __init__(self, responses: list[tuple[str, dict]]):
        # each item: (tool_name, arguments_dict)
        self._responses = list(responses)
        self.calls = 0

    class _Completions:
        def __init__(self, outer):
            self._outer = outer

        def create(self, **kwargs):
            if not self._outer._responses:
                raise AssertionError("QueuedFakeClient: no more responses queued")
            self._outer.calls += 1
            name, arguments = self._outer._responses.pop(0)
            message = SimpleNamespace(tool_calls=[FakeToolCall(name, arguments)])
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    @property
    def chat(self):
        return SimpleNamespace(completions=self._Completions(self))


def test_generate_event_summary_returns_valid_fields():
    client = QueuedFakeClient([
        ("record_event_summary", {
            "summary_short": "RBI cuts repo rate by 25 basis points",
            "summary_long": "The RBI lowered its key lending rate. This should ease borrowing costs across the economy.",
        }),
    ])
    result = generate_event_summary(client, "RBI cuts rates", "The RBI cut the repo rate today.")
    assert result["summary_short"] == "RBI cuts repo rate by 25 basis points"
    assert "ease borrowing costs" in result["summary_long"]
    assert client.calls == 1


def test_generate_event_summary_retries_once_on_invalid_text_then_uses_retry():
    client = QueuedFakeClient([
        ("record_event_summary", {
            "summary_short": "Stock could see ~5% upside",  # rejected: percentage
            "summary_long": "A clean two sentence summary. No advice language here.",
        }),
        ("record_event_summary", {
            "summary_short": "News moves this company's outlook",
            "summary_long": "A clean two sentence summary retried. Still no advice language.",
        }),
    ])
    result = generate_event_summary(client, "t", "c")
    assert result["summary_short"] == "News moves this company's outlook"
    assert client.calls == 2


def test_generate_event_summary_returns_none_when_both_fields_invalid_even_after_retry():
    client = QueuedFakeClient([
        ("record_event_summary", {"summary_short": "Buy this stock now", "summary_long": "Sell before it drops 5%."}),
        ("record_event_summary", {"summary_short": "Buy more of this", "summary_long": "Hold for 5% gains."}),
    ])
    result = generate_event_summary(client, "t", "c")
    assert result is None
    assert client.calls == 2


def test_generate_event_summary_returns_none_when_no_tool_call():
    class NoToolCallClient:
        class _Completions:
            def create(self, **kwargs):
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None))])

        @property
        def chat(self):
            return SimpleNamespace(completions=self._Completions())

    assert generate_event_summary(NoToolCallClient(), "t", "c") is None


def test_generate_event_summary_returns_none_on_client_exception():
    """A client whose create() raises (e.g. a network error, or any other
    non-RateLimitError failure) must degrade to None, not propagate --
    same 'never raise' contract as measure_company_move."""
    class ExplodingClient:
        class _Completions:
            def create(self, **kwargs):
                raise Exception("boom: connection reset")

        @property
        def chat(self):
            return SimpleNamespace(completions=self._Completions())

    assert generate_event_summary(ExplodingClient(), "t", "c") is None


def test_generate_event_summary_returns_none_on_malformed_json_arguments():
    """A tool call whose arguments are truncated/malformed JSON (plausible
    from the small FALLBACK_MODEL) must degrade to None rather than
    letting json.JSONDecodeError propagate."""
    class MalformedToolCall:
        def __init__(self):
            self.function = SimpleNamespace(name="record_event_summary", arguments='{"summary_short": "oops",')

    class MalformedJsonClient:
        class _Completions:
            def create(self, **kwargs):
                message = SimpleNamespace(tool_calls=[MalformedToolCall()])
                return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        @property
        def chat(self):
            return SimpleNamespace(completions=self._Completions())

    assert generate_event_summary(MalformedJsonClient(), "t", "c") is None
