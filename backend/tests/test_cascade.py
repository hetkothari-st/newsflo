import json
from types import SimpleNamespace

import pytest

from app.analysis.cascade import (
    BROAD_EVENT_TYPES, analyze_article, _extract_facts, _generate_edges, _identify_cascade_companies_per_sector,
    _identify_companies, _identify_sectors, _sector_fanout_mentions, _sector_mechanism_edges,
    build_company_tool, build_sector_tool,
)
from app.analysis.schemas import CompanyMention, SectorFinding
from app.models import Company
from app.reasoning.rulebook import CHAINS


class FakeToolCall:
    def __init__(self, name, arguments_dict):
        self.function = SimpleNamespace(name=name, arguments=json.dumps(arguments_dict))


def _tool_use_failed_error():
    """Builds a real openai.BadRequestError shaped like Groq's actual 400
    when the model emits a malformed tool-call blob -- `code` set to
    "tool_use_failed", same as what `_make_status_error` constructs from a
    real HTTP response (see openai._client.OpenAI._make_status_error: body
    passed to the exception is already `body["error"]`, so `code` lives at
    the top level of the dict passed here, not nested under "error")."""
    import httpx
    from openai import BadRequestError

    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    response = httpx.Response(status_code=400, request=request)
    return BadRequestError(
        "Failed to call a function. Please adjust your prompt.",
        response=response,
        body={
            "code": "tool_use_failed",
            "message": "Failed to call a function. Please adjust your prompt. "
                        "See 'failed_generation' for more details.",
            "failed_generation": "<function=record_sector_companies>{unbalanced...",
        },
    )


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
        self.last_tool = None
        self.last_messages = None

    class _Completions:
        def __init__(self, outer):
            self._outer = outer

        def create(self, **kwargs):
            name = kwargs["tool_choice"]["function"]["name"]
            self._outer.calls.append({"name": name, "model": kwargs.get("model")})
            self._outer.last_tool = kwargs["tools"][0]
            self._outer.last_messages = kwargs.get("messages")
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


def test_identify_sectors_primary_parses_response():
    client = ScriptedClient({
        "record_sectors": {"sectors": [
            {"sector": "banking", "direction": "bearish", "mechanism": "FX exposure on the rupee's fall."},
        ]},
    })

    result = _identify_sectors(client, facts="The rupee fell 2% today.", parent_sectors=None)

    assert len(result) == 1
    assert result[0].sector == "banking"
    assert result[0].direction == "bearish"
    assert result[0].parent_sector is None


def test_identify_sectors_cascade_sets_parent_sector():
    primary = [SectorFinding(sector="banking", direction="bearish", mechanism="FX exposure.")]
    client = ScriptedClient({
        "record_sectors": {"sectors": [
            {
                "sector": "railways_transport", "direction": "bearish",
                "mechanism": "Higher import costs for fuel/rolling stock.", "parent_sector": "banking",
            },
        ]},
    })

    result = _identify_sectors(client, facts="The rupee fell 2% today.", parent_sectors=primary)

    assert result[0].sector == "railways_transport"
    assert result[0].parent_sector == "banking"


def test_identify_sectors_empty_result_is_valid():
    client = ScriptedClient({"record_sectors": {"sectors": []}})

    result = _identify_sectors(client, facts="Nothing much happened.", parent_sectors=None)

    assert result == []


def test_identify_sectors_drops_an_off_taxonomy_sector_value():
    # A real production response returned "aviation" -- not a SECTORS
    # value (only mentioned inside railways_transport's own definition
    # text) -- which the tool schema's enum doesn't always strictly block
    # server-side. Must be dropped, not passed through: an off-taxonomy
    # sector here breaks the NEXT call's enum-constrained company schema.
    client = ScriptedClient({
        "record_sectors": {"sectors": [
            {"sector": "aviation", "direction": "bearish", "mechanism": "not a real SECTORS value"},
            {"sector": "banking", "direction": "bearish", "mechanism": "a real one"},
        ]},
    })

    result = _identify_sectors(client, facts="f", parent_sectors=None)

    assert [s.sector for s in result] == ["banking"]


def test_identify_sectors_calls_fallback_model_only():
    from app.analysis.claude_client import FALLBACK_MODEL

    client = ScriptedClient({"record_sectors": {"sectors": []}})

    _identify_sectors(client, facts="f", parent_sectors=None)

    assert client.calls == [{"name": "record_sectors", "model": FALLBACK_MODEL}]


def test_primary_sector_prompt_contains_rulebook_digest():
    # RULE_MONSOON_GOOD appears only in the digest (stage 2), never in
    # SECTOR_DEFINITIONS -- proves the digest block is actually injected
    # into the primary sector-identification call and NOT the cascade call.
    from app.analysis.cascade import _identify_sectors
    client = ScriptedClient({"record_sectors": {"sectors": []}})
    _identify_sectors(client, "some facts", None)
    prompt = client.last_messages[-1]["content"]
    assert "RULE_MONSOON_GOOD" in prompt
    assert "KNOWN TRANSMISSION CHAINS" in prompt


def test_cascade_sector_prompt_has_no_rulebook_digest():
    from app.analysis.cascade import _identify_sectors
    from app.analysis.schemas import SectorFinding
    client = ScriptedClient({"record_sectors": {"sectors": []}})
    parents = [SectorFinding(sector="banking", direction="bullish", mechanism="m")]
    _identify_sectors(client, "some facts", parents)
    prompt = client.last_messages[-1]["content"]
    assert "KNOWN TRANSMISSION CHAINS" not in prompt


def test_primary_sector_framing_asks_for_every_sector_with_a_real_channel():
    # The Boeing 737 MAX 7 regression: _identify_sectors returned only
    # `defense`, so airlines/airports, aerospace components, forgings and
    # infra had no candidate list to be selected from at all. Breadth has to
    # start here -- no later stage can recover a sector never named.
    client = ScriptedClient({"record_sectors": {"sectors": []}})
    _identify_sectors(client, "some facts", None)
    prompt = client.last_messages[-1]["content"]

    assert "EVERY financial, business, or economic sector" in prompt
    assert "not just the single most obvious one" in prompt
    # Names the transmission channels to walk, rather than leaving "directly
    # affected" to be read as "the sector the headline is about".
    for channel in ["supplies its components", "who buys or operates it",
                    "maintains and services it", "who regulates it"]:
        assert channel in prompt
    assert "failure of thoroughness" in prompt


def test_primary_sector_framing_keeps_the_zero_sector_guard_intact():
    # The hard guard that a story with no economic mechanism correctly
    # returns nothing. Broadening the framing above must not erode it: an
    # accident/crime/human-interest story still yields zero sectors.
    client = ScriptedClient({"record_sectors": {"sectors": []}})
    _identify_sectors(client, "some facts", None)
    prompt = client.last_messages[-1]["content"]

    assert "Zero sectors is a correct answer" in prompt
    assert "accident, disaster, crime, or human-interest story has zero real sectors" in prompt
    assert "Do not manufacture a mechanism" in prompt
    # And the breadth instruction is explicitly scoped so it cannot be read
    # as licence to invent a channel.
    assert "does NOT weaken this" in prompt
    assert "never inventing a channel" in prompt


