"""Per-company verification: the explicit "does this company belong?" pass.

The cascade's own stages are generative -- each one is asked to FIND
companies, and a model asked to find things finds things. Nothing re-read the
assembled list and asked the opposite question, which is how a food-delivery
company survived to the card back of a crude-oil story.

This pass can only judge, never add: `ticker` is enum-constrained to the
already-assembled list, and any verdict naming a ticker outside it is
ignored. Failure keeps every company -- a provider outage must not silently
empty an alert, the same "degrade, never crash" discipline as
app.analysis.refinement.
"""
import json
import logging

from openai import RateLimitError

from app.analysis.claude_client import FALLBACK_MODEL, MODEL, SYSTEM_PROMPT
from app.analysis.schemas import CompanyMention

logger = logging.getLogger(__name__)

VERIFICATION_FRAMING = (
    "Below is a list of companies a previous analysis step proposed as "
    "affected by this news, each with the reason it gave. For EACH company, "
    "decide one thing only: does a specific, concrete mechanism from THESE "
    "facts genuinely reach THAT company's own business -- its revenue, its "
    "costs, its customers, or its competitive position?\n\n"
    "Set belongs=false when the link is thematic, generic, or true of the "
    "whole economy rather than this company; when the stated reason only "
    "says the company is large or well-known in a sector the news touches; "
    "or when the reason restates a fact from the article without connecting "
    "it to this company. Set belongs=true only when you could defend the "
    "link to a professional equity analyst reading the same article.\n\n"
    "Judge each company independently. Rejecting most of the list is a "
    "correct answer, and so is accepting all of it -- do not aim for a "
    "balance. You may not add companies; judge only what is listed."
)


def build_verification_tool(valid_tickers: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": "record_company_verdicts",
            "description": "Judge whether each proposed company is genuinely affected by this news.",
            "parameters": {
                "type": "object",
                "properties": {
                    "verdicts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "ticker": {"type": "string", "enum": valid_tickers},
                                "belongs": {"type": "boolean"},
                                "reason": {
                                    "type": "string",
                                    "description": "One line. Required when belongs is false.",
                                },
                            },
                            "required": ["ticker", "belongs"],
                        },
                    },
                },
                "required": ["verdicts"],
            },
        },
    }


def verify_companies(
    client, facts: str, title: str, companies: list[CompanyMention],
) -> list[CompanyMention]:
    """Returns the subset of `companies` that survives verification, in the
    original order.

    A company the model never returned a verdict for is KEPT -- omission is
    not a rejection (same discipline as
    app.analysis.refinement.generate_impact_whys). A company with no ticker
    (a sector fan-out mention) is never judged and always kept: it makes no
    company-specific claim to verify. Any failure returns the input list
    unchanged.
    """
    judgeable = [c for c in companies if c.ticker]
    if not judgeable:
        return companies

    tickers = [c.ticker for c in judgeable]
    listing = "\n".join(f"- {c.ticker} ({c.name}): {c.rationale}" for c in judgeable)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"{VERIFICATION_FRAMING}\n\nArticle: {title}\n\nFacts: {facts}\n\n"
            f"Proposed companies:\n{listing}"
        )},
    ]
    tool = build_verification_tool(tickers)

    def _call(model: str):
        return client.chat.completions.create(
            model=model, max_tokens=2048, tools=[tool],
            tool_choice={"type": "function", "function": {"name": "record_company_verdicts"}},
            messages=messages,
        )

    try:
        try:
            response = _call(MODEL)
        except RateLimitError:
            response = _call(FALLBACK_MODEL)
        message = response.choices[0].message
        tool_call = next(
            (tc for tc in (message.tool_calls or []) if tc.function.name == "record_company_verdicts"),
            None,
        )
        if tool_call is None:
            logger.warning("verification returned no tool call; keeping every company")
            return companies
        arguments = json.loads(tool_call.function.arguments)
    except Exception as exc:
        logger.warning("verification call failed, keeping every company: %s", exc)
        return companies

    known = set(tickers)
    rejected: dict[str, str] = {}
    for verdict in arguments.get("verdicts", []):
        ticker = verdict.get("ticker")
        # Defensive: provider enums are not reliably enforced for nested
        # array items (cascade.py:282). A verdict about a company that is
        # not on the list cannot mean anything.
        if ticker not in known:
            continue
        if verdict.get("belongs") is False:
            rejected[ticker] = verdict.get("reason") or "no stated reason"

    for ticker, reason in rejected.items():
        logger.info("verification dropped %s: %s", ticker, reason)

    return [c for c in companies if not (c.ticker and c.ticker in rejected)]
