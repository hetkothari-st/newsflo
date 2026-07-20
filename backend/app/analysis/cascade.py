"""Sector-first, multi-step cascade reasoning: replaces the old single-call
app.analysis.claude_client.analyze_article with a 7-call chain (facts ->
primary sectors -> primary companies -> cascade sectors L1 -> cascade
companies L1 -> cascade sectors L2 -> cascade companies L2). See
docs/superpowers/specs/2026-07-20-sector-cascade-reasoning-design.md.

All three stage functions below (_extract_facts, _identify_sectors,
_identify_companies) are pure: given a client and inputs, they make exactly
one LLM call and return parsed, validated output, raising on a genuinely
malformed response (no tool_use block). The orchestrator (analyze_article,
added in a later task of this same plan) is responsible for sequencing
them and for the truncate-on-failure behavior described in the design spec.
"""
import json

from app.analysis.claude_client import FALLBACK_MODEL, SYSTEM_PROMPT
from app.analysis.schemas import CATEGORIES, EVENT_TYPES, SECTOR_DEFINITIONS, SECTORS, FactsResult, SectorFinding

FACTS_INSTRUCTIONS = (
    "Read this news article closely and extract its core facts and economic "
    "mechanism -- what actually happened, the key entities/numbers/geography "
    "involved, and WHY it matters economically. Do not name any companies or "
    "sectors yet -- that happens in a later step. Just establish the ground "
    "truth this analysis will reason from.\n\n"
    "Also classify this article's overall category (topical bucket, shown as "
    "a badge on the feed card) as exactly one of the values below -- "
    "lowercase-with-underscores, exact spelling, NEVER a sentence. If "
    "nothing matches, use \"other\":\n"
    f"{', '.join(CATEGORIES)}\n\n"
    "Also classify its event_type (the specific triggering event) as exactly "
    "one of the values below. If nothing matches, use \"other\":\n"
    f"{', '.join(EVENT_TYPES)}\n"
)


def build_facts_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "record_facts",
            "description": "Record the key facts/economic mechanism of this article and its classification.",
            "parameters": {
                "type": "object",
                "properties": {
                    "facts": {
                        "type": "string",
                        "description": (
                            "What actually happened, the key entities/numbers/geography "
                            "involved, and the economic mechanism at play -- plain "
                            "prose, no company or sector names yet."
                        ),
                    },
                    "category": {"type": "string", "enum": CATEGORIES},
                    "event_type": {"type": "string", "enum": EVENT_TYPES},
                },
                "required": ["facts", "category", "event_type"],
            },
        },
    }


def _extract_facts(client, title: str, content: str) -> FactsResult:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                FACTS_INSTRUCTIONS
                + f"Title: {title}\n\nContent: "
                + f"{content or '(no content available -- reason only from the title)'}"
            ),
        },
    ]
    response = client.chat.completions.create(
        model=FALLBACK_MODEL,
        max_tokens=1024,
        tools=[build_facts_tool()],
        tool_choice={"type": "function", "function": {"name": "record_facts"}},
        messages=messages,
    )
    message = response.choices[0].message
    tool_calls = message.tool_calls or []
    tool_call = next((tc for tc in tool_calls if tc.function.name == "record_facts"), None)
    if tool_call is None:
        raise ValueError(f"No record_facts tool_use block for article: {title!r}")
    arguments = json.loads(tool_call.function.arguments)
    return FactsResult.model_validate(arguments)


def build_sector_tool(cascade: bool, valid_parents: list[str] | None) -> dict:
    """cascade=False builds the primary/directly-affected sector tool
    (stage 2, no parent_sector field). cascade=True builds the cascade
    tool (stages 4/6), adding a parent_sector field enum-constrained to
    valid_parents so the model cannot invent a nonexistent parent sector."""
    properties = {
        "sector": {"type": "string", "enum": SECTORS},
        "direction": {"type": "string", "enum": ["bullish", "bearish"]},
        "mechanism": {
            "type": "string",
            "description": "One-line explanation of why this sector is affected.",
        },
    }
    required = ["sector", "direction", "mechanism"]
    if cascade:
        properties["parent_sector"] = {"type": "string", "enum": valid_parents}
        required.append("parent_sector")
    return {
        "type": "function",
        "function": {
            "name": "record_sectors",
            "description": "Record sectors affected by this news, with direction and mechanism.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sectors": {
                        "type": "array",
                        "items": {"type": "object", "properties": properties, "required": required},
                    },
                },
                "required": ["sectors"],
            },
        },
    }


def _identify_sectors(client, facts: str, parent_sectors: list[SectorFinding] | None) -> list[SectorFinding]:
    """parent_sectors=None -> primary/directly-affected sector identification
    (stage 2). parent_sectors=<a prior stage's sectors> -> cascade: sectors
    affected AS A CONSEQUENCE of those already-identified sectors, one hop
    further out (stage 4 or 6)."""
    if parent_sectors is None:
        framing = (
            "Given these facts, identify every financial, business, or economic "
            "sector DIRECTLY affected by this news -- the sectors the news is "
            "actually about, not knock-on effects. For each, give its direction "
            "(bullish/bearish) and a one-line mechanism explaining WHY that "
            "sector is affected. Zero sectors is a correct answer when nothing "
            "in the facts genuinely supports one."
        )
        parent_context = ""
        valid_parents = None
    else:
        parent_lines = "\n".join(f"- {s.sector}: {s.mechanism}" for s in parent_sectors)
        framing = (
            "Given these facts and the sectors already identified as directly "
            "affected, identify sectors affected AS A CONSEQUENCE of those -- a "
            "ripple/knock-on effect, not the news's own direct subject. Only "
            "include a sector here if you have a genuine, specific mechanism "
            "for why it's affected because of the parent sector's own move, "
            "not because it's tangentially related. Zero cascade sectors is a "
            "correct answer when you don't have a real, specific one. For each, "
            "give its direction, a one-line mechanism, and which of the "
            "already-identified sectors it's rippling from (parent_sector)."
        )
        parent_context = f"\n\nAlready-identified sectors this may ripple from:\n{parent_lines}"
        valid_parents = [s.sector for s in parent_sectors]

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"{framing}\n\n"
                f"SECTOR DEFINITIONS:\n{SECTOR_DEFINITIONS}\n\n"
                f"Facts: {facts}"
                f"{parent_context}"
            ),
        },
    ]
    tool = build_sector_tool(cascade=parent_sectors is not None, valid_parents=valid_parents)
    response = client.chat.completions.create(
        model=FALLBACK_MODEL,
        max_tokens=2048,
        tools=[tool],
        tool_choice={"type": "function", "function": {"name": "record_sectors"}},
        messages=messages,
    )
    message = response.choices[0].message
    tool_calls = message.tool_calls or []
    tool_call = next((tc for tc in tool_calls if tc.function.name == "record_sectors"), None)
    if tool_call is None:
        raise ValueError("No record_sectors tool_use block")
    arguments = json.loads(tool_call.function.arguments)
    return [SectorFinding.model_validate(s) for s in arguments.get("sectors", [])]