def test_company_rationale_instructions_forbid_verbatim_echo():
    from app.analysis.cascade import COMPANY_RATIONALE_INSTRUCTIONS
    assert "verbatim" in COMPANY_RATIONALE_INSTRUCTIONS.lower()
    assert "first principles" in COMPANY_RATIONALE_INSTRUCTIONS.lower()


def test_build_sector_tool_cascade_constrains_parent_sector_enum():
    tool = build_sector_tool(cascade=True, valid_parents=["banking", "auto"])
    parent_enum = tool["function"]["parameters"]["properties"]["sectors"]["items"]["properties"]["parent_sector"]["enum"]
    assert parent_enum == ["banking", "auto"]
    required = tool["function"]["parameters"]["properties"]["sectors"]["items"]["required"]
    assert "parent_sector" in required


def test_build_sector_tool_primary_has_no_parent_sector_field():
    tool = build_sector_tool(cascade=False, valid_parents=None)
    properties = tool["function"]["parameters"]["properties"]["sectors"]["items"]["properties"]
    assert "parent_sector" not in properties


_BANKING_SECTOR = SectorFinding(sector="banking", direction="bearish", mechanism="FX exposure on the rupee's fall.")

_FULL_COMPANY_FIELDS = {
    "name": "HDFC Bank", "ticker": "HDFCBANK.NS", "direction": "bearish",
    "magnitude_low": 1.0, "magnitude_high": 2.0,
    "rationale": "Large forex book takes a mark-to-market hit as the rupee weakens.",
    "key_points": ["The rupee falling means HDFC Bank's dollar-denominated liabilities cost more in rupee terms."],
    "time_horizon": "Short-Term",
    "reasons": ["Forex mark-to-market loss on rupee depreciation."],
    "evidence_refs": ["article: rupee fell 2% today"],
    "risks": ["Rupee could recover quickly."],
    "assumptions": ["No RBI intervention in the next week."],
    "unknowns": ["Size of HDFC Bank's unhedged forex book."],
    "alternative_hypothesis": "A weaker rupee could also boost NRI deposit inflows, offsetting the forex loss.",
}


def test_identify_companies_direct_stage_sets_impact_level_and_sector():
    client = ScriptedClient({
        "record_sector_companies": {"sector_companies": [
            {"sector": "banking", "companies": [_FULL_COMPANY_FIELDS]},
        ]},
    })

    result = _identify_companies(client, facts="f", sectors=[_BANKING_SECTOR], impact_level="direct", parent_pool=None)

    assert len(result) == 1
    company = result[0]
    assert company.ticker == "HDFCBANK.NS"
    assert company.is_direct is True
    assert company.sector == "banking"
    assert company.impact_level == "direct"
    assert company.parent_ticker is None
    assert company.rationale == _FULL_COMPANY_FIELDS["rationale"]
    assert company.reasons == _FULL_COMPANY_FIELDS["reasons"]
    assert company.evidence_refs == _FULL_COMPANY_FIELDS["evidence_refs"]
    assert company.alternative_hypothesis == _FULL_COMPANY_FIELDS["alternative_hypothesis"]


def test_company_framings_ask_for_breadth_and_no_longer_cap_at_three():
    # The correction that overshot: the cascade framing used to tell the
    # model that naming "1-3 real companies per sector" was the normal,
    # expected outcome, which capped a 737 MAX story at three companies
    # total. Both stages now carry the same breadth instruction.
    from app.analysis.cascade import _BREADTH_INSTRUCTION

    client = ScriptedClient({"record_sector_companies": {"sector_companies": []}})
    _identify_companies(client, facts="f", sectors=[_BANKING_SECTOR], impact_level="direct", parent_pool=None)
    direct_prompt = client.last_messages[1]["content"]

    parent_pool = [CompanyMention(
        name="HDFC Bank", ticker="HDFCBANK.NS", is_direct=True, direction="bearish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", time_horizon="Short-Term",
        impact_level="direct",
    )]
    client = ScriptedClient({"record_sector_companies": {"sector_companies": []}})
    _identify_companies(
        client, facts="f", sectors=[_BANKING_SECTOR], impact_level="indirect_l1", parent_pool=parent_pool,
    )
    cascade_prompt = client.last_messages[1]["content"]

    for prompt in (direct_prompt, cascade_prompt):
        assert _BREADTH_INSTRUCTION in prompt
        assert "1-3 real companies per sector" not in prompt
    assert "Five, ten, " in _BREADTH_INSTRUCTION
    assert "component suppliers" in _BREADTH_INSTRUCTION


def test_breadth_instruction_still_forbids_inventing_and_size_reasoning():
    # Breadth must come from selecting more REAL candidates, never from
    # size-ranked fan-out -- that is what put a food-delivery company on a
    # crude-oil story.
    from app.analysis.cascade import _BREADTH_INSTRUCTION

    assert "cannot record one that is not" in _BREADTH_INSTRUCTION
    assert "still forbidden is inventing" in _BREADTH_INSTRUCTION
    assert "major player in this sector" in _BREADTH_INSTRUCTION


def test_identify_companies_returns_many_companies_for_one_sector(db_session):
    # The product requirement, asserted end-to-end on the stage: nothing in
    # parsing, grounding, or the post-filter caps how many companies come
    # back from a single sector.
    tickers = [f"AERO{i:02d}.NS" for i in range(12)]
    for ticker in tickers:
        db_session.add(Company(
            ticker=ticker, name=f"Aero Supplier {ticker}", sector="defense", index_tier="OTHER",
        ))
    db_session.commit()

    client = ScriptedClient({"record_sector_companies": {"sector_companies": [{
        "sector": "defense",
        "companies": [_full_company(f"Aero Supplier {t}", t) for t in tickers],
    }]}})

    mentions = _identify_companies(
        client, facts="facts",
        sectors=[SectorFinding(sector="defense", direction="bullish", mechanism="m")],
        impact_level="direct", parent_pool=None, session=db_session,
    )

    assert [m.ticker for m in mentions] == tickers
    assert all(m.impact_level == "direct" for m in mentions)


def test_identify_companies_cascade_stage_requires_and_sets_parent_ticker():
    parent_pool = [CompanyMention(
        name="HDFC Bank", ticker="HDFCBANK.NS", is_direct=True, direction="bearish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", time_horizon="Short-Term",
        impact_level="direct",
    )]
    cascade_fields = dict(_FULL_COMPANY_FIELDS, name="IRCTC", ticker="IRCTC.NS", parent_ticker="HDFCBANK.NS")
    client = ScriptedClient({
        "record_sector_companies": {"sector_companies": [
            {"sector": "railways_transport", "companies": [cascade_fields]},
        ]},
    })

    result = _identify_companies(
        client, facts="f", sectors=[_BANKING_SECTOR], impact_level="indirect_l1", parent_pool=parent_pool,
    )

    assert result[0].impact_level == "indirect_l1"
    assert result[0].parent_ticker == "HDFCBANK.NS"


def test_identify_companies_direct_stage_calls_primary_model():
    from app.analysis.claude_client import MODEL

    client = ScriptedClient({"record_sector_companies": {"sector_companies": []}})

    _identify_companies(client, facts="f", sectors=[_BANKING_SECTOR], impact_level="direct", parent_pool=None)

    assert client.calls == [{"name": "record_sector_companies", "model": MODEL}]


