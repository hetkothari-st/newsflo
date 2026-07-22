"""LLM-assisted company enrichment: plain-language business description
plus supply-chain suppliers/customers, used for the (i) business/sector
popup and the discovery directory (docs/NEWS_IMPACT_APP_SPEC.md §3.1).
One-time-per-company enrichment job (see backend/backfill_business_
profiles.py) -- Company.business_desc/supply_chain_*_json are read at API-
serialization time, never written by the per-article analysis pipeline
(this is master company data, not per-event data), same pattern as
app.companies.sub_sectors.classify_batch / backfill_subsectors.py.
"""
import json

from openai import RateLimitError

from app.analysis.claude_client import FALLBACK_MODEL, MODEL, SYSTEM_PROMPT
from app.reasoning.compliance import validate_no_advice_language

BUSINESS_PROFILE_FRAMING = (
    "For each company below, write a one-sentence, jargon-free "
    "description of what it actually does (for a reader with no finance "
    "background), plus its main suppliers (companies/industries it buys "
    "key inputs from) and main customers (companies/industries it sells "
    "to) -- real, specific names or industries you actually know, not "
    "generic filler. Empty lists are correct when you don't have a "
    "confident, specific answer. No percentage, price, or buy/sell/hold "
    "language."
)


def build_business_profile_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "record_business_profiles",
            "description": "Describe each company's business in plain language and name its main suppliers/customers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "profiles": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "ticker": {"type": "string"},
                                "business_desc": {"type": "string"},
                                "suppliers": {"type": "array", "items": {"type": "string"}},
                                "customers": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["ticker", "business_desc", "suppliers", "customers"],
                        },
                    },
                },
                "required": ["profiles"],
            },
        },
    }


def _call_business_profile_tool(client, companies: list[tuple[str, str, str]]) -> dict[str, dict]:
    """Returns {ticker: entry} parsed from the tool call, or {} on any
    failure -- a malformed/truncated JSON response, an exhausted
    RateLimitError fallback, a missing tool-call, or any other client
    error all degrade to {} rather than raising, same "never crash the
    alert" discipline as app.market.measure.measure_company_move. The
    entire attempt (both model attempts, response parsing, and
    json.loads) is wrapped in one outer try/except so nothing here can
    ever propagate."""
    listing = "\n".join(f"- {ticker}: {name} ({sector})" for ticker, name, sector in companies)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"{BUSINESS_PROFILE_FRAMING}\n\nCompanies:\n{listing}"},
    ]
    tool = build_business_profile_tool()

    def _call(model: str):
        return client.chat.completions.create(
            model=model, max_tokens=4096, tools=[tool],
            tool_choice={"type": "function", "function": {"name": "record_business_profiles"}},
            messages=messages,
        )

    try:
        try:
            response = _call(MODEL)
        except RateLimitError:
            response = _call(FALLBACK_MODEL)
        message = response.choices[0].message
        tool_call = next((tc for tc in (message.tool_calls or []) if tc.function.name == "record_business_profiles"), None)
        if tool_call is None:
            return {}
        arguments = json.loads(tool_call.function.arguments)
        return {
            entry["ticker"]: entry for entry in arguments.get("profiles", [])
            if entry.get("ticker") not in (None, "") and entry.get("business_desc") not in (None, "")
        }
    except Exception:
        return {}


def generate_business_profiles_batch(client, companies: list[tuple[str, str, str]]) -> dict[str, dict]:
    """companies: [(ticker, name, sector), ...]. Returns {ticker: {
    business_desc, suppliers, customers}}. A ticker the model omits, or
    whose business_desc fails validate_no_advice_language even after one
    batched retry, is absent from the result -- the caller
    (backfill_business_profiles.py) leaves it unenriched and retries on
    the next run, same "omit rather than fabricate" discipline as
    app.companies.sub_sectors.classify_batch. Never raises -- see
    _call_business_profile_tool."""
    if not companies:
        return {}
    first = _call_business_profile_tool(client, companies)

    result: dict[str, dict] = {}
    retry_tickers = []
    for ticker, _name, _sector in companies:
        entry = first.get(ticker)
        if entry is None:
            continue
        if validate_no_advice_language(entry["business_desc"]).is_valid:
            result[ticker] = {
                "business_desc": entry["business_desc"],
                "suppliers": entry.get("suppliers", []),
                "customers": entry.get("customers", []),
            }
        else:
            retry_tickers.append(ticker)

    if retry_tickers:
        retry_companies = [c for c in companies if c[0] in retry_tickers]
        retry = _call_business_profile_tool(client, retry_companies)
        for ticker in retry_tickers:
            entry = retry.get(ticker)
            if entry is None:
                continue
            if validate_no_advice_language(entry["business_desc"]).is_valid:
                result[ticker] = {
                    "business_desc": entry["business_desc"],
                    "suppliers": entry.get("suppliers", []),
                    "customers": entry.get("customers", []),
                }

    return result
