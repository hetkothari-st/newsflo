"""Phase 4 of the cost-optimization plan: a per-call model-routing layer.

The property that matters most here is the boring one -- with the shipped
default configuration, NOTHING is downgraded and every request is byte-for-
byte what it was before tiering existed. A call moves to the cheap tier only
when a human has put its name in LLM_CHEAP_TIER_CALLS after diffing strong
against cheap output on real articles, and the two reasoning calls cannot be
moved at all.
"""
from types import SimpleNamespace

import pytest

from app.analysis import cascade, refinement
from app.analysis.claude_client import (
    GroqAdapter, _AnthropicCompletions, _GeminiCompletions, tier_kwargs,
)
from app.config import (
    LLM_PROTECTED_CALLS, LLM_TIERABLE_CALLS, LLM_TIER_CHEAP, LLM_TIER_MODELS,
    LLM_TIER_REASONING, resolve_tier, settings,
)
from app.filtering import relevance


ALL_CALLS = sorted(LLM_PROTECTED_CALLS | LLM_TIERABLE_CALLS)


def test_nothing_is_downgraded_by_default():
    """The shipped default. Every call runs on the reasoning tier until
    somebody explicitly and knowingly moves it."""
    assert settings.llm_cheap_tier_calls == ""
    for call_name in ALL_CALLS:
        assert resolve_tier(call_name) == LLM_TIER_REASONING


@pytest.mark.parametrize("call_name", sorted(LLM_PROTECTED_CALLS))
def test_protected_calls_cannot_be_downgraded_even_when_configured(call_name, monkeypatch):
    """`_extract_facts` is the one full-article read everything downstream
    depends on, and `_identify_companies` decides which companies are
    affected and why. Config must not be able to move either, however it is
    set."""
    monkeypatch.setattr(settings, "llm_cheap_tier_calls", ",".join(ALL_CALLS))
    assert resolve_tier(call_name) == LLM_TIER_REASONING


@pytest.mark.parametrize("call_name", sorted(LLM_TIERABLE_CALLS))
def test_eligible_calls_move_when_explicitly_listed(call_name, monkeypatch):
    monkeypatch.setattr(settings, "llm_cheap_tier_calls", call_name)
    assert resolve_tier(call_name) == LLM_TIER_CHEAP
    # ...and only that one moves.
    for other in LLM_TIERABLE_CALLS - {call_name}:
        assert resolve_tier(other) == LLM_TIER_REASONING


def test_unknown_call_name_stays_on_the_reasoning_tier(monkeypatch):
    monkeypatch.setattr(settings, "llm_cheap_tier_calls", "not_a_real_call")
    assert resolve_tier("not_a_real_call") == LLM_TIER_REASONING


def test_tier_kwargs_names_the_call_for_token_accounting():
    assert tier_kwargs("extract_facts") == {"tier": LLM_TIER_REASONING, "call_name": "extract_facts"}


# --- every call site actually declares itself ---

