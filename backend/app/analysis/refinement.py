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


IMPACT_WHY_FRAMING = (
    "Each company below already has a MEASURED market reaction to this "
    "news -- a real, observed price move relative to its sector, already "
    "computed from market data. Your job is ONLY to explain, in one "
    "plain-language sentence per company, the causal mechanism: why this "
    "specific news would move this specific company in that direction. "
    "You are explaining an observed fact, not predicting one -- never "
    "restate, estimate, or imply any percentage, price, or magnitude in "
    "your explanation; the number itself is already measured and shown "
    "separately. Never use buy/sell/hold, rating, or price-target "
    "language. If you cannot state a genuine, specific mechanism for a "
    "company, omit it rather than writing a vague sentence."
)


def build_impact_why_tool(tickers: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": "record_impact_whys",
            "description": "Explain, in plain language, why each company's already-measured market reaction happened.",
            "parameters": {
                "type": "object",
                "properties": {
                    "whys": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "ticker": {"type": "string", "enum": tickers},
                                "why": {"type": "string"},
                            },
                            "required": ["ticker", "why"],
                        },
                    },
                },
                "required": ["whys"],
            },
        },
    }


def _call_impact_why_tool(client, title: str, content: str, companies: list[dict]) -> dict[str, str]:
    """Returns {ticker: why} parsed from the tool call, or {} on any
    failure -- a malformed/truncated JSON response, an exhausted
    RateLimitError fallback, a missing tool-call, or any other client
    error all degrade to {} rather than raising, same "never crash the
    alert" discipline as app.market.measure.measure_company_move. The
    entire attempt (both model attempts, response parsing, and
    json.loads) is wrapped in one outer try/except so nothing here can
    ever propagate."""
    tickers = [c["ticker"] for c in companies]
    company_lines = "\n".join(
        f"- {c['ticker']} ({c['name']}): moved {c['direction']}, a "
        f"{'sharp' if abs(c['excess_move_pct']) >= 3 else 'modest'} reaction "
        "relative to its sector (do not restate any number in your answer)"
        for c in companies
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"{IMPACT_WHY_FRAMING}\n\nArticle: {title}\n\n{content}\n\nCompanies:\n{company_lines}",
        },
    ]
    tool = build_impact_why_tool(tickers)

    def _call(model: str):
        return client.chat.completions.create(
            model=model, max_tokens=2048, tools=[tool],
            tool_choice={"type": "function", "function": {"name": "record_impact_whys"}},
            messages=messages,
        )

    try:
        try:
            response = _call(MODEL)
        except RateLimitError:
            response = _call(FALLBACK_MODEL)
        message = response.choices[0].message
        tool_call = next((tc for tc in (message.tool_calls or []) if tc.function.name == "record_impact_whys"), None)
        if tool_call is None:
            return {}
        arguments = json.loads(tool_call.function.arguments)
        return {
            entry["ticker"]: entry["why"] for entry in arguments.get("whys", [])
            if entry.get("ticker") and entry.get("why") is not None
        }
    except Exception:
        return {}


def generate_impact_whys(client, title: str, content: str, companies: list[dict]) -> dict[str, str]:
    """companies: [{"ticker", "name", "direction", "excess_move_pct"}, ...]
    -- only companies with a real measured excess_move_pct
    (measurement_status == "ok") should ever be passed in; this function
    never invents a why for a company with no measured move. Returns
    {ticker: why} -- a ticker the model never answered is not retried
    (same "omit rather than mismatch" discipline as
    app.companies.sub_sectors.classify_batch); a ticker the model DID
    answer but whose text fails validation gets one batched retry
    covering every such ticker, then is dropped if still invalid. Never
    raises -- see _call_impact_why_tool."""
    if not companies:
        return {}
    tickers = [c["ticker"] for c in companies]
    first = _call_impact_why_tool(client, title, content, companies)

    result: dict[str, str] = {}
    retry_tickers = []
    for ticker in tickers:
        if ticker not in first:
            continue  # model never answered -- not retried, simply absent
        text = validate_or_none(first[ticker])
        if text is not None:
            result[ticker] = text
        else:
            retry_tickers.append(ticker)

    if retry_tickers:
        retry_companies = [c for c in companies if c["ticker"] in retry_tickers]
        retry = _call_impact_why_tool(client, title, content, retry_companies)
        for ticker in retry_tickers:
            text = validate_or_none(retry.get(ticker))
            if text is not None:
                result[ticker] = text

    return result


