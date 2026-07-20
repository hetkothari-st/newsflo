import json
from types import SimpleNamespace

from app.companies.sector_classification import build_sector_classify_tool, classify_sector_batch
from app.analysis.schemas import SECTORS


class FakeToolCall:
    def __init__(self, name, arguments_dict):
        self.function = SimpleNamespace(name=name, arguments=json.dumps(arguments_dict))


class FakeCompletions:
    def __init__(self, response_input):
        self._response_input = response_input

    def create(self, **kwargs):
        message = SimpleNamespace(tool_calls=[FakeToolCall("record_sector_classifications", self._response_input)])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeClient:
    def __init__(self, response_input):
        self.chat = SimpleNamespace(completions=FakeCompletions(response_input))


def test_build_sector_classify_tool_enum_matches_sectors():
    tool = build_sector_classify_tool()
    enum = tool["function"]["parameters"]["properties"]["classifications"]["items"]["properties"]["sector"]["enum"]
    assert enum == SECTORS


def test_classify_sector_batch_accepts_a_valid_response():
    client = FakeClient({"classifications": [{"ticker": "IRCTC.NS", "sector": "railways_transport"}]})
    result = classify_sector_batch(client, [("IRCTC.NS", "Indian Railway Catering and Tourism Corp")])
    assert result == {"IRCTC.NS": "railways_transport"}


def test_classify_sector_batch_falls_back_to_other_for_an_off_enum_value():
    client = FakeClient({"classifications": [{"ticker": "IRCTC.NS", "sector": "not_a_real_sector"}]})
    result = classify_sector_batch(client, [("IRCTC.NS", "Indian Railway Catering and Tourism Corp")])
    assert result == {"IRCTC.NS": "other"}


def test_classify_sector_batch_omits_a_ticker_the_model_did_not_address():
    client = FakeClient({"classifications": []})
    result = classify_sector_batch(client, [("IRCTC.NS", "Indian Railway Catering and Tourism Corp")])
    assert result == {}


def test_classify_sector_batch_prompt_includes_sector_definitions():
    captured = {}

    def create(**kwargs):
        captured["messages"] = kwargs["messages"]
        response = {"classifications": []}
        message = SimpleNamespace(tool_calls=[FakeToolCall("record_sector_classifications", response)])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    classify_sector_batch(client, [("IRCTC.NS", "Indian Railway Catering and Tourism Corp")])

    all_content = " ".join(m["content"] for m in captured["messages"])
    assert "construction_realestate: real estate developers" in all_content