def _call_names_used_by(run) -> list[str]:
    seen = []

    def create(**kwargs):
        seen.append(kwargs.get("call_name"))
        import json
        name = kwargs["tool_choice"]["function"]["name"]
        payloads = {
            "record_facts": {"facts": "f", "category": "oil_gas", "event_type": "crude_oil"},
            "record_sectors": {"sectors": []},
            "record_sector_companies": {"sector_companies": []},
            "record_edge_verification": {"verifications": []},
            "record_relevance": {"relevant": True},
            "record_event_summary": {"summary_short": "s" * 20, "summary_long": "One. Two.", "is_unconfirmed": False},
            "record_timeline_effects": {"effects": []},
            "record_ripple_layers": {"layers": []},
            "record_impact_whys": {"whys": []},
        }
        tool_call = SimpleNamespace(function=SimpleNamespace(name=name, arguments=json.dumps(payloads[name])))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[tool_call]))])

    run(SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    return seen


def test_every_llm_call_site_declares_its_call_name():
    """An unnamed call is invisible to both the tier router and the token
    accounting, so this pins the whole set."""
    sectors = [cascade.SectorFinding(sector="oil_gas", direction="bullish", mechanism="m")]
    used = set()
    used |= set(_call_names_used_by(lambda c: cascade._extract_facts(c, "t", "b")))
    used |= set(_call_names_used_by(lambda c: cascade._identify_sectors(c, "f", None)))
    used |= set(_call_names_used_by(
        lambda c: cascade._identify_companies(c, "f", sectors, impact_level="direct", parent_pool=None)))
    used |= set(_call_names_used_by(lambda c: cascade._generate_edges(c, "f", "crude_oil", [])))
    used |= set(_call_names_used_by(lambda c: relevance.classify_relevance(c, "t", "b")))
    used |= set(_call_names_used_by(lambda c: refinement.generate_event_summary(c, "t", "f")))
    used |= set(_call_names_used_by(lambda c: refinement.generate_timeline_effects(c, "t", "f")))
    used |= set(_call_names_used_by(lambda c: refinement.generate_ripple_layers(
        c, "t", "f", [{"ticker": "X.NS", "name": "X", "sector": "it", "direction": "bullish"}])))
    used |= set(_call_names_used_by(lambda c: refinement.generate_impact_whys(
        c, "t", "f", [{"ticker": "X.NS", "name": "X", "direction": "bullish", "excess_move_pct": 1.0}])))

    assert None not in used
    assert used == set(ALL_CALLS)


# --- the client layer honours the tier, and only downwards ---

class _CapturingAnthropic:
    def __init__(self):
        self.kwargs = None
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(content=[], usage=None)


def _anthropic_model_for(tier):
    fake = _CapturingAnthropic()
    _AnthropicCompletions(fake, model="claude-sonnet-4-5").create(
        max_tokens=10, tools=[{"function": {"name": "t", "description": "d", "parameters": {}}}],
        messages=[{"role": "user", "content": "u"}], tier=tier,
    )
    return fake.kwargs["model"]


def test_anthropic_cheap_tier_swaps_the_model():
    assert _anthropic_model_for(LLM_TIER_CHEAP) == LLM_TIER_MODELS["anthropic"][LLM_TIER_CHEAP]


def test_anthropic_reasoning_tier_leaves_the_adapter_model_alone():
    assert _anthropic_model_for(LLM_TIER_REASONING) == "claude-sonnet-4-5"
    assert _anthropic_model_for(None) == "claude-sonnet-4-5"


def _gemini_url_for(tier, monkeypatch):
    captured = {}

    class _Response:
        status_code = 200

        @staticmethod
        def json():
            return {"candidates": []}

    monkeypatch.setattr(
        "app.analysis.claude_client.httpx.post",
        lambda url, json=None, timeout=None: (captured.update(url=url), _Response())[1],
    )
    _GeminiCompletions("key", "gemini-flash-latest").create(
        max_tokens=10,
        tools=[{"function": {"name": "t", "description": "d", "parameters": {"type": "object"}}}],
        messages=[{"role": "user", "content": "u"}], tier=tier,
    )
    return captured["url"]


def test_gemini_cheap_tier_swaps_the_model(monkeypatch):
    assert LLM_TIER_MODELS["gemini"][LLM_TIER_CHEAP] in _gemini_url_for(LLM_TIER_CHEAP, monkeypatch)


def test_gemini_reasoning_tier_leaves_the_adapter_model_alone(monkeypatch):
    assert "gemini-flash-latest" in _gemini_url_for(LLM_TIER_REASONING, monkeypatch)


def _groq_model_for(tier):
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(usage=None)

    GroqAdapter(SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))) \
        .chat.completions.create(model="llama-3.3-70b-versatile", messages=[], tier=tier, call_name="x")
    return captured


def test_groq_cheap_tier_swaps_the_model():
    assert _groq_model_for(LLM_TIER_CHEAP)["model"] == LLM_TIER_MODELS["groq"][LLM_TIER_CHEAP]


def test_groq_reasoning_tier_keeps_the_call_sites_own_model():
    """The cascade already picks its Groq model per stage for quota reasons
    that predate tiering. A reasoning-tier default must not rewrite that."""
    assert _groq_model_for(LLM_TIER_REASONING)["model"] == "llama-3.3-70b-versatile"


def test_groq_adapter_strips_the_tier_kwargs_before_the_openai_client_sees_them():
    """A raw OpenAI client rejects unknown kwargs outright, so these must
    not reach it -- this is what makes a degrade-to-Groq survive."""
    captured = _groq_model_for(LLM_TIER_REASONING)
    assert "tier" not in captured
    assert "call_name" not in captured
