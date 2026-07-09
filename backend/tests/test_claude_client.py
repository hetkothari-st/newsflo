from types import SimpleNamespace

from app.analysis.claude_client import analyze_article


class FakeToolUseBlock:
    type = "tool_use"

    def __init__(self, input_data):
        self.input = input_data


class FakeMessages:
    def __init__(self, response_input):
        self._response_input = response_input

    def create(self, **kwargs):
        return SimpleNamespace(content=[FakeToolUseBlock(self._response_input)])


class FakeClient:
    def __init__(self, response_input):
        self.messages = FakeMessages(response_input)


def test_analyze_article_parses_direct_mention():
    fake_output = {
        "category": "oil_energy",
        "companies": [{
            "name": "Reliance Industries", "ticker": "RELIANCE.NS", "is_direct": True, "sector": None,
            "direction": "bullish", "magnitude_low": 2.0, "magnitude_high": 4.0,
            "rationale": "Top refiner benefits from crude price spike.",
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
        }],
    }
    client = FakeClient(fake_output)

    result = analyze_article(client, title="Crude prices spike globally", content="")

    assert result.companies[0].is_direct is False
    assert result.companies[0].sector == "oil_gas"


class FakeMessagesNoToolUse:
    """Fake messages that returns empty content (no tool_use block)."""
    def create(self, **kwargs):
        return SimpleNamespace(content=[])


class FakeClientNoToolUse:
    def __init__(self):
        self.messages = FakeMessagesNoToolUse()


def test_analyze_article_raises_on_missing_tool_use_block():
    """Test that a clear ValueError is raised when Claude response has no tool_use block."""
    client = FakeClientNoToolUse()
    article_title = "Test Article Title"

    try:
        analyze_article(client, title=article_title, content="Some content")
        assert False, "Expected ValueError to be raised"
    except ValueError as e:
        assert "Claude response contained no tool_use block" in str(e)
        assert article_title in str(e)
