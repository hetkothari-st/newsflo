import json

from openai import OpenAI

from app.analysis.schemas import SECTORS, AnalysisOutput

MODEL = "anthropic/claude-sonnet-4.5"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

RECORD_ANALYSIS_TOOL = {
    "type": "function",
    "function": {
        "name": "record_analysis",
        "description": "Record which companies are affected by this news article and how.",
        "parameters": {
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
    },
}


def build_client(api_key: str) -> OpenAI:
    return OpenAI(api_key=api_key, base_url=OPENROUTER_BASE_URL)


def analyze_article(client, title: str, content: str) -> AnalysisOutput:
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=600,
        tools=[RECORD_ANALYSIS_TOOL],
        tool_choice={"type": "function", "function": {"name": "record_analysis"}},
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
    message = response.choices[0].message
    tool_calls = message.tool_calls or []
    tool_call = next((tc for tc in tool_calls if tc.function.name == "record_analysis"), None)
    if tool_call is None:
        raise ValueError(f"Claude response contained no tool_use block for article: {title!r}")
    arguments = json.loads(tool_call.function.arguments)
    return AnalysisOutput.model_validate(arguments)