def test_identify_companies_falls_back_to_secondary_model_on_rate_limit():
    from app.analysis.claude_client import FALLBACK_MODEL, MODEL

    class RateLimitOnceThenScripted(ScriptedClient):
        class _Completions(ScriptedClient._Completions):
            def create(self, **kwargs):
                if kwargs["model"] == MODEL:
                    from openai import RateLimitError
                    import httpx
                    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
                    response = httpx.Response(status_code=429, request=request)
                    self._outer.calls.append({"name": kwargs["tool_choice"]["function"]["name"], "model": kwargs["model"]})
                    raise RateLimitError("rate limited", response=response, body=None)
                return super().create(**kwargs)

        @property
        def chat(self):
            return SimpleNamespace(completions=self._Completions(self))

    client = RateLimitOnceThenScripted({"record_sector_companies": {"sector_companies": []}})

    _identify_companies(client, facts="f", sectors=[_BANKING_SECTOR], impact_level="direct", parent_pool=None)

    assert client.calls == [
        {"name": "record_sector_companies", "model": MODEL},
        {"name": "record_sector_companies", "model": FALLBACK_MODEL},
    ]


def test_identify_companies_falls_back_to_secondary_model_on_tool_use_failed():
    # Live production failure: the slim retry stayed on the primary model
    # and Groq returned 400 tool_use_failed (a malformed llama-style
    # function-call blob it couldn't parse) -- distinct from a rate limit,
    # this must ALSO trigger the FALLBACK_MODEL retry rather than losing
    # the whole stage.
    from app.analysis.claude_client import FALLBACK_MODEL, MODEL

    class ToolUseFailedOnceThenScripted(ScriptedClient):
        class _Completions(ScriptedClient._Completions):
            def create(self, **kwargs):
                if kwargs["model"] == MODEL:
                    self._outer.calls.append({"name": kwargs["tool_choice"]["function"]["name"], "model": kwargs["model"]})
                    raise _tool_use_failed_error()
                return super().create(**kwargs)

        @property
        def chat(self):
            return SimpleNamespace(completions=self._Completions(self))

    company_fields = dict(_FULL_COMPANY_FIELDS, name="HDFC Bank", ticker="HDFCBANK.NS")
    client = ToolUseFailedOnceThenScripted({
        "record_sector_companies": {"sector_companies": [
            {"sector": "banking", "companies": [company_fields]},
        ]},
    })

    result = _identify_companies(client, facts="f", sectors=[_BANKING_SECTOR], impact_level="direct", parent_pool=None)

    assert len(result) == 1
    assert result[0].ticker == "HDFCBANK.NS"
    assert client.calls == [
        {"name": "record_sector_companies", "model": MODEL},
        {"name": "record_sector_companies", "model": FALLBACK_MODEL},
    ]


def test_identify_companies_cascade_stage_falls_back_to_secondary_model_on_tool_use_failed():
    # Same tool_use_failed -> FALLBACK_MODEL ladder must apply to a cascade
    # stage (parent_pool set), not just the direct stage.
    from app.analysis.claude_client import FALLBACK_MODEL, MODEL

    class ToolUseFailedOnceThenScripted(ScriptedClient):
        class _Completions(ScriptedClient._Completions):
            def create(self, **kwargs):
                if kwargs["model"] == MODEL:
                    self._outer.calls.append({"name": kwargs["tool_choice"]["function"]["name"], "model": kwargs["model"]})
                    raise _tool_use_failed_error()
                return super().create(**kwargs)

        @property
        def chat(self):
            return SimpleNamespace(completions=self._Completions(self))

    parent_pool = [CompanyMention(
        name="HDFC Bank", ticker="HDFCBANK.NS", is_direct=True, direction="bearish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", time_horizon="Short-Term",
        impact_level="direct",
    )]
    cascade_fields = dict(_FULL_COMPANY_FIELDS, name="IRCTC", ticker="IRCTC.NS", parent_ticker="HDFCBANK.NS")
    client = ToolUseFailedOnceThenScripted({
        "record_sector_companies": {"sector_companies": [
            {"sector": "railways_transport", "companies": [cascade_fields]},
        ]},
    })

    result = _identify_companies(
        client, facts="f", sectors=[_BANKING_SECTOR], impact_level="indirect_l1", parent_pool=parent_pool,
    )

    assert result[0].ticker == "IRCTC.NS"
    assert client.calls == [
        {"name": "record_sector_companies", "model": MODEL},
        {"name": "record_sector_companies", "model": FALLBACK_MODEL},
    ]


def test_identify_companies_raises_when_both_models_fail_tool_use_failed():
    # Must NOT silently degrade to an empty company list -- that would be
    # indistinguishable from "genuinely no companies found". A failure on
    # BOTH models is a real failure and must propagate.
    class AlwaysToolUseFailedClient(ScriptedClient):
        class _Completions(ScriptedClient._Completions):
            def create(self, **kwargs):
                self._outer.calls.append({"name": kwargs["tool_choice"]["function"]["name"], "model": kwargs["model"]})
                raise _tool_use_failed_error()

        @property
        def chat(self):
            return SimpleNamespace(completions=self._Completions(self))

    from openai import BadRequestError

    client = AlwaysToolUseFailedClient({})

    with pytest.raises(BadRequestError):
        _identify_companies(client, facts="f", sectors=[_BANKING_SECTOR], impact_level="direct", parent_pool=None)


def test_identify_companies_cascade_stage_raises_when_both_models_fail_tool_use_failed():
    class AlwaysToolUseFailedClient(ScriptedClient):
        class _Completions(ScriptedClient._Completions):
            def create(self, **kwargs):
                self._outer.calls.append({"name": kwargs["tool_choice"]["function"]["name"], "model": kwargs["model"]})
                raise _tool_use_failed_error()

        @property
        def chat(self):
            return SimpleNamespace(completions=self._Completions(self))

    from openai import BadRequestError

    parent_pool = [CompanyMention(
        name="HDFC Bank", ticker="HDFCBANK.NS", is_direct=True, direction="bearish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", time_horizon="Short-Term",
        impact_level="direct",
    )]
    client = AlwaysToolUseFailedClient({})

    with pytest.raises(BadRequestError):
        _identify_companies(
            client, facts="f", sectors=[_BANKING_SECTOR], impact_level="indirect_l1", parent_pool=parent_pool,
        )

    # Cascade stage never gets the slim retry -- exactly two calls (primary
    # then FALLBACK_MODEL), not four.
    assert len(client.calls) == 2


def test_identify_companies_does_not_retry_on_a_different_bad_request_error():
    # A genuinely malformed schema on our side would also 400 -- must NOT be
    # mistaken for tool_use_failed and must NOT trigger the FALLBACK_MODEL
    # retry, so a real bug surfaces immediately instead of being masked.
    import httpx
    from openai import BadRequestError

    class OtherBadRequestClient(ScriptedClient):
        class _Completions(ScriptedClient._Completions):
            def create(self, **kwargs):
                self._outer.calls.append({"name": kwargs["tool_choice"]["function"]["name"], "model": kwargs["model"]})
                request = httpx.Request("POST", "https://example.test/v1/chat/completions")
                response = httpx.Response(status_code=400, request=request)
                raise BadRequestError(
                    "bad schema", response=response,
                    body={"code": "invalid_request_error", "message": "schema mismatch"},
                )

        @property
        def chat(self):
            return SimpleNamespace(completions=self._Completions(self))

    parent_pool = [CompanyMention(
        name="HDFC Bank", ticker="HDFCBANK.NS", is_direct=True, direction="bearish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", time_horizon="Short-Term",
        impact_level="direct",
    )]
    client = OtherBadRequestClient({})

    with pytest.raises(BadRequestError):
        _identify_companies(
            client, facts="f", sectors=[_BANKING_SECTOR], impact_level="indirect_l1", parent_pool=parent_pool,
        )

    # Only ONE call -- no FALLBACK_MODEL retry for a non-tool_use_failed 400.
    assert len(client.calls) == 1


