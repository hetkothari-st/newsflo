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
    analyze_article,
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
            "confidence_score": 85, "time_horizon": "Short-Term",
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
            "confidence_score": 55, "time_horizon": "Medium-Term",
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


class FakeCompletionsModelFallback:
    """Raises a rate limit for the primary MODEL, succeeds for FALLBACK_MODEL."""
    def __init__(self, response_input):
        self._response_input = response_input
        self.models_called = []

    def create(self, **kwargs):
        from app.analysis.claude_client import FALLBACK_MODEL, MODEL
        self.models_called.append(kwargs["model"])
        if kwargs["model"] == MODEL:
            raise _rate_limit_error()
        assert kwargs["model"] == FALLBACK_MODEL
        message = SimpleNamespace(tool_calls=[FakeToolCall("record_analysis", self._response_input)])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_analyze_article_falls_back_to_secondary_model_on_rate_limit():
    from app.analysis.claude_client import FALLBACK_MODEL, MODEL

    fake_output = {
        "category": "oil_energy",
        "companies": [{
            "name": "Reliance Industries", "ticker": "RELIANCE.NS", "is_direct": True, "sector": None,
            "direction": "bullish", "magnitude_low": 2.0, "magnitude_high": 4.0,
            "rationale": "Top refiner benefits from crude price spike.",
            "confidence_score": 85, "time_horizon": "Short-Term",
        }],
    }
    completions = FakeCompletionsModelFallback(fake_output)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    result = analyze_article(client, title="US strikes Iran oil sites", content="crude oil markets react")

    assert result.companies[0].ticker == "RELIANCE.NS"
    assert completions.models_called == [MODEL, FALLBACK_MODEL]


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

    from app.analysis.claude_client import RECORD_ANALYSIS_TOOL, SYSTEM_PROMPT

    result = adapter.chat.completions.create(
        max_tokens=1024,
        tools=[RECORD_ANALYSIS_TOOL],
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


def test_analyze_article_works_end_to_end_via_anthropic_adapter():
    tool_input = {
        "category": "oil_energy",
        "companies": [{
            "name": "Reliance Industries", "ticker": "RELIANCE.NS", "is_direct": True, "sector": None,
            "direction": "bullish", "magnitude_low": 2.0, "magnitude_high": 4.0,
            "rationale": "Refiner margins expand.",
            "confidence_score": 85, "time_horizon": "Short-Term",
        }],
    }
    fake_messages = _FakeAnthropicMessages(tool_input)
    adapter = AnthropicAdapter.__new__(AnthropicAdapter)
    adapter.chat = SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kw: _translate_via_fake(fake_messages, **kw),
    ))

    result = analyze_article(adapter, title="US strikes Iran oil sites", content="crude oil markets react")

    assert result.category == "oil_energy"
    assert result.companies[0].ticker == "RELIANCE.NS"


def test_record_analysis_tool_no_longer_requires_confidence_score():
    from app.analysis.claude_client import RECORD_ANALYSIS_TOOL
    company_props = RECORD_ANALYSIS_TOOL["function"]["parameters"]["properties"]["companies"]["items"]
    assert "confidence_score" not in company_props["properties"]
    assert "confidence_score" not in company_props["required"]


def test_record_analysis_tool_requires_evidence_discipline_fields():
    from app.analysis.claude_client import RECORD_ANALYSIS_TOOL
    company_props = RECORD_ANALYSIS_TOOL["function"]["parameters"]["properties"]["companies"]["items"]
    for field in ["reasons", "evidence_refs", "risks", "assumptions", "unknowns", "alternative_hypothesis"]:
        assert field in company_props["properties"]
        assert field in company_props["required"]


def test_record_analysis_tool_requires_event_type_at_top_level():
    from app.analysis.claude_client import RECORD_ANALYSIS_TOOL
    top_level = RECORD_ANALYSIS_TOOL["function"]["parameters"]
    assert "event_type" in top_level["properties"]
    assert "event_type" in top_level["required"]


