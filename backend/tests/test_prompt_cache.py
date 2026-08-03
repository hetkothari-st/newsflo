"""Phase 2 of the cost-optimization plan: mark the stable prefix (system
prompt + tool schema) with the active provider's prompt-caching mechanism,
and make sure every call site actually puts its stable content first so
that prefix is as long as it can be.

Caching is a billing-only change -- the model is sent the same tokens and
returns the same output either way -- so these tests check the markers and
the ordering, and that turning caching off leaves the request exactly as it
was before this shipped.
"""
import json
from types import SimpleNamespace

import pytest

from app.analysis import cascade
from app.analysis.claude_client import (
    PROMPT_CACHE_SUPPORT, SYSTEM_PROMPT, _AnthropicCompletions, _GeminiCompletions,
)
from app.analysis.schemas import SectorFinding
from app.config import PROMPT_CACHE_CONTROL, settings


class _CapturingAnthropic:
    def __init__(self):
        self.kwargs = None
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.kwargs = kwargs
        block = SimpleNamespace(type="tool_use", name="record_facts", input={"facts": "f"})
        return SimpleNamespace(content=[block])


def _anthropic_call(**overrides):
    fake = _CapturingAnthropic()
    completions = _AnthropicCompletions(fake, model="claude-sonnet-4-5")
    completions.create(
        max_tokens=100,
        tools=[{"type": "function", "function": {
            "name": "record_facts", "description": "d", "parameters": {"type": "object", "properties": {}},
        }}],
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "the variable part"},
        ],
        **overrides,
    )
    return fake.kwargs


def test_anthropic_marks_system_block_with_cache_control(monkeypatch):
    monkeypatch.setattr(settings, "prompt_cache_enabled", True)
    kwargs = _anthropic_call()
    assert kwargs["system"] == [{
        "type": "text", "text": SYSTEM_PROMPT, "cache_control": PROMPT_CACHE_CONTROL,
    }]


def test_anthropic_marks_tool_schema_with_cache_control(monkeypatch):
    monkeypatch.setattr(settings, "prompt_cache_enabled", True)
    kwargs = _anthropic_call()
    assert kwargs["tools"][0]["cache_control"] == PROMPT_CACHE_CONTROL
    # The tool itself is otherwise untouched -- caching adds a marker, it
    # never rewrites the schema the model has to satisfy.
    assert kwargs["tools"][0]["name"] == "record_facts"
    assert kwargs["tools"][0]["input_schema"] == {"type": "object", "properties": {}}


def test_anthropic_sends_the_pre_caching_request_shape_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "prompt_cache_enabled", False)
    kwargs = _anthropic_call()
    assert kwargs["system"] == SYSTEM_PROMPT  # plain string, exactly as before
    assert "cache_control" not in kwargs["tools"][0]


def test_anthropic_user_message_is_never_marked(monkeypatch):
    """Only the stable prefix is cacheable. Marking the per-article message
    would spend a cache write on content that is never seen twice."""
    monkeypatch.setattr(settings, "prompt_cache_enabled", True)
    kwargs = _anthropic_call()
    assert kwargs["messages"] == [{"role": "user", "content": "the variable part"}]


def test_gemini_request_keeps_stable_content_out_of_contents(monkeypatch):
    """Gemini caches a repeated prefix implicitly -- there is no marker to
    set, so what matters is that the stable system prompt and tool schema
    ride their own top-level fields and only the variable text lands in
    `contents`."""
    captured = {}

    class _Response:
        status_code = 200

        @staticmethod
        def json():
            return {"candidates": [{"content": {"parts": [
                {"functionCall": {"name": "record_facts", "args": {"facts": "f"}}},
            ]}}]}

    monkeypatch.setattr(
        "app.analysis.claude_client.httpx.post",
        lambda url, json=None, timeout=None: (captured.update(body=json), _Response())[1],
    )
    _GeminiCompletions("key", "gemini-flash-latest").create(
        max_tokens=100,
        tools=[{"type": "function", "function": {
            "name": "record_facts", "description": "d", "parameters": {"type": "object", "properties": {}},
        }}],
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "the variable part"},
        ],
    )
    body = captured["body"]
    assert body["systemInstruction"] == {"parts": [{"text": SYSTEM_PROMPT}]}
    assert body["tools"][0]["function_declarations"][0]["name"] == "record_facts"
    assert body["contents"] == [{"role": "user", "parts": [{"text": "the variable part"}]}]


def test_prompt_cache_support_is_declared_for_every_provider():
    assert PROMPT_CACHE_SUPPORT == {"anthropic": "explicit", "gemini": "implicit", "groq": "none"}


