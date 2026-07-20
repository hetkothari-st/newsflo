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
import logging

from openai import RateLimitError

from app.reasoning.playbooks import PLAYBOOKS_TEXT
from app.reasoning.rulebook import RULEBOOK_TEXT

from app.analysis.claude_client import FALLBACK_MODEL, MODEL, SYSTEM_PROMPT
from app.analysis.schemas import (
    CATEGORIES, EVENT_TYPES, SECTOR_DEFINITIONS, SECTORS, TIME_HORIZONS,
    AnalysisOutput, CompanyMention, FactsResult, SectorFinding,
)

logger = logging.getLogger(__name__)

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


# Preserves this session's own hard-won plain-language WHY/HOW quality bar
# (see docs/superpowers/specs/2026-07-19-*-key-insights-quality*, and rules
# 6-8 of the now-deleted app.analysis.claude_client.ANALYSIS_INSTRUCTIONS)
# plus the rulebook/playbook citation discipline (rules 11-15 of the same,
# now-deleted, instructions) that app.pipeline._persist_alert's
# rulebook_ids_json extraction depends on -- both are load-bearing, not
# cosmetic prompt text.
COMPANY_RATIONALE_INSTRUCTIONS = (
    "For each company:\n"
    "- rationale: name the specific mechanism for THAT company -- its "
    "specific role (upstream producer vs refiner vs distributor vs miner: "
    "never assume every company in a sector plays the same role), its "
    "market position, and a real precedent if you know one. Never restate a "
    "price/number the article already reports as if it were analysis -- "
    "explain WHY this specific news moves this specific company, and HOW.\n"
    "- key_points: 1-4 plain-language sentences (full sentences, no word "
    "cap, typically 15-30 words) a reader with ZERO finance background can "
    "read once and immediately understand WHY this affects this company and "
    "HOW. Spell out the causal chain: [what happened] -> [what that changes "
    "for this company -- its costs, sales, profit, what its customers do] "
    "-> [why that's good or bad]. Replace or immediately unpack finance "
    "jargon (never leave \"margin compression\", \"deal pipeline "
    "pressure\", or similar unexplained). Never: (a) restating a "
    "price/number the article already reports; (b) a vague sentiment line "
    "with no mechanism; (c) a generic, always-true company fact untied to "
    "this specific news; (d) a jargon-dense sentence an ordinary reader "
    "would have to look up. Fewer, clearer sentences beat more, vaguer "
    "ones -- 1-2 entries is correct when that's all the genuine mechanism "
    "supports.\n"
    "- reasons: 1-4 short, distinct, individually-citable reasons "
    "supporting the direction call.\n"
    "- evidence_refs: one entry per `reasons` item -- either a rule id from "
    "ECONOMIC REASONING RULES below (e.g. \"RULE_REPO_RATE_CUT\"), a quoted "
    "or closely paraphrased fact from the article (prefix \"article: \"), "
    "or a specific historical precedent you actually know (prefix "
    "\"historical: \").\n"
    "- risks: 0-3 specific risks that could invalidate this call. "
    "assumptions: 0-3 things assumed true that, if wrong, change the call. "
    "unknowns: 0-3 pieces of missing information that would make this call "
    "more reliable.\n"
    "- alternative_hypothesis: one sentence describing a plausible "
    "competing interpretation, or why none is credible.\n"
    "- time_horizon: exactly one of Immediate, Short-Term, Medium-Term, "
    "Long-Term, based on when the mechanism actually plays out.\n\n"
    "Consult the ECONOMIC REASONING RULES and SECTOR PLAYBOOKS below. If a "
    "rule genuinely applies, use it to strengthen your rationale and "
    "include its rule id verbatim as one entry in that company's "
    "evidence_refs. Do not force-fit a rule that doesn't actually apply.\n"
    f"ECONOMIC REASONING RULES:\n{RULEBOOK_TEXT}\n\n"
    f"SECTOR PLAYBOOKS:\n{PLAYBOOKS_TEXT}"
)