def test_identify_companies_direct_stage_retries_slim_on_oversize_rejection():
    # Simulates Groq's per-request token cap (observed live as 413 "Request
    # too large"): any prompt carrying the full rulebook block is rejected,
    # the slim retry (no rulebook) succeeds. The direct stage must recover
    # instead of losing every direct company.
    class OversizeRejectingClient(ScriptedClient):
        class _Completions(ScriptedClient._Completions):
            def create(self, **kwargs):
                content = kwargs["messages"][1]["content"]
                if "ECONOMIC REASONING RULES" in content:
                    self._outer.calls.append({
                        "name": kwargs["tool_choice"]["function"]["name"],
                        "model": kwargs["model"],
                    })
                    raise RuntimeError("Request too large (simulated 413)")
                return super().create(**kwargs)

        @property
        def chat(self):
            return SimpleNamespace(completions=self._Completions(self))

    company_fields = dict(_FULL_COMPANY_FIELDS, name="HDFC Bank", ticker="HDFCBANK.NS")
    client = OversizeRejectingClient({
        "record_sector_companies": {"sector_companies": [
            {"sector": "banking", "companies": [company_fields]},
        ]},
    })

    result = _identify_companies(client, facts="f", sectors=[_BANKING_SECTOR], impact_level="direct", parent_pool=None)

    assert len(result) == 1
    assert result[0].ticker == "HDFCBANK.NS"
    # First call carried the rulebook and was rejected; the retry was slim.
    assert len(client.calls) == 2
    assert "ECONOMIC REASONING RULES" not in client.last_messages[1]["content"]


def test_identify_companies_cascade_stage_does_not_retry_slim():
    # The slim retry exists only for the direct stage's oversized prompt --
    # a cascade-stage failure must propagate to analyze_article's own
    # truncation handling, not silently re-call the model.
    class AlwaysFailingClient(ScriptedClient):
        class _Completions(ScriptedClient._Completions):
            def create(self, **kwargs):
                raise RuntimeError("provider down")

        @property
        def chat(self):
            return SimpleNamespace(completions=self._Completions(self))

    parent_pool = [CompanyMention(
        name="HDFC Bank", ticker="HDFCBANK.NS", is_direct=True, direction="bearish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", time_horizon="Short-Term",
        impact_level="direct",
    )]
    client = AlwaysFailingClient({})

    with pytest.raises(RuntimeError, match="provider down"):
        _identify_companies(
            client, facts="f", sectors=[_BANKING_SECTOR], impact_level="indirect_l1", parent_pool=parent_pool,
        )


def test_build_company_tool_cascade_constrains_parent_ticker_enum():
    tool = build_company_tool(parent_tickers=["HDFCBANK.NS"])
    props = tool["function"]["parameters"]["properties"]["sector_companies"]["items"]["properties"]["companies"]["items"]["properties"]
    assert props["parent_ticker"]["enum"] == ["HDFCBANK.NS"]


def test_build_company_tool_direct_has_no_parent_ticker_field():
    tool = build_company_tool(parent_tickers=None)
    props = tool["function"]["parameters"]["properties"]["sector_companies"]["items"]["properties"]["companies"]["items"]["properties"]
    assert "parent_ticker" not in props


def test_company_rationale_instructions_contains_rulebook_and_playbook_content():
    # ARPU appears only in the telecom playbook entry (verified absent from
    # RULEBOOK_TEXT and SECTOR_DEFINITIONS) -- a real, specific probe that
    # would catch a dropped PLAYBOOKS_TEXT interpolation.
    from app.analysis.cascade import COMPANY_RATIONALE_INSTRUCTIONS
    assert "RULE_CRUDE_OIL_UP" in COMPANY_RATIONALE_INSTRUCTIONS
    assert "ARPU" in COMPANY_RATIONALE_INSTRUCTIONS


def _full_company(name, ticker, parent_ticker=None):
    fields = dict(_FULL_COMPANY_FIELDS, name=name, ticker=ticker)
    if parent_ticker:
        fields["parent_ticker"] = parent_ticker
    return fields


class PerSectorScriptedClient:
    """Returns one scripted response per call, keyed by call order --
    unlike ScriptedClient (one fixed response per tool name), this lets a
    test give each of several same-tool-name calls its own distinct
    response, proving _identify_cascade_companies_per_sector makes one
    real call per sector rather than bundling them."""

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls = []

    class _Completions:
        def __init__(self, outer):
            self._outer = outer

        def create(self, **kwargs):
            name = kwargs["tool_choice"]["function"]["name"]
            self._outer.calls.append(name)
            response = self._outer._responses.pop(0)
            if isinstance(response, Exception):
                raise response
            message = SimpleNamespace(tool_calls=[FakeToolCall(name, response)])
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    @property
    def chat(self):
        return SimpleNamespace(completions=self._Completions(self))


def test_identify_cascade_companies_per_sector_makes_one_call_per_sector():
    banking = SectorFinding(sector="banking", direction="bearish", mechanism="m", parent_sector="oil_gas")
    auto = SectorFinding(sector="auto", direction="bearish", mechanism="m", parent_sector="oil_gas")
    parent_pool = [CompanyMention(
        name="Reliance", ticker="RELIANCE.NS", is_direct=True, direction="bearish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", time_horizon="Short-Term",
        impact_level="direct",
    )]
    client = PerSectorScriptedClient([
        {"sector_companies": [{"sector": "banking", "companies": [_full_company("HDFC Bank", "HDFCBANK.NS", parent_ticker="RELIANCE.NS")]}]},
        {"sector_companies": [{"sector": "auto", "companies": [_full_company("Maruti", "MARUTI.NS", parent_ticker="RELIANCE.NS")]}]},
    ])

    result, gaps = _identify_cascade_companies_per_sector(
        client, facts="f", sectors=[banking, auto], impact_level="indirect_l1", parent_pool=parent_pool,
    )

    assert client.calls == ["record_sector_companies", "record_sector_companies"]
    assert {c.ticker for c in result} == {"HDFCBANK.NS", "MARUTI.NS"}
    assert all(c.impact_level == "indirect_l1" for c in result)
    assert gaps == []


