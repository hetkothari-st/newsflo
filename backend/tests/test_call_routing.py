"""CallRoutedClient: the paid-Gemini cost boundary. Protected calls and
ONLY protected calls may reach the paid chain."""
from types import SimpleNamespace

from app.analysis.claude_client import CallRoutedClient, build_client
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
