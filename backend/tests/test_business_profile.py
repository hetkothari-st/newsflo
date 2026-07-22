import json
from types import SimpleNamespace

from app.companies.business_profile import generate_business_profiles_batch


class FakeToolCall:
    def __init__(self, name, arguments_dict):
        self.function = SimpleNamespace(name=name, arguments=json.dumps(arguments_dict))


class QueuedFakeClient:
    def __init__(self, responses: list[tuple[str, dict]]):
        self._responses = list(responses)
        self.calls = 0

    class _Completions:
        def __init__(self, outer):
            self._outer = outer

        def create(self, **kwargs):
            if not self._outer._responses:
                raise AssertionError("QueuedFakeClient: no more responses queued")
            self._outer.calls += 1
            name, arguments = self._outer._responses.pop(0)
            message = SimpleNamespace(tool_calls=[FakeToolCall(name, arguments)])
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    @property
    def chat(self):
        return SimpleNamespace(completions=self._Completions(self))


def test_generate_business_profiles_batch_returns_valid_entries():
    client = QueuedFakeClient([
        ("record_business_profiles", {"profiles": [
            {
                "ticker": "RELIANCE.NS", "business_desc": "Runs oil refining, retail, and telecom businesses.",
                "suppliers": ["Crude oil producers"], "customers": ["Fuel retailers", "Telecom consumers"],
            },
        ]}),
    ])
    result = generate_business_profiles_batch(client, [("RELIANCE.NS", "Reliance Industries", "oil_gas")])
    assert result["RELIANCE.NS"]["business_desc"] == "Runs oil refining, retail, and telecom businesses."
    assert result["RELIANCE.NS"]["suppliers"] == ["Crude oil producers"]
    assert result["RELIANCE.NS"]["customers"] == ["Fuel retailers", "Telecom consumers"]
    assert client.calls == 1


def test_generate_business_profiles_batch_retries_only_rejected_tickers():
    client = QueuedFakeClient([
        ("record_business_profiles", {"profiles": [
            {"ticker": "A.NS", "business_desc": "Expect 5% growth this quarter.", "suppliers": [], "customers": []},
            {"ticker": "B.NS", "business_desc": "Makes steel products for construction.", "suppliers": ["Iron ore miners"], "customers": ["Builders"]},
        ]}),
        ("record_business_profiles", {"profiles": [
            {"ticker": "A.NS", "business_desc": "Manufactures consumer electronics.", "suppliers": ["Component makers"], "customers": ["Retailers"]},
        ]}),
    ])
    result = generate_business_profiles_batch(client, [
        ("A.NS", "Company A", "consumer_durables"), ("B.NS", "Company B", "metals"),
    ])
    assert result["A.NS"]["business_desc"] == "Manufactures consumer electronics."
    assert result["B.NS"]["business_desc"] == "Makes steel products for construction."
    assert client.calls == 2


def test_generate_business_profiles_batch_drops_ticker_still_invalid_after_retry():
    client = QueuedFakeClient([
        ("record_business_profiles", {"profiles": [
            {"ticker": "A.NS", "business_desc": "Buy this stock for 5% upside.", "suppliers": [], "customers": []},
        ]}),
        ("record_business_profiles", {"profiles": [
            {"ticker": "A.NS", "business_desc": "Sell before the price target hits.", "suppliers": [], "customers": []},
        ]}),
    ])
    result = generate_business_profiles_batch(client, [("A.NS", "Company A", "auto")])
    assert "A.NS" not in result
    assert client.calls == 2


def test_generate_business_profiles_batch_empty_for_no_companies():
    assert generate_business_profiles_batch(QueuedFakeClient([]), []) == {}
