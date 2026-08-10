"""The two cost guards added after the 2026-08-10 paid-key leak: the facts
memo (a cheap-stage failure must never re-bill the paid facts stage) and
the process-wide Groq pacing hook."""
import time
from types import SimpleNamespace

import pytest

from app.analysis import cascade, claude_client
from app.config import settings


def _facts_response(payload='{"category": "oil_gas", "event_type": "trade_policy", "facts": "some facts"}'):
    tool_call = SimpleNamespace(function=SimpleNamespace(name="record_facts", arguments=payload))
    message = SimpleNamespace(tool_calls=[tool_call])
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _CountingClient:
    def __init__(self):
        self.calls = 0
        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.calls += 1
                return _facts_response()

        self.chat = SimpleNamespace(completions=_Completions())


def test_extract_facts_memo_never_rebills_same_article(monkeypatch):
    cascade._FACTS_MEMO.clear()
    client = _CountingClient()

    first = cascade._extract_facts(client, "Russia oil imports", "content body")
    second = cascade._extract_facts(client, "Russia oil imports", "content body")

    assert client.calls == 1  # the paid call happened exactly once
    assert first == second


def test_extract_facts_memo_is_bounded(monkeypatch):
    cascade._FACTS_MEMO.clear()
    client = _CountingClient()
    for i in range(cascade._FACTS_MEMO_MAX + 10):
        cascade._extract_facts(client, f"title {i}", "content")
    assert len(cascade._FACTS_MEMO) == cascade._FACTS_MEMO_MAX


def test_groq_pacing_spaces_consecutive_calls(monkeypatch):
    monkeypatch.setattr(settings, "groq_min_call_interval_seconds", 0.2)
    claude_client._last_groq_call_at = 0.0

    started = time.monotonic()
    claude_client._pace_groq_call()
    claude_client._pace_groq_call()
    elapsed = time.monotonic() - started

    # Windows time.sleep granularity can undershoot by ~15ms -- the guard
    # is "consecutive calls are spaced", not sub-ms precision.
    assert elapsed >= 0.15


def test_groq_pacing_disabled_by_default(monkeypatch):
    monkeypatch.setattr(settings, "groq_min_call_interval_seconds", 0.0)
    started = time.monotonic()
    for _ in range(5):
        claude_client._pace_groq_call()
    assert time.monotonic() - started < 0.05
