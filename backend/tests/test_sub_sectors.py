import json
from types import SimpleNamespace

from app.companies.sub_sectors import (
    SUB_SECTOR_DEFINITIONS,
    SUB_SECTOR_TAXONOMY,
    build_classify_tool,
    classify_batch,
    is_valid_sub_sector,
    other_bucket,
)


class FakeToolCall:
    def __init__(self, name, arguments_dict):
        self.function = SimpleNamespace(name=name, arguments=json.dumps(arguments_dict))


class FakeCompletions:
    def __init__(self, response_input):
        self._response_input = response_input

    def create(self, **kwargs):
        message = SimpleNamespace(
            tool_calls=[FakeToolCall("record_subsector_classifications", self._response_input)]
        )
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeChat:
    def __init__(self, response_input):
        self.completions = FakeCompletions(response_input)


class FakeClient:
    def __init__(self, response_input):
        self.chat = FakeChat(response_input)


def test_is_valid_sub_sector_true_for_known_pair():
    assert is_valid_sub_sector("banking", "private_bank") is True


def test_is_valid_sub_sector_false_for_wrong_sector():
    assert is_valid_sub_sector("auto", "private_bank") is False


def test_is_valid_sub_sector_false_for_unknown_sector():
    assert is_valid_sub_sector("not_a_sector", "private_bank") is False


def test_other_bucket_is_always_a_valid_sub_sector():
    for sector in SUB_SECTOR_TAXONOMY:
        assert is_valid_sub_sector(sector, other_bucket(sector))


def test_every_sector_has_definitions_and_a_matching_taxonomy_key_set():
    assert set(SUB_SECTOR_DEFINITIONS) == set(SUB_SECTOR_TAXONOMY)


def test_build_classify_tool_enum_matches_taxonomy():
    tool = build_classify_tool("banking")
    enum = tool["function"]["parameters"]["properties"]["classifications"]["items"]["properties"]["sub_sector"]["enum"]
    assert enum == SUB_SECTOR_TAXONOMY["banking"]


def test_classify_batch_accepts_a_valid_response():
    client = FakeClient({"classifications": [{"ticker": "HDFCBANK.NS", "sub_sector": "private_bank"}]})
    result = classify_batch(client, "banking", [("HDFCBANK.NS", "HDFC Bank")])
    assert result == {"HDFCBANK.NS": "private_bank"}


def test_classify_batch_falls_back_to_other_bucket_for_an_off_enum_value():
    # The model returned a sub_sector that doesn't belong to this sector's
    # enum at all -- must not be persisted as-is.
    client = FakeClient({"classifications": [{"ticker": "HDFCBANK.NS", "sub_sector": "not_a_real_value"}]})
    result = classify_batch(client, "banking", [("HDFCBANK.NS", "HDFC Bank")])
    assert result == {"HDFCBANK.NS": "banking_other"}


def test_classify_batch_falls_back_to_other_bucket_for_a_ticker_the_model_omitted():
    client = FakeClient({"classifications": []})
    result = classify_batch(client, "banking", [("HDFCBANK.NS", "HDFC Bank")])
    # An omitted ticker gets no entry at all -- the caller (backfill script)
    # treats a missing key as "still unclassified, try again next run" rather
    # than guessing a bucket for it.
    assert result == {}