def test_identify_cascade_companies_per_sector_skips_a_failing_sector_not_the_others():
    banking = SectorFinding(sector="banking", direction="bearish", mechanism="m", parent_sector="oil_gas")
    auto = SectorFinding(sector="auto", direction="bearish", mechanism="m", parent_sector="oil_gas")
    parent_pool = [CompanyMention(
        name="Reliance", ticker="RELIANCE.NS", is_direct=True, direction="bearish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", time_horizon="Short-Term",
        impact_level="direct",
    )]
    client = PerSectorScriptedClient([
        ValueError("boom"),
        ValueError("boom again"),  # banking's retry attempt also fails
        {"sector_companies": [{"sector": "auto", "companies": [_full_company("Maruti", "MARUTI.NS", parent_ticker="RELIANCE.NS")]}]},
    ])

    result, gaps = _identify_cascade_companies_per_sector(
        client, facts="f", sectors=[banking, auto], impact_level="indirect_l1", parent_pool=parent_pool,
    )

    assert [c.ticker for c in result] == ["MARUTI.NS"]
    assert len(gaps) == 1
    assert gaps[0]["sector"] == "banking"
    assert gaps[0]["attempts"] == 2


def test_identify_cascade_companies_per_sector_retries_then_records_gap():
    sectors = [
        SectorFinding(sector="banking", direction="bullish", mechanism="m1", parent_sector="oil_gas"),
        SectorFinding(sector="auto", direction="bullish", mechanism="m2", parent_sector="oil_gas"),
    ]
    parent_pool = [CompanyMention(
        name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", time_horizon="Short-Term",
    )]

    call_log = []

    class FlakyThenGoodClient:
        @property
        def chat(self):
            return SimpleNamespace(completions=self)

        def create(self, **kwargs):
            # Which sector this call is for isn't directly inspectable from
            # kwargs (the tool schema doesn't echo it back); key off call
            # order instead -- sectors are processed in list order (banking,
            # then auto), and each sector gets up to 2 attempts, so calls
            # 1-2 are banking's two attempts (both fail) and call 3 is
            # auto's first attempt (succeeds).
            call_log.append(kwargs["tool_choice"]["function"]["name"])
            if len(call_log) <= 2:
                raise RuntimeError("transient failure")
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                tool_calls=[FakeToolCall("record_sector_companies", {"sector_companies": [
                    {"sector": "auto", "companies": [{
                        "name": "Maruti Suzuki", "ticker": "MARUTI.NS", "direction": "bullish",
                        "magnitude_low": 1.0, "magnitude_high": 2.0, "rationale": "r",
                        "key_points": [], "time_horizon": "Short-Term", "reasons": [],
                        "evidence_refs": [], "risks": [], "assumptions": [], "unknowns": [],
                        "alternative_hypothesis": "none", "parent_ticker": "RELIANCE.NS",
                    }]},
                ]})],
            ))])

    mentions, gaps = _identify_cascade_companies_per_sector(
        FlakyThenGoodClient(), facts="f", sectors=sectors, impact_level="indirect_l1", parent_pool=parent_pool,
    )

    assert len(gaps) == 1
    assert gaps[0]["sector"] == "banking"
    assert gaps[0]["impact_level"] == "indirect_l1"
    assert gaps[0]["attempts"] == 2
    assert gaps[0]["last_error"]
    assert len(mentions) == 1
    assert mentions[0].ticker == "MARUTI.NS"  # the "auto" sector still succeeded


def test_analyze_article_composes_all_seven_stages_end_to_end():
    # Sector/company stages are called multiple times with the same tool
    # name in one run (stage 2 vs 4 vs 6 all call record_sectors; stage 3
    # vs 5 vs 7 all call record_sector_companies) -- ScriptedClient as built
    # in Task 3 only supports ONE canned response per tool name. Use a
    # call-count-based variant here instead.
    class MultiStageClient:
        def __init__(self):
            self.calls = []
            self._sector_responses = [
                {"sectors": [{"sector": "banking", "direction": "bearish", "mechanism": "FX exposure."}]},
                {"sectors": [{
                    "sector": "railways_transport", "direction": "bearish",
                    "mechanism": "Import costs rise.", "parent_sector": "banking",
                }]},
                {"sectors": []},  # no hop-2 sectors found -- stops the chain
            ]
            self._company_responses = [
                {"sector_companies": [{"sector": "banking", "companies": [_full_company("HDFC Bank", "HDFCBANK.NS")]}]},
                {"sector_companies": [{
                    "sector": "railways_transport",
                    "companies": [_full_company("IRCTC", "IRCTC.NS", parent_ticker="HDFCBANK.NS")],
                }]},
            ]
            self._sector_call_count = 0
            self._company_call_count = 0

        class _Completions:
            def __init__(self, outer):
                self._outer = outer

            def create(self, **kwargs):
                name = kwargs["tool_choice"]["function"]["name"]
                self._outer.calls.append(name)
                if name == "record_facts":
                    response = {"facts": "The rupee fell 2% today.", "category": "macro_policy", "event_type": "currency_move"}
                elif name == "record_sectors":
                    response = self._outer._sector_responses[self._outer._sector_call_count]
                    self._outer._sector_call_count += 1
                elif name == "record_sector_companies":
                    response = self._outer._company_responses[self._outer._company_call_count]
                    self._outer._company_call_count += 1
                elif name == "record_company_verdicts":
                    # Verification stage (app.analysis.verification) runs
                    # once over the whole assembled company list, after every
                    # generative stage and before edges -- not itself under
                    # test here, just needs a well-formed response (every
                    # company kept) so this end-to-end test isn't coupled to
                    # verification behavior.
                    tickers = kwargs["tools"][0]["function"]["parameters"]["properties"]["verdicts"]["items"]["properties"]["ticker"]["enum"]
                    response = {"verdicts": [{"ticker": t, "belongs": True} for t in tickers]}
                elif name == "record_edge_verification":
                    # currency_move has a CHAINS entry, so analyze_article's
                    # final stage (_generate_edges) makes one verification
                    # call -- not itself under test here, just needs a
                    # well-formed response so this end-to-end test isn't
                    # coupled to edge-verification behavior.
                    from app.reasoning.rulebook import CHAINS
                    response = {
                        "verifications": [
                            {"index": i, "applicable": True} for i in range(len(CHAINS["currency_move"]))
                        ],
                        "llm_only_edges": [],
                    }
                else:
                    raise AssertionError(f"unexpected tool: {name}")
                message = SimpleNamespace(tool_calls=[FakeToolCall(name, response)])
                return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        @property
        def chat(self):
            return SimpleNamespace(completions=self._Completions(self))

    client = MultiStageClient()

    result = analyze_article(client, title="Rupee falls sharply", content="The rupee weakened 2% today.")

    assert result.category == "macro_policy"
    assert result.event_type == "currency_move"
    # 3, not 4: the deterministic sector-wide fan-out now only fires at the
    # primary level -- both cascade fan-out call sites (L1/L2) were deleted
    # entirely (Task 11), so the L1 cascade sector (railways_transport) gets
    # no sector-wide mention of its own, only the LLM-named cascade company.
    assert len(result.companies) == 3
    direct, sector_wide, cascade = result.companies
    assert direct.ticker == "HDFCBANK.NS"
    assert direct.impact_level == "direct"
    assert direct.parent_ticker is None
    # One deterministic sector-wide fan-out mention per primary sector (here
    # just "banking") -- lets resolve_companies's top-N-by-tier lookup add
    # this sector's other real companies regardless of what the LLM named.
    # currency_move is a BROAD_EVENT_TYPES member, so the gate lets it fire.
    assert sector_wide.is_direct is False
    assert sector_wide.sector == "banking"
    assert sector_wide.direction == "bearish"
    assert sector_wide.impact_level == "direct"
    assert cascade.ticker == "IRCTC.NS"
    assert cascade.impact_level == "indirect_l1"
    assert cascade.parent_ticker == "HDFCBANK.NS"
    # 8 calls: facts, primary sectors, primary companies, L1 sectors, L1
    # companies, L2 sectors -- the L2-sector call DOES run (L1 sectors and
    # L1 companies-with-tickers are both non-empty, so the orchestrator's
    # guards let it through), but it returns zero L2 sectors, so stage 7
    # (L2 companies) never runs -- then one company-verification call (see
    # app.analysis.verification) and finally one edge-verification call
    # (currency_move has a CHAINS entry) before edges are returned.
    assert client.calls == [
        "record_facts", "record_sectors", "record_sector_companies",
        "record_sectors", "record_sector_companies", "record_sectors",
        "record_company_verdicts", "record_edge_verification",
    ]
    # Both real sectors found across the run (banking primary, railways_transport
    # L1) get their own news->sector mechanism edge, carrying the actual
    # per-article reasoning text from the scripted record_sectors responses.
    mechanism_edges = {e["to"]["label"]: e for e in result.edges if e["from"]["label"] == "news" and e["to"]["kind"] == "sector"}
    assert mechanism_edges["banking"]["note"] == "FX exposure."
    assert mechanism_edges["railways_transport"]["note"] == "Import costs rise."