def test_analyze_article_parses_new_evidence_fields_when_present():
    fake_output = {
        "category": "oil_energy",
        "event_type": "crude_oil",
        "companies": [{
            "name": "Reliance Industries", "ticker": "RELIANCE.NS", "is_direct": True, "sector": None,
            "direction": "bullish", "magnitude_low": 2.0, "magnitude_high": 4.0,
            "rationale": "Top refiner benefits from crude price spike.",
            "key_points": ["Crude spikes"], "time_horizon": "Short-Term",
            "reasons": ["Refining margins widen on crude spike."],
            "evidence_refs": ["RULE_CRUDE_OIL_UP"],
            "risks": ["Margin reversal if crude falls back."],
            "assumptions": ["Crude stays elevated for the quarter."],
            "unknowns": ["Whether this is a durable supply shock or a spike."],
            "alternative_hypothesis": "Market has already priced this in.",
        }],
    }
    client = FakeClient(fake_output)

    result = analyze_article(client, title="Oil prices spike", content="crude oil markets react")

    assert result.event_type == "crude_oil"
    company = result.companies[0]
    assert company.reasons == ["Refining margins widen on crude spike."]
    assert company.evidence_refs == ["RULE_CRUDE_OIL_UP"]
    assert company.risks == ["Margin reversal if crude falls back."]
    assert company.confidence_score is None  # no longer LLM-provided


def test_analysis_instructions_contains_rulebook_and_playbook_content():
    # CASA (an earlier choice here) is NOT playbook-unique -- it also
    # appears in RULEBOOK_TEXT via RULE_BANKING_METRICS's "credit growth,
    # deposit growth, CASA, NIM, ..." text, so it wouldn't actually catch a
    # dropped PLAYBOOKS_TEXT interpolation. ARPU appears only in the
    # telecom playbook entry -- verified absent from RULEBOOK_TEXT,
    # SECTOR_DEFINITIONS, and every rule's example text.
    from app.analysis.claude_client import ANALYSIS_INSTRUCTIONS
    assert "RULE_CRUDE_OIL_UP" in ANALYSIS_INSTRUCTIONS
    assert "ARPU" in ANALYSIS_INSTRUCTIONS


def test_record_analysis_tool_requires_impact_level_and_parent_ticker():
    from app.analysis.claude_client import RECORD_ANALYSIS_TOOL
    from app.analysis.schemas import IMPACT_LEVELS
    company_props = RECORD_ANALYSIS_TOOL["function"]["parameters"]["properties"]["companies"]["items"]
    assert "impact_level" in company_props["required"]
    assert "parent_ticker" in company_props["required"]
    assert company_props["properties"]["impact_level"]["enum"] == IMPACT_LEVELS


def test_analysis_instructions_covers_indirect_impact_rules():
    from app.analysis.claude_client import ANALYSIS_INSTRUCTIONS
    assert "indirect_l1" in ANALYSIS_INSTRUCTIONS
    assert "indirect_l2" in ANALYSIS_INSTRUCTIONS
    assert "parent_ticker" in ANALYSIS_INSTRUCTIONS


def test_analyze_article_parses_indirect_impact_chain():
    fake_output = {
        "category": "tech", "event_type": "other",
        "companies": [
            {
                "name": "Nvidia", "ticker": "NVDA.NS", "is_direct": True, "sector": None,
                "direction": "bearish", "magnitude_low": 2.0, "magnitude_high": 4.0,
                "rationale": "export ban hits Nvidia directly", "time_horizon": "Short-Term",
                "impact_level": "direct", "parent_ticker": None,
            },
            {
                "name": "TSMC", "ticker": "TSM.NS", "is_direct": True, "sector": None,
                "direction": "bearish", "magnitude_low": 1.0, "magnitude_high": 2.0,
                "rationale": "TSMC fabs Nvidia's chips; lower orders reduce TSMC revenue.",
                "time_horizon": "Medium-Term", "impact_level": "indirect_l1", "parent_ticker": "NVDA.NS",
            },
        ],
    }
    client = FakeClient(fake_output)

    result = analyze_article(client, title="US restricts advanced chip exports", content="")

    direct, indirect = result.companies
    assert direct.impact_level == "direct"
    assert direct.parent_ticker is None
    assert indirect.impact_level == "indirect_l1"
    assert indirect.parent_ticker == "NVDA.NS"


def test_analyze_article_defaults_impact_level_to_direct_when_absent():
    # Legacy-shape fake output (no impact_level/parent_ticker keys at all) --
    # must still parse cleanly with the new fields defaulting.
    fake_output = {
        "category": "oil_energy",
        "companies": [{
            "name": "Reliance Industries", "ticker": "RELIANCE.NS", "is_direct": True, "sector": None,
            "direction": "bullish", "magnitude_low": 2.0, "magnitude_high": 4.0,
            "rationale": "refiner margin", "time_horizon": "Short-Term",
        }],
    }
    client = FakeClient(fake_output)

    result = analyze_article(client, title="Oil prices spike", content="")

    assert result.companies[0].impact_level == "direct"
    assert result.companies[0].parent_ticker is None