HORIZONS = ["TODAY", "DAYS", "WEEKS", "MONTHS", "QUARTERS"]

TIMELINE_FRAMING = (
    "Describe how this news event's effect plays out over time -- one "
    "entry per horizon that genuinely has something distinct to say "
    "(TODAY = immediate market reaction, DAYS = next few trading days, "
    "WEEKS = next few weeks, MONTHS = next few months, QUARTERS = "
    "multi-quarter/structural). Skip a horizon entirely if you have "
    "nothing genuinely distinct to add for it -- zero, one, or several "
    "entries are all correct depending on the story. Plain language, no "
    "jargon, no percentage, price, or buy/sell/hold language -- describe "
    "what unfolds, not whether to trade on it."
)


def build_timeline_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "record_timeline_effects",
            "description": "Describe how this news event's effect unfolds over time, one entry per relevant horizon.",
            "parameters": {
                "type": "object",
                "properties": {
                    "effects": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "horizon": {"type": "string", "enum": HORIZONS},
                                "description": {"type": "string"},
                            },
                            "required": ["horizon", "description"],
                        },
                    },
                },
                "required": ["effects"],
            },
        },
    }


def _call_timeline_tool(client, title: str, content: str) -> list[dict]:
    """Returns [{"horizon", "description"}, ...] parsed from the tool
    call, dropping any entry whose horizon isn't one of the five
    recognized values or whose description is empty -- or [] on any
    failure -- a malformed/truncated JSON response, an exhausted
    RateLimitError fallback, a missing tool-call, or any other client
    error all degrade to [] rather than raising, same "never crash the
    alert" discipline as app.market.measure.measure_company_move. The
    entire attempt (both model attempts, response parsing, and
    json.loads) is wrapped in one outer try/except so nothing here can
    ever propagate."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"{TIMELINE_FRAMING}\n\nTitle: {title}\n\nContent: {content}"},
    ]
    tool = build_timeline_tool()

    def _call(model: str):
        return client.chat.completions.create(
            model=model, max_tokens=1536, tools=[tool],
            tool_choice={"type": "function", "function": {"name": "record_timeline_effects"}},
            messages=messages,
        )

    try:
        try:
            response = _call(MODEL)
        except RateLimitError:
            response = _call(FALLBACK_MODEL)
        message = response.choices[0].message
        tool_call = next((tc for tc in (message.tool_calls or []) if tc.function.name == "record_timeline_effects"), None)
        if tool_call is None:
            return []
        arguments = json.loads(tool_call.function.arguments)
        return [
            {"horizon": e["horizon"], "description": e["description"]}
            for e in arguments.get("effects", [])
            if e.get("horizon") in HORIZONS and e.get("description")
        ]
    except Exception:
        return []


def generate_timeline_effects(client, title: str, content: str) -> list[dict]:
    """Returns [{"horizon", "description"}, ...], zero or more -- only for
    horizons the model gave genuine distinct content for AND whose
    description passes validation, retrying once (batched) for any
    horizon that failed validation, then dropping it if still invalid.
    Unrecognized horizon values are dropped during parsing in
    _call_timeline_tool and never reach here, so they are never
    persisted or retried. Never raises -- see _call_timeline_tool."""
    first = _call_timeline_tool(client, title, content)

    valid = []
    invalid_horizons = []
    for entry in first:
        text = validate_or_none(entry["description"])
        if text is not None:
            valid.append({"horizon": entry["horizon"], "description": text})
        else:
            invalid_horizons.append(entry["horizon"])

    if invalid_horizons:
        retry_by_horizon = {e["horizon"]: e["description"] for e in _call_timeline_tool(client, title, content)}
        for horizon in invalid_horizons:
            text = validate_or_none(retry_by_horizon.get(horizon))
            if text is not None:
                valid.append({"horizon": horizon, "description": text})

    return valid
