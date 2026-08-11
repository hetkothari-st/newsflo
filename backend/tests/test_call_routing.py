"""CallRoutedClient: the paid-Gemini cost boundary. Protected calls and
ONLY protected calls may reach the paid chain."""
from types import SimpleNamespace

import httpx
import pytest
from openai import RateLimitError

from app.analysis.claude_client import CallRoutedClient, FallbackClient, build_client
from app.config import LLM_PROTECTED_CALLS


class _RecordingClient:
    def __init__(self, name):
        self.name = name
        self.calls = []
        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.calls.append(kwargs.get("call_name"))
                return SimpleNamespace(choices=[])

        self.chat = SimpleNamespace(completions=_Completions())


def test_protected_calls_route_to_paid_chain_everything_else_default():
    paid, free = _RecordingClient("paid"), _RecordingClient("free")
    client = CallRoutedClient(paid, free, LLM_PROTECTED_CALLS)

    for call in ("extract_facts", "identify_companies"):
        client.chat.completions.create(call_name=call, tier="reasoning")
    for call in ("classify_relevance", "identify_sectors", "event_summary",
                 "generate_edges", "impact_whys", "ripple_layers"):
        client.chat.completions.create(call_name=call, tier="reasoning")

    assert paid.calls == ["extract_facts", "identify_companies"]
    assert "extract_facts" not in free.calls and "identify_companies" not in free.calls
    assert len(free.calls) == 6


def test_missing_call_name_never_spends_the_paid_budget():
    paid, free = _RecordingClient("paid"), _RecordingClient("free")
    client = CallRoutedClient(paid, free, LLM_PROTECTED_CALLS)

    client.chat.completions.create(tier="reasoning")  # no call_name

    assert paid.calls == []
    assert free.calls == [None]


def test_build_client_returns_router_only_when_paid_key_present():
    routed = build_client(["gsk_x"], "free-gemini", gemini_paid_api_key="paid-gemini")
    plain = build_client(["gsk_x"], "free-gemini")

    assert isinstance(routed, CallRoutedClient)
    assert not isinstance(plain, CallRoutedClient)


# --- the granted router: budget-granted articles' safety net ---

class _ExplodingClient:
    """Free chain whose every call rate-limits -- the Groq TPD-exhausted
    production state of 2026-08-11."""

    def __init__(self):
        outer = self
        self.calls = []

        class _Completions:
            def create(self, **kwargs):
                outer.calls.append(kwargs.get("call_name"))
                request = httpx.Request("POST", "https://example.test/v1/chat/completions")
                response = httpx.Response(status_code=429, request=request)
                raise RateLimitError("rate limited", response=response, body=None)

        self.chat = SimpleNamespace(completions=_Completions())


def test_granted_router_backstops_cheap_calls_with_the_paid_chain():
    paid, free = _RecordingClient("paid"), _ExplodingClient()
    granted = CallRoutedClient(
        paid, FallbackClient(free, paid), LLM_PROTECTED_CALLS,
    )

    granted.chat.completions.create(call_name="identify_sectors", tier="reasoning")

    # Free chain was tried first (Groq stays primary for cheap work) and
    # only its rate-limit pushed the call to the paid chain.
    assert free.calls == ["identify_sectors"]
    assert paid.calls == ["identify_sectors"]


def test_plain_router_has_no_paid_backstop_for_cheap_calls():
    paid, free = _RecordingClient("paid"), _ExplodingClient()
    router = CallRoutedClient(paid, free, LLM_PROTECTED_CALLS)

    with pytest.raises(RateLimitError):
        router.chat.completions.create(call_name="identify_sectors", tier="reasoning")
    assert paid.calls == []


def test_build_client_attaches_a_granted_router_beside_the_plain_one():
    routed = build_client(["gsk_x"], None, gemini_paid_api_key="paid-gemini")

    assert isinstance(routed.granted, CallRoutedClient)
    # Same protected chain object: the two routers cannot drift on what
    # the paid key serves first.
    assert routed.granted._protected is routed._protected
    # The granted default is the free chain wrapped with a paid fallback.
    assert isinstance(routed.granted._default, FallbackClient)
    assert routed.granted._default._primary is routed._default
