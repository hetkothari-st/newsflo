"""The LLM refinement layer (docs/NEWS_IMPACT_APP_SPEC.md, this repo's
docs/superpowers/plans/2026-07-22-measurement-first-impact-phase3-llm-
refinement.md). Every function here produces TEXT explaining an
already-measured fact -- never a number, never a prediction. Measurement
(app.market.measure) is the spine; this module is the explanation layer on
top of it. Built up across the plan's Tasks 4 (generate_event_summary), 5
(generate_impact_whys), 6 (generate_timeline_effects), and 9
(refine_alert, the orchestrator).
"""
import json

from openai import RateLimitError

from app.analysis.claude_client import FALLBACK_MODEL, MODEL, SYSTEM_PROMPT
from app.reasoning.compliance import validate_or_none

EVENT_SUMMARY_FRAMING = (
    "Summarize this news event for a retail investor with no finance "
    "background. summary_short must be 12 words or fewer -- the single "
    "most important, plain-language takeaway. summary_long must be "
    "exactly two sentences, plain language, no jargon (unpack any finance "
    "term you use). Do not include any percentage, price, price target, "
    "or buy/sell/hold language -- describe what happened and why it "
    "matters, not whether to trade on it."
)


def build_event_summary_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "record_event_summary",
            "description": "Summarize this news event in plain, jargon-free language.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary_short": {
                        "type": "string",
                        "description": "One line, 12 words or fewer, the core 'why this matters' in plain language.",
                    },
                    "summary_long": {
                        "type": "string",
                        "description": "Exactly two plain-language sentences, jargon-free, expanding on summary_short.",
                    },
                },
                "required": ["summary_short", "summary_long"],
            },
        },
    }


def _call_event_summary_tool(client, title: str, content: str) -> dict | None:
    """Returns the parsed tool-call arguments, or None on any failure --
    a malformed/truncated JSON response, an exhausted RateLimitError
    fallback, or any other client error all degrade to None rather than
    raising, same "never crash the alert" discipline as
    app.market.measure.measure_company_move."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"{EVENT_SUMMARY_FRAMING}\n\nTitle: {title}\n\nContent: {content}"},
    ]
    tool = build_event_summary_tool()

    def _call(model: str):
        return client.chat.completions.create(
            model=model, max_tokens=512, tools=[tool],
            tool_choice={"type": "function", "function": {"name": "record_event_summary"}},
            messages=messages,
        )

    try:
        try:
            response = _call(MODEL)
        except RateLimitError:
            response = _call(FALLBACK_MODEL)
        message = response.choices[0].message
        tool_call = next((tc for tc in (message.tool_calls or []) if tc.function.name == "record_event_summary"), None)
        if tool_call is None:
            return None
        return json.loads(tool_call.function.arguments)
    except Exception:
        return None


def generate_event_summary(client, title: str, content: str) -> dict | None:
    """Returns {"summary_short", "summary_long"} (either may be None if it
    never passed validation, even after one retry), or None entirely if
    NEITHER field ever became usable. Never raises -- a malformed or
    missing tool-call response degrades to None, same "never crash the
    alert" discipline as app.market.measure.measure_company_move."""
    first = _call_event_summary_tool(client, title, content)
    if first is None:
        return None

    summary_short = validate_or_none(first.get("summary_short"))
    summary_long = validate_or_none(first.get("summary_long"))

    if summary_short is None or summary_long is None:
        retry = _call_event_summary_tool(client, title, content)
        if retry is not None:
            if summary_short is None:
                summary_short = validate_or_none(retry.get("summary_short"))
            if summary_long is None:
                summary_long = validate_or_none(retry.get("summary_long"))

    if summary_short is None and summary_long is None:
        return None
    return {"summary_short": summary_short, "summary_long": summary_long}
