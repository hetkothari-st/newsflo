import json
from types import SimpleNamespace

import pytest

from app.analysis.cascade import analyze_article, _extract_facts, _identify_companies, _identify_sectors, build_company_tool, build_sector_tool
from app.analysis.schemas import CompanyMention, SectorFinding


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


def test_identify_sectors_calls_fallback_model_only():
    from app.analysis.claude_client import FALLBACK_MODEL

    client = ScriptedClient({"record_sectors": {"sectors": []}})

    _identify_sectors(client, facts="f", parent_sectors=None)

    assert client.calls == [{"name": "record_sectors", "model": FALLBACK_MODEL}]


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
    assert len(result.companies) == 2
    direct, cascade = result.companies
    assert direct.ticker == "HDFCBANK.NS"
    assert direct.impact_level == "direct"
    assert direct.parent_ticker is None
    assert cascade.ticker == "IRCTC.NS"
    assert cascade.impact_level == "indirect_l1"
    assert cascade.parent_ticker == "HDFCBANK.NS"
    # 6 calls: facts, primary sectors, primary companies, L1 sectors, L1
    # companies, L2 sectors -- the L2-sector call DOES run (L1 sectors and
    # L1 companies-with-tickers are both non-empty, so the orchestrator's
    # guards let it through), but it returns zero L2 sectors, so stage 7
    # (L2 companies) never runs.
    assert client.calls == [
        "record_facts", "record_sectors", "record_sector_companies",
        "record_sectors", "record_sector_companies", "record_sectors",
    ]


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
    client = ScriptedClient({
        "record_facts": {"facts": "f", "category": "other", "event_type": "other"},
        "record_sectors": {"sectors": [{"sector": "banking", "direction": "bearish", "mechanism": "m"}]},
        "record_sector_companies": ValueError("boom"),
    })

    result = analyze_article(client, title="t", content="c")

    assert result.companies == []


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
