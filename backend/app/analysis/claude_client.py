from anthropic import Anthropic

from app.analysis.schemas import SECTORS, AnalysisOutput

MODEL = "claude-sonnet-4-5"

RECORD_ANALYSIS_TOOL = {
    "name": "record_analysis",
    "description": "Record which companies are affected by this news article and how.",
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {"type": "string"},
            "companies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "ticker": {"type": ["string", "null"]},
                        "is_direct": {"type": "boolean"},
                        "sector": {"type": ["string", "null"], "enum": SECTORS + [None]},
                        "direction": {"type": "string", "enum": ["bullish", "bearish"]},
                        "magnitude_low": {"type": "number"},
                        "magnitude_high": {"type": "number"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["name", "is_direct", "direction", "magnitude_low", "magnitude_high", "rationale"],
                },
            },
        },
        "required": ["category", "companies"],
    },
}


def build_client(api_key: str) -> Anthropic:
    return Anthropic(api_key=api_key)


def analyze_article(client, title: str, content: str) -> AnalysisOutput:
    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        tools=[RECORD_ANALYSIS_TOOL],
        tool_choice={"type": "tool", "name": "record_analysis"},
        messages=[{
            "role": "user",
            "content": (
                "Analyze this financial news article. Identify which companies are directly "
                "named and which sectors are indirectly affected, with direction and an "
                "estimated percentage price-move range.\n\n"
                f"Title: {title}\n\nContent: {content}"
            ),
        }],
    )
    tool_use = next(block for block in message.content if block.type == "tool_use")
    return AnalysisOutput.model_validate(tool_use.input)