def test_analyze_article_propagates_facts_stage_failure():
    client = ScriptedClient({"record_facts": ValueError("boom")})

    with pytest.raises(ValueError, match="boom"):
        analyze_article(client, title="t", content="c")


def test_analyze_article_propagates_primary_sector_stage_failure():
    client = ScriptedClient({
        "record_facts": {"facts": "f", "category": "other", "event_type": "other"},
        "record_sectors": ValueError("boom"),
    })

    with pytest.raises(ValueError, match="boom"):
        analyze_article(client, title="t", content="c")


def test_analyze_article_truncates_and_returns_direct_companies_when_primary_company_stage_fails():
    # event_type must be a BROAD_EVENT_TYPES member for the deterministic
    # fan-out to fire at all (see test_broad_event_types_include_rate_and_
    # commodity_moves) -- "repo_rate_change" here, not "other".
    client = ScriptedClient({
        "record_facts": {"facts": "f", "category": "other", "event_type": "repo_rate_change"},
        "record_sectors": {"sectors": [{"sector": "banking", "direction": "bearish", "mechanism": "m"}]},
        "record_sector_companies": ValueError("boom"),
    })

    result = analyze_article(client, title="t", content="c")

    # The LLM's own per-company call failed, but the deterministic
    # sector-wide fan-out mention (built from the already-succeeded primary
    # sector, not from this failed call) still comes through -- a resilience
    # side effect: this alert still resolves to real companies via
    # resolve_companies's top-N-by-tier lookup instead of zero.
    assert len(result.companies) == 1
    assert result.companies[0].is_direct is False
    assert result.companies[0].sector == "banking"


def test_sector_fanout_mentions_builds_one_per_sector_with_impact_level():
    # parent_ticker was removed as a dead parameter -- the L1/L2 cascade call
    # sites that used to pass it were deleted, and the sole remaining caller
    # (analyze_article, at the primary/direct level only) never does.
    sectors = [
        SectorFinding(sector="auto", direction="bearish", mechanism="input cost pass-through"),
        SectorFinding(sector="metals", direction="bullish", mechanism="commodity price rise"),
    ]

    mentions = _sector_fanout_mentions(sectors, impact_level="indirect_l2")

    assert len(mentions) == 2
    assert all(m.is_direct is False for m in mentions)
    assert all(m.impact_level == "indirect_l2" for m in mentions)
    assert all(m.parent_ticker is None for m in mentions)
    assert {m.sector for m in mentions} == {"auto", "metals"}
    assert {m.direction for m in mentions} == {"bearish", "bullish"}


def test_sector_fanout_mentions_direct_stage_has_no_parent_ticker():
    sectors = [SectorFinding(sector="banking", direction="bearish", mechanism="rate exposure")]

    mentions = _sector_fanout_mentions(sectors, impact_level="direct")

    assert mentions[0].parent_ticker is None
    assert mentions[0].impact_level == "direct"


def test_analyze_article_adds_one_sector_wide_mention_per_primary_sector():
    # Two primary sectors, one LLM-named direct company (in "banking" only)
    # -- the "oil_gas" sector never got a specific company named by the LLM
    # at all, the exact production symptom this fan-out fixes. No ticker on
    # the named company so the L1/L2 cascade stages never trigger (keeps
    # this test scoped to stage 3's own output, not the whole 7-stage chain
    # -- see test_analyze_article_composes_all_seven_stages_end_to_end for
    # that). event_type must be a BROAD_EVENT_TYPES member for fan-out to
    # fire at all -- "crude_oil" here, not "other".
    client = ScriptedClient({
        "record_facts": {"facts": "f", "category": "other", "event_type": "crude_oil"},
        "record_sectors": {"sectors": [
            {"sector": "banking", "direction": "bearish", "mechanism": "rate exposure"},
            {"sector": "oil_gas", "direction": "bullish", "mechanism": "crude price pass-through"},
        ]},
        "record_sector_companies": {"sector_companies": [
            {"sector": "banking", "companies": [_full_company("HDFC Bank", None)]},
        ]},
    })

    result = analyze_article(client, title="t", content="c")

    named = [c for c in result.companies if c.name == "HDFC Bank"]
    sector_wide = [c for c in result.companies if c.is_direct is False]
    assert len(named) == 1
    assert len(sector_wide) == 2
    by_sector = {c.sector: c for c in sector_wide}
    assert by_sector["banking"].direction == "bearish"
    assert by_sector["oil_gas"].direction == "bullish"
    assert all(c.impact_level == "direct" for c in sector_wide)
    assert all(c.ticker is None for c in sector_wide)


def test_analyze_article_skips_fanout_for_a_narrow_event_type():
    # Same setup as test_analyze_article_adds_one_sector_wide_mention_per_
    # primary_sector (two primary sectors, one LLM-named direct company in
    # "banking" only, "oil_gas" left with no specific company) -- but
    # event_type is "earnings", a NARROW event NOT in BROAD_EVENT_TYPES.
    # This directly proves the gate is wired into the call site itself, not
    # just that BROAD_EVENT_TYPES contains the right strings in isolation --
    # the two "other"-event tests elsewhere in this file don't assert
    # company composition, so they'd pass identically whether the gate
    # existed or not.
    client = ScriptedClient({
        "record_facts": {"facts": "f", "category": "other", "event_type": "earnings"},
        "record_sectors": {"sectors": [
            {"sector": "banking", "direction": "bearish", "mechanism": "rate exposure"},
            {"sector": "oil_gas", "direction": "bullish", "mechanism": "crude price pass-through"},
        ]},
        "record_sector_companies": {"sector_companies": [
            {"sector": "banking", "companies": [_full_company("HDFC Bank", None)]},
        ]},
    })

    result = analyze_article(client, title="t", content="c")

    named = [c for c in result.companies if c.name == "HDFC Bank"]
    sector_wide = [c for c in result.companies if c.is_direct is False]
    assert len(named) == 1
    assert sector_wide == []


