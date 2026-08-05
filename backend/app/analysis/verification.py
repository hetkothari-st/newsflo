"""Per-company verification: the explicit "does this company belong?" pass.

The cascade's own stages are generative -- each one is asked to FIND
companies, and a model asked to find things finds things. Nothing re-read the
assembled list and asked the opposite question, which is how a food-delivery
company survived to the card back of a crude-oil story.

This pass can only judge, never add: `ticker` is enum-constrained to the
already-assembled list, and any verdict naming a ticker outside it is
ignored. An LLM failure keeps every company the deterministic guard below
did not already drop -- a provider outage must not silently empty an alert,
the same "degrade, never crash" discipline as app.analysis.refinement.

Verification is the ONLY precision stage in the pipeline. Every generative
stage upstream is now deliberately tuned for breadth (see cascade.py's
sector and company framings): the candidate list is the safety rail on
INVENTION, and this pass is the safety rail on RELEVANCE. Loosening it to
compensate for a noisy list would leave the pipeline with neither.

Two filters run here, and they are independent on purpose:
  1. app.reasoning.vagueness.flag_vague_rationale -- deterministic, cannot
     fail, cannot be talked out of a rejection.
  2. the LLM verdict pass below -- judges facts a regex cannot.
"""
import json
import logging

from openai import RateLimitError

from app.analysis.claude_client import FALLBACK_MODEL, MODEL, SYSTEM_PROMPT
from app.analysis.schemas import CompanyMention
from app.reasoning.vagueness import flag_vague_rationale

logger = logging.getLogger(__name__)

VERIFICATION_FRAMING = (
    "Below is a list of companies a previous analysis step proposed as "
    "affected by this news, each with the reason it gave. That step was "
    "instructed to be BROAD, so this list is expected to contain companies "
    "that do not survive scrutiny. You are the only step that removes them.\n\n"
    "For EACH company, apply one concrete bar: does the stated reason name a "
    "specific, checkable channel through which THESE facts reach THAT "
    "company's own business -- a named cost line, a named revenue line, a "
    "named customer/supplier/competitor relationship, or a named regulatory "
    "exposure? Set belongs=true only if you could point at that channel and "
    "defend it to a professional equity analyst reading the same article.\n\n"
    "Set belongs=false in each of these cases:\n\n"
    "1. VAGUE OR HEDGED MECHANISM. The reason says the company \"may "
    "benefit\", \"could see\" an impact, is \"potentially\" affected, \"is "
    "exposed to\" the news, or rides \"sentiment\" or a \"broader theme\", "
    "and names no concrete channel behind the hedge. Hedging is fine when a "
    "channel IS named -- \"margins may compress because jet fuel is a large "
    "share of operating cost\" names a real cost line and passes. A hedge "
    "with nothing behind it does not.\n\n"
    "2. FACTUALLY UNSUPPORTED PREMISE. The mechanism depends on a claim "
    "about that company's business that is simply not true. Use what you "
    "actually know about the company -- what it makes, buys, sells, and "
    "operates. Worked example: \"FAA certification of the Boeing 737 MAX 7 "
    "lets IndiGo consider fleet expansion\" must be rejected, because "
    "IndiGo operates an all-Airbus fleet, so the premise that a Boeing "
    "certification reaches its fleet plans is false. A mechanism resting on "
    "a false premise about the company is not a weak link, it is not a link "
    "at all. If the premise is one you cannot verify either way, judge it on "
    "the rest of the reason rather than assuming it is true.\n\n"
    "3. GENERIC SIZE OR PROMINENCE. The reason amounts to \"it is a major "
    "player in this sector\", \"it is one of the largest companies here\", "
    "or \"it is a well-known name in this space\". Size is not a mechanism. "
    "Nor is restating a fact from the article without connecting it to this "
    "specific company.\n\n"
    "Judge each company independently against that bar. Rejecting most of "
    "the list is a correct answer, and so is accepting all of it -- do not "
    "aim for a balance, and do not keep a company merely because a lot of "
    "others were rejected. You may not add companies; judge only what is "
    "listed."
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
                                    "description": (
                                        "One line explaining the verdict. Strongly encouraged "
                                        "when belongs is false -- not schema-required, since "
                                        "code here tolerates a missing reason (falls back to "
                                        "a generic one) rather than losing the whole verdict."
                                    ),
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
    (a sector fan-out mention) is never judged and always kept by EITHER
    filter: it makes no company-specific claim to verify, and its rationale
    is a programmatic sector template (see cascade._sector_fanout_mentions),
    not model prose the vagueness guard was written to judge.

    An LLM failure returns the input list minus only the deterministic
    vagueness rejections. Those are computed before the call and are not
    contingent on it: a rationale that is pure hedge is pure hedge whether
    or not the provider is up, and letting a provider outage restore
    content-free analysis to the alert would make the guard useless exactly
    when the pipeline is already degraded.
    """
    judgeable = [c for c in companies if c.ticker]
    if not judgeable:
        return companies

    # Filter 1, deterministic. Runs first and outside the try below so no
    # exception path can skip it.
    rejected: dict[str, str] = {}
    for company in judgeable:
        result = flag_vague_rationale(company.rationale)
        if result.is_vague:
            rejected[company.ticker] = result.reason
            logger.info("vagueness guard dropped %s: %s", company.ticker, result.reason)

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
            return _survivors(companies, rejected)
        arguments = json.loads(tool_call.function.arguments)

        # The whole verdict-processing loop lives inside this same try: this
        # module's contract (see analyze_article's call site, which wraps it
        # in NO try/except of its own) is to be entirely self-contained, so a
        # malformed sub-field here must degrade the same way a malformed
        # top-level response does -- keep every company -- rather than raise
        # and take the whole article down with it. Provider tool-calling is
        # not reliably schema-shaped even at the top level (a model can
        # return "verdicts" as a single object, null, or a list of strings
        # instead of the expected list of objects), so every shape is
        # defensively checked rather than assumed.
        known = set(tickers)
        verdicts = arguments.get("verdicts")
        if not isinstance(verdicts, list):
            verdicts = []
        for verdict in verdicts:
            if not isinstance(verdict, dict):
                continue
            ticker = verdict.get("ticker")
            # Defensive: provider enums are not reliably enforced for nested
            # array items (cascade.py:282). A verdict about a company that is
            # not on the list cannot mean anything. A non-string ticker (e.g.
            # a list) would also raise TypeError on the `in` check below.
            if not isinstance(ticker, str) or ticker not in known:
                continue
            if verdict.get("belongs") is False and ticker not in rejected:
                reason = verdict.get("reason") or "no stated reason"
                rejected[ticker] = reason
                logger.info("verification dropped %s: %s", ticker, reason)

        return _survivors(companies, rejected)
    except Exception as exc:
        logger.warning(
            "verification call failed, keeping every company the vagueness "
            "guard did not already drop: %s", exc,
        )
        return _survivors(companies, rejected)


def _survivors(companies: list[CompanyMention], rejected: dict[str, str]) -> list[CompanyMention]:
    return [c for c in companies if not (c.ticker and c.ticker in rejected)]
