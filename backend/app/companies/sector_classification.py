"""One-time top-level sector (re-)classification, using SECTORS as the
closed vocabulary (see app.analysis.schemas). Distinct from
app.companies.sub_sectors, which classifies one level below (a sub-sector
WITHIN an already-known sector) -- this module classifies the sector
itself. See backend/backfill_sectors.py for the one-time enrichment job
that uses this.
"""
import json

from openai import RateLimitError

from app.analysis.claude_client import FALLBACK_MODEL, MODEL
from app.analysis.schemas import SECTOR_DEFINITIONS, SECTORS


def build_sector_classify_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "record_sector_classifications",
            "description": "Classify each company into a sector.",
            "parameters": {
                "type": "object",
                "properties": {
                    "classifications": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "ticker": {"type": "string"},
                                "sector": {"type": "string", "enum": SECTORS},
                            },
                            "required": ["ticker", "sector"],
                        },
                    },
                },
                "required": ["classifications"],
            },
        },
    }


def classify_sector_batch(client, tickers_and_names: list[tuple[str, str]]) -> dict[str, str]:
    """One tool-call classifying every (ticker, name) pair into a top-level
    SECTORS value, based on its actual, primary line of business. A ticker
    the model returns with an off-enum sector falls back to "other" rather
    than raising -- "other" is itself a valid SECTORS value, unlike
    app.companies.sub_sectors.classify_batch's per-sector "_other" bucket.
    A ticker the model omits entirely from its response is simply absent
    from the returned dict -- the caller (backfill_sectors.py) leaves it
    untouched and retries it on the next run, same "omit rather than
    mismatch" philosophy as app.companies.resolution.
    """
    tool = build_sector_classify_tool()
    listing = "\n".join(f"- {ticker}: {name}" for ticker, name in tickers_and_names)
    messages = [
        {
            "role": "system",
            "content": (
                "You are a financial sector-classification analyst. Classify each "
                "listed company into exactly one sector from the given enum, based "
                "on its actual, primary line of business.\n\n"
                f"SECTOR DEFINITIONS:\n{SECTOR_DEFINITIONS}"
            ),
        },
        {"role": "user", "content": f"Companies to classify:\n{listing}"},
    ]

    def _call(model: str):
        return client.chat.completions.create(
            model=model,
            max_tokens=4096,
            tools=[tool],
            tool_choice={"type": "function", "function": {"name": "record_sector_classifications"}},
            messages=messages,
        )

    try:
        response = _call(MODEL)
    except RateLimitError:
        response = _call(FALLBACK_MODEL)

    message = response.choices[0].message
    tool_calls = message.tool_calls or []
    tool_call = next((tc for tc in tool_calls if tc.function.name == "record_sector_classifications"), None)
    if tool_call is None:
        return {}

    arguments = json.loads(tool_call.function.arguments)
    result: dict[str, str] = {}
    for entry in arguments.get("classifications", []):
        ticker = entry.get("ticker")
        sector = entry.get("sector")
        if not ticker:
            continue
        result[ticker] = sector if sector in SECTORS else "other"
    return result