def test_analyze_article_logs_swallowed_stage_failures(caplog):
    import logging
    client = ScriptedClient({
        "record_facts": {"facts": "f", "category": "other", "event_type": "other"},
        "record_sectors": {"sectors": [{"sector": "banking", "direction": "bearish", "mechanism": "m"}]},
        "record_sector_companies": ValueError("boom"),
    })

    with caplog.at_level(logging.WARNING):
        analyze_article(client, title="t", content="c")

    assert any("boom" in record.message for record in caplog.records)


def test_analyze_article_stops_cascade_when_primary_sectors_are_empty():
    client = ScriptedClient({
        "record_facts": {"facts": "f", "category": "other", "event_type": "other"},
        "record_sectors": {"sectors": []},
    })

    result = analyze_article(client, title="t", content="c")

    assert result.companies == []
    # No company stage should have run at all -- nothing to find companies
    # within when there are zero primary sectors.
    assert [c["name"] for c in client.calls] == ["record_facts", "record_sectors"]


def test_generate_edges_keeps_a_pruned_edge():
    proposed = CHAINS["repo_rate_change"]  # real chain, 6 edges, from Phase 2

    verifications = [{"index": 0, "applicable": False, "pruned_reason": "no lending angle in this specific article"}]
    verifications += [{"index": i, "applicable": True} for i in range(1, len(proposed))]

    client = ScriptedClient({
        "record_edge_verification": {"verifications": verifications, "llm_only_edges": []},
    })

    edges = _generate_edges(client, facts="Repo rate cut announced.", event_type="repo_rate_change", companies=[])

    pruned = [e for e in edges if e["source"] == "rulebook_pruned"]
    assert len(pruned) == 1
    assert pruned[0]["from"] == proposed[0]["from"]
    assert pruned[0]["to"] == proposed[0]["to"]
    assert "no lending angle in this specific article" in pruned[0]["note"]
    verified = [e for e in edges if e["source"] == "rulebook_verified"]
    assert len(verified) == len(proposed) - 1


def test_generate_edges_connects_every_company_to_its_sector():
    companies = [
        CompanyMention(
            name="HDFC Bank", ticker="HDFCBANK.NS", is_direct=True, sector="banking",
            direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="r", time_horizon="Short-Term",
        ),
        CompanyMention(
            name="Maruti Suzuki", ticker="MARUTI.NS", is_direct=False, sector="auto",
            direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="r", time_horizon="Short-Term",
            impact_level="indirect_l1",
        ),
    ]
    # earnings has no CHAINS entry -- no verify call should even be attempted.
    client = ScriptedClient({})

    edges = _generate_edges(client, facts="f", event_type="earnings", companies=companies)

    sector_edges = {e["to"]["label"]: e for e in edges if e["from"]["kind"] == "sector"}
    assert sector_edges["HDFCBANK.NS"]["from"]["label"] == "banking"
    assert sector_edges["HDFCBANK.NS"]["direction"] == "bullish"
    assert sector_edges["HDFCBANK.NS"]["source"] == "llm_only"
    assert sector_edges["MARUTI.NS"]["from"]["label"] == "auto"


def test_generate_edges_no_chain_event_type_produces_only_sector_attachment_edges():
    companies = [CompanyMention(
        name="Reliance", ticker="RELIANCE.NS", is_direct=True, sector="oil_gas",
        direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="r", time_horizon="Short-Term",
    )]
    client = ScriptedClient({})  # asserts nothing gets called -- earnings has no CHAINS entry

    edges = _generate_edges(client, facts="f", event_type="earnings", companies=companies)

    assert len(edges) == 1
    assert all(e["source"] == "llm_only" for e in edges)


def test_sector_mechanism_edges_carries_the_real_per_sector_mechanism_text():
    sectors = [
        SectorFinding(sector="banking", direction="bearish", mechanism="Higher funding costs squeeze NIMs."),
        SectorFinding(sector="auto", direction="bullish", mechanism="Cheaper credit lifts vehicle financing demand.", parent_sector="banking"),
    ]

    edges = _sector_mechanism_edges(sectors)

    assert len(edges) == 2
    by_sector = {e["to"]["label"]: e for e in edges}
    assert by_sector["banking"]["from"] == {"kind": "news", "label": "news"}
    assert by_sector["banking"]["to"] == {"kind": "sector", "label": "banking"}
    assert by_sector["banking"]["note"] == "Higher funding costs squeeze NIMs."
    assert by_sector["banking"]["direction"] == "bearish"
    assert by_sector["auto"]["note"] == "Cheaper credit lifts vehicle financing demand."


def test_sector_mechanism_edges_deduplicates_a_sector_named_at_multiple_stages():
    # A sector can legitimately be found both as primary AND later as an L1
    # ripple target (e.g. of a different primary sector) -- only its FIRST
    # (most direct) mechanism should end up on the node, not a second one.
    sectors = [
        SectorFinding(sector="banking", direction="bearish", mechanism="Primary-stage mechanism."),
        SectorFinding(sector="banking", direction="bearish", mechanism="L1-stage mechanism.", parent_sector="oil_gas"),
    ]

    edges = _sector_mechanism_edges(sectors)

    assert len(edges) == 1
    assert edges[0]["note"] == "Primary-stage mechanism."


def test_sector_mechanism_edges_empty_for_no_sectors():
    assert _sector_mechanism_edges([]) == []


def test_generate_edges_llm_only_company_edge_enum_constrained_to_resolved_tickers():
    companies = [
        CompanyMention(
            name="HDFC Bank", ticker="HDFCBANK.NS", is_direct=True, sector="banking",
            direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="r", time_horizon="Short-Term",
        ),
        CompanyMention(
            name="Maruti Suzuki", ticker="MARUTI.NS", is_direct=False, sector="auto",
            direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="r", time_horizon="Short-Term",
            impact_level="indirect_l1",
        ),
    ]
    proposed = CHAINS["repo_rate_change"]
    verifications = [{"index": i, "applicable": True} for i in range(len(proposed))]
    client = ScriptedClient({
        "record_edge_verification": {
            "verifications": verifications,
            "llm_only_edges": [{
                "from_ticker": "HDFCBANK.NS", "to_ticker": "MARUTI.NS", "relation": "credit_cost",
                "direction": "bullish", "note": "Auto financing flows through HDFC Bank's lending book.",
            }],
        },
    })

    edges = _generate_edges(client, facts="f", event_type="repo_rate_change", companies=companies)

    llm_company_edges = [
        e for e in edges
        if e["source"] == "llm_only" and e["from"]["kind"] == "company" and e["to"]["kind"] == "company"
    ]
    assert len(llm_company_edges) == 1
    assert llm_company_edges[0]["from"]["label"] == "HDFCBANK.NS"
    assert llm_company_edges[0]["to"]["label"] == "MARUTI.NS"

    # The tool schema actually sent must enum-constrain both ticker fields
    # to the resolved companies -- verify the real constraint was sent, not
    # just that the scripted response happened to be accepted.
    sent_tool = client.last_tool
    props = sent_tool["function"]["parameters"]["properties"]["llm_only_edges"]["items"]["properties"]
    assert set(props["from_ticker"]["enum"]) == {"HDFCBANK.NS", "MARUTI.NS"}
    assert set(props["to_ticker"]["enum"]) == {"HDFCBANK.NS", "MARUTI.NS"}