_COMPANY_ITEM_PROPERTIES = {
    "name": {"type": "string"},
    "ticker": {"type": ["string", "null"]},
    "direction": {"type": "string", "enum": ["bullish", "bearish"]},
    "magnitude_low": {"type": "number"},
    "magnitude_high": {"type": "number"},
    "rationale": {"type": "string"},
    "key_points": {"type": "array", "items": {"type": "string"}},
    "time_horizon": {"type": "string", "enum": TIME_HORIZONS},
    "reasons": {"type": "array", "items": {"type": "string"}},
    "evidence_refs": {"type": "array", "items": {"type": "string"}},
    "risks": {"type": "array", "items": {"type": "string"}},
    "assumptions": {"type": "array", "items": {"type": "string"}},
    "unknowns": {"type": "array", "items": {"type": "string"}},
    "alternative_hypothesis": {"type": "string"},
}
_COMPANY_ITEM_REQUIRED = [
    "name", "direction", "magnitude_low", "magnitude_high", "rationale", "key_points",
    "time_horizon", "reasons", "evidence_refs", "risks", "assumptions", "unknowns",
    "alternative_hypothesis",
]


def build_company_tool(parent_tickers: list[str] | None) -> dict:
    """parent_tickers=None builds the direct/primary-stage tool (stage 3, no
    parent_ticker field). A non-empty list builds a cascade-stage tool
    (stages 5/7), adding a parent_ticker field enum-constrained to
    parent_tickers so the model cannot invent a nonexistent parent."""
    properties = dict(_COMPANY_ITEM_PROPERTIES)
    required = list(_COMPANY_ITEM_REQUIRED)
    if parent_tickers:
        properties["parent_ticker"] = {"type": "string", "enum": parent_tickers}
        required.append("parent_ticker")
    return {
        "type": "function",
        "function": {
            "name": "record_sector_companies",
            "description": "Record companies affected within each given sector.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sector_companies": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "sector": {"type": "string", "enum": SECTORS},
                                "companies": {
                                    "type": "array",
                                    "items": {
                                        "type": "object", "properties": properties, "required": required,
                                    },
                                },
                            },
                            "required": ["sector", "companies"],
                        },
                    },
                },
                "required": ["sector_companies"],
            },
        },
    }


def _identify_companies(
    client, facts: str, sectors: list[SectorFinding], impact_level: str,
    parent_pool: list[CompanyMention] | None,
) -> list[CompanyMention]:
    """sectors: the sector(s) to find companies within (from a prior
    _identify_sectors call). impact_level: stamped onto every returned
    CompanyMention programmatically (never asked of the LLM). parent_pool:
    for a cascade stage, the companies (from the previous company-stage)
    each returned company must chain from via parent_ticker; None for the
    direct/primary stage (stage 3)."""
    sector_lines = "\n".join(f"- {s.sector} ({s.direction}): {s.mechanism}" for s in sectors)
    if parent_pool is None:
        framing = (
            "For each sector below, name the specific companies genuinely, "
            "directly affected -- both winners and losers where applicable (a "
            "single sector can have companies benefiting AND companies hurt by "
            "the same news, e.g. importers vs exporters on a currency move). "
            "Use your own knowledge of real companies and their actual "
            "business models; do not force-fit a company that doesn't "
            "genuinely fit. Zero companies for a sector is correct when none "
            "genuinely fit."
        )
        parent_context = ""
        parent_tickers = None
    else:
        # Filtered from the SAME iteration so names and tickers can never
        # misalign -- do not build parent_tickers and parent_lines from two
        # separately-filtered lists and zip() them; a parent_pool entry
        # with no ticker would then pair the wrong name with the wrong
        # ticker.
        parent_tickers = [c.ticker for c in parent_pool if c.ticker]
        parent_lines = "\n".join(f"- {c.ticker} ({c.name})" for c in parent_pool if c.ticker)
        framing = (
            "For each sector below, name the specific companies affected as a "
            "ripple from the already-identified companies listed. Every "
            "company you name MUST chain from one of those via parent_ticker "
            "(the exact ticker string) -- a real, specific economic link "
            "(supplier, customer, or close competitor), not merely being in "
            "the same sector. Zero companies for a sector is correct when you "
            "don't have a real, specific one."
        )
        parent_context = f"\n\nMust chain from one of these companies:\n{parent_lines}"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"{framing}\n\n"
                f"Facts: {facts}\n\n"
                f"Sectors:\n{sector_lines}"
                f"{parent_context}\n\n"
                f"{COMPANY_RATIONALE_INSTRUCTIONS}"
            ),
        },
    ]
    tool = build_company_tool(parent_tickers if parent_tickers else None)

    def _call(model: str):
        return client.chat.completions.create(
            model=model,
            max_tokens=8192,
            tools=[tool],
            tool_choice={"type": "function", "function": {"name": "record_sector_companies"}},
            messages=messages,
        )

    try:
        response = _call(MODEL)
    except RateLimitError:
        response = _call(FALLBACK_MODEL)

    message = response.choices[0].message
    tool_calls = message.tool_calls or []
    tool_call = next((tc for tc in tool_calls if tc.function.name == "record_sector_companies"), None)
    if tool_call is None:
        raise ValueError("No record_sector_companies tool_use block")
    arguments = json.loads(tool_call.function.arguments)

    mentions: list[CompanyMention] = []
    for group in arguments.get("sector_companies", []):
        sector = group.get("sector")
        for company in group.get("companies", []):
            mentions.append(CompanyMention(
                name=company["name"], ticker=company.get("ticker"), is_direct=True,
                sector=sector, direction=company["direction"],
                magnitude_low=company["magnitude_low"], magnitude_high=company["magnitude_high"],
                rationale=company["rationale"], key_points=company.get("key_points", []),
                time_horizon=company["time_horizon"], reasons=company.get("reasons", []),
                evidence_refs=company.get("evidence_refs", []), risks=company.get("risks", []),
                assumptions=company.get("assumptions", []), unknowns=company.get("unknowns", []),
                alternative_hypothesis=company.get("alternative_hypothesis"),
                impact_level=impact_level, parent_ticker=company.get("parent_ticker"),
            ))
    return mentions