# --- message-order audit: stable content before variable content ---

_FACTS = "UNIQUEFACTSMARKER an outage removed barrels from the market"


def _user_prompt_of(call):
    """Runs one cascade stage against a capturing client and returns the
    user message it built."""
    captured = {}

    def create(**kwargs):
        captured["prompt"] = kwargs["messages"][-1]["content"]
        name = kwargs["tool_choice"]["function"]["name"]
        payloads = {
            "record_facts": {"facts": "f", "category": "oil_gas", "event_type": "crude_oil"},
            "record_sectors": {"sectors": []},
            "record_sector_companies": {"sector_companies": []},
            "record_edge_verification": {"verifications": []},
        }
        tool_call = SimpleNamespace(function=SimpleNamespace(name=name, arguments=json.dumps(payloads[name])))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[tool_call]))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    call(client)
    return captured["prompt"]


@pytest.mark.parametrize("parent_pool", [None, "cascade"])
def test_identify_companies_puts_instructions_before_the_facts(parent_pool):
    """The regression this guards: the field instructions used to sit AFTER
    the per-article facts, which put ~6k tokens of constant text past the
    first byte that changes per call and made the cacheable prefix nearly
    worthless."""
    pool = None if parent_pool is None else [cascade.CompanyMention(
        name="Reliance", ticker="RELIANCE.NS", is_direct=True, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", time_horizon="Short-Term",
    )]
    sectors = [SectorFinding(sector="oil_gas", direction="bullish", mechanism="crude up")]
    prompt = _user_prompt_of(lambda c: cascade._identify_companies(
        c, _FACTS, sectors, impact_level="direct", parent_pool=pool,
    ))

    instructions_at = prompt.index("- ticker: write the EXACT ticker symbol")
    facts_at = prompt.index(_FACTS)
    assert instructions_at < facts_at
    # ...and the instructions are still pointed at from the end, so losing
    # their old adjacency to the answer costs nothing.
    assert prompt.rstrip().endswith("filling in every field exactly as they specify.")


def test_identify_sectors_already_leads_with_stable_content():
    prompt = _user_prompt_of(lambda c: cascade._identify_sectors(c, _FACTS, parent_sectors=None))
    assert prompt.index("SECTOR DEFINITIONS:") < prompt.index(_FACTS)


def test_extract_facts_leads_with_stable_instructions():
    prompt = _user_prompt_of(lambda c: cascade._extract_facts(c, "A title", "UNIQUEBODY"))
    assert prompt.index(cascade.FACTS_INSTRUCTIONS) < prompt.index("UNIQUEBODY")


def test_generate_edges_leads_with_stable_framing():
    prompt = _user_prompt_of(lambda c: cascade._generate_edges(c, _FACTS, "crude_oil", []))
    assert prompt.index(cascade._EDGE_VERIFY_FRAMING) < prompt.index(_FACTS)


def test_refinement_calls_lead_with_stable_framing():
    from app.analysis import refinement

    captured = []

    def create(**kwargs):
        captured.append(kwargs["messages"][-1]["content"])
        name = kwargs["tool_choice"]["function"]["name"]
        payloads = {
            "record_event_summary": {"summary_short": "s" * 20, "summary_long": "A sentence. Another one.", "is_unconfirmed": False},
            "record_timeline_effects": {"effects": []},
            "record_ripple_layers": {"layers": []},
            "record_impact_whys": {"whys": []},
        }
        tool_call = SimpleNamespace(function=SimpleNamespace(name=name, arguments=json.dumps(payloads[name])))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[tool_call]))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    refinement.generate_event_summary(client, "t", _FACTS)
    refinement.generate_timeline_effects(client, "t", _FACTS)
    refinement.generate_ripple_layers(client, "t", _FACTS, [{
        "ticker": "RELIANCE.NS", "name": "Reliance", "sector": "oil_gas", "direction": "bullish",
    }])
    refinement.generate_impact_whys(client, "t", _FACTS, [{
        "ticker": "RELIANCE.NS", "name": "Reliance", "direction": "bullish", "excess_move_pct": 2.0,
    }])

    framings = [
        refinement.EVENT_SUMMARY_FRAMING, refinement.TIMELINE_FRAMING,
        refinement.RIPPLE_LAYERS_FRAMING, refinement.IMPACT_WHY_FRAMING,
    ]
    assert len(captured) == len(framings)
    for prompt, framing in zip(captured, framings):
        assert prompt.index(framing) < prompt.index(_FACTS)