def test_generate_edges_verify_call_failure_falls_back_to_unverified_proposed_chain():
    proposed = CHAINS["crude_oil"]

    class FailingClient:
        @property
        def chat(self):
            return SimpleNamespace(completions=self)

        def create(self, **kwargs):
            raise RuntimeError("provider down")

    edges = _generate_edges(FailingClient(), facts="f", event_type="crude_oil", companies=[])

    rulebook_edges = [e for e in edges if e["source"] == "rulebook_verified"]
    assert len(rulebook_edges) == len(proposed)
    assert all("[UNVERIFIED" in e["note"] for e in rulebook_edges)


def test_generate_edges_verify_call_failure_drops_proposed_chain_for_heterogeneous_event_type():
    # commodity_price's canonical chain (Metal Prices) is not in
    # CHAIN_FALLBACK_KEEP_EVENT_TYPES -- it also covers gold/coal/agri news,
    # so an unverified chain risks charting the wrong subject entirely, not
    # just the wrong direction. On verify failure the proposed edges must
    # be dropped rather than kept as unverified.
    class FailingClient:
        @property
        def chat(self):
            return SimpleNamespace(completions=self)

        def create(self, **kwargs):
            raise RuntimeError("provider down")

    edges = _generate_edges(FailingClient(), facts="f", event_type="commodity_price", companies=[])

    rulebook_edges = [e for e in edges if e["source"] in ("rulebook_verified", "rulebook_pruned")]
    assert rulebook_edges == []


def test_generate_edges_missing_verification_for_one_index_kept_unverified_not_dropped():
    proposed = CHAINS["inflation"]
    # Verify every index except 1 -- index 1 is missing from the response entirely.
    client = ScriptedClient({
        "record_edge_verification": {
            "verifications": [
                {"index": i, "applicable": True}
                for i in range(len(proposed)) if i != 1
            ],
            "llm_only_edges": [],
        },
    })

    edges = _generate_edges(client, facts="f", event_type="inflation", companies=[])

    assert len(edges) == len(proposed)  # nothing silently dropped
    missing = [e for e in edges if "[UNVERIFIED" in e["note"]]
    assert len(missing) == 1
    assert missing[0]["from"] == proposed[1]["from"]


def test_company_tool_enum_constrains_ticker_to_candidates():
    tool = build_company_tool(None, valid_tickers=["HPCL.NS", "BPCL.NS"])
    ticker_schema = (
        tool["function"]["parameters"]["properties"]["sector_companies"]
        ["items"]["properties"]["companies"]["items"]["properties"]["ticker"]
    )
    assert ticker_schema["enum"] == ["HPCL.NS", "BPCL.NS"]


def test_company_tool_leaves_ticker_unconstrained_without_candidates():
    tool = build_company_tool(None)
    ticker_schema = (
        tool["function"]["parameters"]["properties"]["sector_companies"]
        ["items"]["properties"]["companies"]["items"]["properties"]["ticker"]
    )
    assert "enum" not in ticker_schema


def test_identify_companies_injects_candidates_into_the_prompt(db_session):
    db_session.add(Company(
        ticker="HPCL.NS", name="Hindustan Petroleum", sector="oil_gas",
        index_tier="NIFTY50", business_desc="Refines crude oil.",
    ))
    db_session.commit()

    client = ScriptedClient({"record_sector_companies": {"sector_companies": []}})
    _identify_companies(
        client, facts="facts", sectors=[SectorFinding(sector="oil_gas", direction="bullish", mechanism="m")],
        impact_level="direct", parent_pool=None, session=db_session,
    )

    prompt = client.last_messages[1]["content"]
    assert "HPCL.NS" in prompt
    assert "Refines crude oil." in prompt


def test_identify_companies_drops_a_ticker_outside_the_candidate_list(db_session):
    # Provider enums are not reliably enforced for nested array items
    # (cascade.py:282) -- the defensive post-filter must catch this rather
    # than let an invented ticker through to resolution.
    db_session.add(Company(
        ticker="HPCL.NS", name="Hindustan Petroleum", sector="oil_gas", index_tier="NIFTY50",
    ))
    db_session.commit()

    client = ScriptedClient({"record_sector_companies": {"sector_companies": [{
        "sector": "oil_gas",
        "companies": [
            _full_company("Hindustan Petroleum", "HPCL.NS"),
            _full_company("Invented Ltd.", "INVENTED.NS"),
        ],
    }]}})

    mentions = _identify_companies(
        client, facts="facts", sectors=[SectorFinding(sector="oil_gas", direction="bullish", mechanism="m")],
        impact_level="direct", parent_pool=None, session=db_session,
    )

    assert [m.ticker for m in mentions] == ["HPCL.NS"]


def test_identify_companies_without_a_session_stays_ungrounded(db_session):
    # db_session is seeded with nothing and passed nowhere here -- proves a
    # caller that omits `session` entirely (the default) gets the exact old,
    # unconstrained behavior even though a DB is available in-process.
    client = ScriptedClient({"record_sector_companies": {"sector_companies": [{
        "sector": "oil_gas",
        "companies": [_full_company("Anything Ltd.", "ANY.NS")],
    }]}})

    mentions = _identify_companies(
        client, facts="facts", sectors=[SectorFinding(sector="oil_gas", direction="bullish", mechanism="m")],
        impact_level="direct", parent_pool=None,
    )

    assert [m.ticker for m in mentions] == ["ANY.NS"]


def test_analyze_article_drops_a_company_verification_rejects(monkeypatch):
    import app.analysis.cascade as cascade_module

    monkeypatch.setattr(
        cascade_module, "verify_companies",
        lambda client, facts, title, companies: [c for c in companies if c.ticker != "BAD.NS"],
    )
    # ScriptedClient (defined above) keys its canned response by tool name,
    # not by call order -- reused for every subsequent call to the same
    # tool (e.g. the L1/L2 cascade sector and company stages that follow
    # the primary ones), which is fine here: event_type "other" has no
    # CHAINS entry, so _generate_edges never makes its own verify call, and
    # verify_companies itself is monkeypatched above rather than exercised
    # for real. The only thing under test is that analyze_article actually
    # calls (the monkeypatched) verify_companies and uses its result --
    # not the cascade's own sector/company reasoning.
    client = ScriptedClient({
        "record_facts": {"facts": "f", "category": "other", "event_type": "other"},
        "record_sectors": {"sectors": [{"sector": "banking", "direction": "bearish", "mechanism": "m"}]},
        "record_sector_companies": {"sector_companies": [{
            "sector": "banking",
            "companies": [
                _full_company("Good Ltd.", "GOOD.NS"),
                _full_company("Bad Ltd.", "BAD.NS"),
            ],
        }]},
    })

    result = analyze_article(client, title="t", content="c")

    tickers = [c.ticker for c in result.companies]
    assert "BAD.NS" not in tickers
    assert "GOOD.NS" in tickers


def test_broad_event_types_include_rate_and_commodity_moves():
    assert "repo_rate_change" in BROAD_EVENT_TYPES
    assert "crude_oil" in BROAD_EVENT_TYPES


def test_narrow_event_types_are_excluded():
    assert "earnings" not in BROAD_EVENT_TYPES
    assert "merger_acquisition" not in BROAD_EVENT_TYPES
    assert "order_win_contract" not in BROAD_EVENT_TYPES