def analyze_article(client, title: str, content: str) -> AnalysisOutput:
    """Runs the 7-call sector-cascade chain and composes the result into the
    same AnalysisOutput shape app.pipeline.py already consumes. Failure
    handling (see docs/superpowers/specs/2026-07-20-sector-cascade-
    reasoning-design.md): a facts (stage 1) or primary-sector (stage 2)
    failure propagates, failing the whole article -- identical to the old
    single-call analyze_article's behavior. A failure at any later stage
    truncates the pipeline there: everything produced by stages that
    already succeeded is still returned.
    """
    facts_result = _extract_facts(client, title, content)
    primary_sectors = _identify_sectors(client, facts_result.facts, parent_sectors=None)

    all_companies: list = []
    if not primary_sectors:
        return AnalysisOutput(category=facts_result.category, event_type=facts_result.event_type, companies=all_companies)

    try:
        primary_companies = _identify_companies(
            client, facts_result.facts, primary_sectors, impact_level="direct", parent_pool=None,
        )
    except Exception as exc:
        logger.warning("cascade stage 3 (primary companies) failed, truncating: %s", exc)
        primary_companies = []
    all_companies.extend(primary_companies)

    l1_parent_tickers_present = [c for c in primary_companies if c.ticker]
    if l1_parent_tickers_present:
        try:
            l1_sectors = _identify_sectors(client, facts_result.facts, parent_sectors=primary_sectors)
            l1_companies = (
                _identify_companies(
                    client, facts_result.facts, l1_sectors, impact_level="indirect_l1",
                    parent_pool=l1_parent_tickers_present,
                )
                if l1_sectors else []
            )
        except Exception as exc:
            logger.warning("cascade stage 4/5 (L1 cascade sectors/companies) failed, truncating: %s", exc)
            l1_sectors, l1_companies = [], []
        all_companies.extend(l1_companies)

        l2_parent_tickers_present = [c for c in l1_companies if c.ticker]
        if l1_sectors and l2_parent_tickers_present:
            try:
                l2_sectors = _identify_sectors(client, facts_result.facts, parent_sectors=l1_sectors)
                l2_companies = (
                    _identify_companies(
                        client, facts_result.facts, l2_sectors, impact_level="indirect_l2",
                        parent_pool=l2_parent_tickers_present,
                    )
                    if l2_sectors else []
                )
            except Exception as exc:
                logger.warning("cascade stage 6/7 (L2 cascade sectors/companies) failed, truncating: %s", exc)
                l2_companies = []
            all_companies.extend(l2_companies)

    return AnalysisOutput(category=facts_result.category, event_type=facts_result.event_type, companies=all_companies)
