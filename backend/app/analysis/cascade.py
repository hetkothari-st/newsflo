"""Sector-first, multi-step cascade reasoning: replaces the old single-call
app.analysis.claude_client.analyze_article with a staged chain (facts ->
primary sectors -> primary companies -> cascade sectors L1 -> cascade
companies L1 -> cascade sectors L2 -> cascade companies L2). See
docs/superpowers/specs/2026-07-20-sector-cascade-reasoning-design.md.

Originally a fixed 7 calls total. Confirmed in production that bundling
every cascade sector's company lookup into one call degrades to an empty
response once there are several sectors (each company's required fields
are verbose enough that 5-7 sectors' worth doesn't fit one tool call's
token budget, and the model returns nothing rather than a partial result)
-- so cascade company identification (stages 5/7) now makes one call PER
cascade sector via _identify_cascade_companies_per_sector, making the
total call count scale with how many cascade sectors are actually found
(typically 1 for facts + 1-2 for primary sectors/companies + N for each
cascade level's sectors and companies), not a fixed 7.

All three stage functions below (_extract_facts, _identify_sectors,
_identify_companies) are pure: given a client and inputs, they make exactly
one LLM call and return parsed, validated output, raising on a genuinely
malformed response (no tool_use block). The orchestrator (analyze_article)
is responsible for sequencing them and for the truncate-on-failure
behavior described in the design spec.
"""
import json
import logging

from openai import RateLimitError

from app.reasoning.playbooks import PLAYBOOKS_TEXT
from app.reasoning.rulebook import CHAINS, EDGE_RELATIONS, NODE_SECTOR, RULEBOOK_TEXT, get_chain

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
            "ripple/knock-on effect, not the news's own direct subject.\n\n"
            "Real financial and economic news almost always ripples beyond its "
            "own direct sector -- a genuine cascade is the norm, not the "
            "exception. Actively look for it through channels like: credit/"
            "loan cost (a rate or lending-policy move changes borrowing costs "
            "for buyers of cars, homes, appliances, etc. -- e.g. a bank's own "
            "move affects auto and consumer-durables sectors as EMI/financing "
            "costs shift); input costs (an oil, metals, or currency move "
            "changes production costs for downstream manufacturers); consumer "
            "spending power (a rate, inflation, or currency move changes how "
            "much households can spend, affecting retail/fmcg/travel); trade/"
            "logistics (a shipping, tariff, or currency move affects importers "
            "and exporters differently). Example: an RBI/lending-rate story's "
            "primary sector is banking, but it genuinely cascades to auto "
            "(car-loan EMIs), construction_realestate (mortgage rates), and "
            "consumer_durables (financed purchases) -- these are not a stretch, "
            "they are the direct, well-known transmission mechanism of a rate "
            "change. Only skip a cascade sector if you genuinely cannot state "
            "a specific mechanism for it -- do not skip one just because "
            "naming it takes more reasoning than stopping at the primary "
            "sector.\n\n"
            "That said, this only applies when the news itself has a genuinely "
            "BROAD economic mechanism (a rate/policy change, a commodity or "
            "currency move, a trade/regulatory shift) that plausibly touches "
            "spending, costs, or credit economy-wide. A NARROW story -- one "
            "company launching a specific product, a single bilateral deal, "
            "one company's own earnings -- does NOT automatically deserve the "
            "same cascade depth just because cascade is normally expected. "
            "For a narrow story, ask: does this specific event genuinely move "
            "the economics of an ENTIRE other sector, or only a couple of "
            "directly, specifically involved companies (a close competitor, "
            "the literal counterparty in the deal)? If it's the latter, "
            "return few or zero cascade sectors -- that is the correct, "
            "honest answer for a narrow story, not a failure to find enough. "
            "A vague, generic story about \"changing consumer spending "
            "habits\" or \"increased engagement\" is not a real mechanism -- "
            "if that is the only link you can articulate for a sector, leave "
            "it out. For each sector you DO include, give its direction, a "
            "one-line mechanism, and which of the already-identified sectors "
            "it's rippling from (parent_sector)."
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
    findings = [SectorFinding.model_validate(s) for s in arguments.get("sectors", [])]
    # Defensive filter: the tool schema enum-constrains `sector` to SECTORS,
    # but that constraint isn't always strictly enforced server-side for a
    # nested array item (confirmed in production: a real response returned
    # "aviation", not a SECTORS value -- it's only mentioned inside
    # railways_transport's own definition text). An off-taxonomy sector
    # here doesn't just mean one bad entry: the NEXT call's company tool
    # schema also enum-constrains `sector`, and feeding it a sector name
    # outside that enum can make the model unable to satisfy the schema at
    # all, degrading the whole call to an empty response. Drop rather than
    # coerce to "other" -- the finding's own mechanism text is written for
    # the specific (invalid) sector it named, not for "other", so
    # relabeling it would misrepresent the reasoning ("omit rather than
    # mismatch", same discipline as app.companies.resolution).
    return [f for f in findings if f.sector in SECTORS]


# Preserves this session's own hard-won plain-language WHY/HOW quality bar
# (see docs/superpowers/specs/2026-07-19-*-key-insights-quality*, and rules
# 6-8 of the now-deleted app.analysis.claude_client.ANALYSIS_INSTRUCTIONS)
# plus the rulebook/playbook citation discipline (rules 11-15 of the same,
# now-deleted, instructions) that app.pipeline._persist_alert's
# rulebook_ids_json extraction depends on -- both are load-bearing, not
# cosmetic prompt text.
_COMPANY_FIELD_INSTRUCTIONS = (
    "- ticker: write the EXACT ticker symbol as it trades, including the "
    "exchange suffix -- Indian companies almost always end in \".NS\" (NSE, "
    "e.g. \"MARUTI.NS\", \"RELIANCE.NS\", \"HINDUNILVR.NS\") or occasionally "
    "\".BO\" (BSE); global companies typically have no suffix (e.g. \"BP\", "
    "\"AAPL\"). This match must be exact -- a ticker off by the suffix alone "
    "(e.g. \"MARUTI\" instead of \"MARUTI.NS\") will fail to resolve to a "
    "real record and the company will be silently dropped. If you are not "
    "confident of the exact ticker, set it to null rather than guessing a "
    "close-but-wrong symbol.\n"
    "- name: the company's real, commonly-used legal name (e.g. \"Maruti "
    "Suzuki India Ltd.\", not an invented or shortened variant) -- if the "
    "ticker above is null or turns out wrong, this name is the only other "
    "way the company can be matched to a real record.\n"
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
    "- risks: 0-3 specific risks that could invalidate this call. "
    "assumptions: 0-3 things assumed true that, if wrong, change the call. "
    "unknowns: 0-3 pieces of missing information that would make this call "
    "more reliable.\n"
    "- alternative_hypothesis: one sentence describing a plausible "
    "competing interpretation, or why none is credible.\n"
    "- time_horizon: exactly one of Immediate, Short-Term, Medium-Term, "
    "Long-Term, based on when the mechanism actually plays out.\n\n"
    "Never invent a specific-sounding number, study, or historical case "
    "(e.g. \"UK data from 2018-2020 showed X% decline\") that you are not "
    "genuinely confident is real -- a fabricated statistic dressed up as "
    "evidence is worse than an honest qualitative statement with no number "
    "at all. If you don't have a real, specific precedent, describe the "
    "mechanism in plain qualitative terms instead of manufacturing one."
)

# Direct-stage (stage 3) gets the full rulebook/playbook reference block --
# it's the highest-value, lowest-cardinality call (one company list, no
# nested per-sector grouping to also reason about) so the extra prompt
# weight doesn't risk starving the model's attention. evidence_refs may
# cite a rule id from this block.
COMPANY_RATIONALE_INSTRUCTIONS = (
    f"{_COMPANY_FIELD_INSTRUCTIONS}\n"
    "- evidence_refs: one entry per `reasons` item -- either a rule id from "
    "ECONOMIC REASONING RULES below (e.g. \"RULE_REPO_RATE_CUT\"), a quoted "
    "or closely paraphrased fact from the article (prefix \"article: \"), "
    "or a specific historical precedent you actually know (prefix "
    "\"historical: \").\n\n"
    "Consult the ECONOMIC REASONING RULES and SECTOR PLAYBOOKS below. If a "
    "rule genuinely applies, use it to strengthen your rationale and "
    "include its rule id verbatim as one entry in that company's "
    "evidence_refs. Do not force-fit a rule that doesn't actually apply.\n"
    f"ECONOMIC REASONING RULES:\n{RULEBOOK_TEXT}\n\n"
    f"SECTOR PLAYBOOKS:\n{PLAYBOOKS_TEXT}"
)

# Cascade stages (5/7) drop the rulebook/playbook block -- those calls
# already carry a longer prompt (multiple sectors + a parent-company list +
# the anti-division-naming rules below), and a real production test showed
# the combined weight pushed the model to return a degenerate empty tool
# call instead of reasoning through it. evidence_refs here is scoped to
# what's actually available in this call (article facts + real-world
# knowledge), not a rulebook that isn't provided.
CASCADE_COMPANY_RATIONALE_INSTRUCTIONS = (
    f"{_COMPANY_FIELD_INSTRUCTIONS}\n"
    "- evidence_refs: one entry per `reasons` item -- either a quoted or "
    "closely paraphrased fact from the article (prefix \"article: \"), or "
    "a specific historical precedent you actually know (prefix "
    "\"historical: \")."
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
            "the same sector.\n\n"
            "A sector reaching this stage already has a stated, genuine "
            "mechanism (see its one-line reason below) -- that mechanism is "
            "real, but it is SECTOR-level, not yet company-level. Your job "
            "has two parts, both required: (1) name real companies the "
            "mechanism genuinely reaches, and (2) for each one, state HOW "
            "that specific mechanism actually hits THAT company's own "
            "business (its own revenue exposure, cost structure, or "
            "customer base) -- not a copy of the sector's one-line reason, "
            "and not a generic description of what the company does. Being "
            "a large, well-known name in the sector is NOT by itself a "
            "reason to include a company -- you still need a genuine, "
            "specific reason the mechanism reaches that company's own "
            "business, not just its sector membership. A cascade sector "
            "caused by rising import/freight costs genuinely reaching an "
            "import-dependent manufacturer in that sector is a real link; "
            "the same sector reaching an unrelated company merely because "
            "it's also big and well-known in that sector is NOT -- if you "
            "cannot state the specific mechanism for a company beyond "
            "\"it's a major player in this sector,\" leave it out. Naming "
            "1-3 real companies per sector with a genuine mechanism each is "
            "the normal, expected outcome for a sector whose own mechanism is "
            "genuinely broad (a rate/policy/commodity/currency move reaching "
            "costs or spending economy-wide) -- reach for that before "
            "concluding there is nothing to name. But do not force it: if "
            "the sector's mechanism only plausibly reaches through vague "
            "language like \"changing consumer spending\" or \"increased "
            "engagement\" rather than something concrete (a specific cost, "
            "a specific revenue line, a specific customer relationship), "
            "that is not a real company-level link -- zero companies for "
            "that sector is the correct, honest answer, not a shortfall. "
            "Never invent a precise-sounding statistic, study, or "
            "historical case you are not genuinely confident is real to "
            "make a weak connection sound stronger -- an honest \"this link "
            "is real but modest\" beats a fabricated data point every "
            "time.\n\n"
            "Each company you name MUST be a real, separate, independently "
            "publicly-traded company with its own ticker -- NEVER a division, "
            "segment, subsidiary, or business unit of a company you (or the "
            "parent list above) already named. Do not write a name like "
            "\"[Company] - [Segment] Division\" or \"[Company]'s [Segment] "
            "arm\" -- that is the SAME company again, not a genuine cascade "
            "link, and it cannot be resolved to a real database row. If your "
            "first instinct is a division/segment of an already-named "
            "company, name a genuinely different, separate company in that "
            "sector instead -- do not omit the sector just because your "
            "first instinct was a segment name."
        )
        parent_context = f"\n\nMust chain from one of these companies:\n{parent_lines}"

    rationale_instructions = COMPANY_RATIONALE_INSTRUCTIONS if parent_pool is None else CASCADE_COMPANY_RATIONALE_INSTRUCTIONS
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"{framing}\n\n"
                f"Facts: {facts}\n\n"
                f"Sectors:\n{sector_lines}"
                f"{parent_context}\n\n"
                f"{rationale_instructions}"
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


def _identify_cascade_companies_per_sector(
    client, facts: str, sectors: list[SectorFinding], impact_level: str, parent_pool: list[CompanyMention],
) -> tuple[list[CompanyMention], list[dict]]:
    """Calls _identify_companies ONCE PER SECTOR rather than bundling every
    cascade sector into one call. Confirmed in production: bundling 5-7
    cascade sectors (each company requires a long rationale/key_points/
    reasons/evidence_refs/risks/assumptions/unknowns block, easily 500+
    tokens) into a single max_tokens=8192 tool call made the model return a
    degenerate empty response (no exception, just `{}` -- silently zero
    companies) even though every sector had a genuine, findable answer. The
    SAME sectors, called one at a time, reliably produced rich, correct,
    multi-company results. Direct/primary companies (stage 3) do not use
    this -- that stage empirically has few enough sectors (the article's
    own direct subject, not a wide cascade fan-out) that bundling is fine.

    A failure on one sector is retried once (2 attempts total) before being
    recorded as a gap dict in the returned gaps list -- never silently
    dropped, so a genuine transient failure (rate limit, malformed
    response) is distinguishable from "this sector genuinely has no
    cascade companies" (which returns normally with an empty list, not a
    gap). A gap on one sector does not lose another sector's results.
    """
    mentions: list[CompanyMention] = []
    gaps: list[dict] = []
    for sector in sectors:
        last_error: str | None = None
        succeeded = False
        for attempt in range(2):  # try once, retry once
            try:
                mentions.extend(_identify_companies(client, facts, [sector], impact_level=impact_level, parent_pool=parent_pool))
                succeeded = True
                break
            except Exception as exc:
                last_error = str(exc)
        if not succeeded:
            logger.warning("cascade company lookup for sector %r failed after retry, recording gap: %s", sector.sector, last_error)
            gaps.append({
                "sector": sector.sector,
                "impact_level": impact_level,
                # parent_pool is a POOL of companies this sector's lookup
                # chains from, not a single one -- there is no single
                # correct parent_ticker to attribute a whole-sector
                # failure to, so this is intentionally left None rather
                # than picking (and thereby misrepresenting) just the
                # first entry.
                "parent_ticker": None,
                "attempts": 2,
                "last_error": last_error,
            })
    return mentions, gaps


_EDGE_VERIFY_FRAMING = (
    "For each proposed transmission-chain edge below, decide whether it "
    "genuinely applies to THIS specific article -- return applicable=true "
    "if the mechanism it describes is genuinely at play here, or "
    "applicable=false with a one-line pruned_reason if it does not "
    "(e.g. the article doesn't actually support that specific link, or "
    "explicitly contradicts it). Do NOT invent a new mechanism, sector, or "
    "edge beyond what's proposed below -- your job here is to verify, not "
    "to expand the chain.\n\n"
    "You MAY additionally propose direct company-to-company edges, but "
    "ONLY between the companies listed below (using their exact ticker "
    "strings) and ONLY where you have a specific, genuine economic link "
    "(supplier, customer, or close competitor) between those two named "
    "companies -- never a company not in this list, and never a vague or "
    "generic connection. Zero additional edges is the correct, honest "
    "answer when no genuine company-to-company link exists -- do not force "
    "one to look thorough."
)


def build_edge_verify_tool(valid_tickers: list[str]) -> dict:
    """valid_tickers: every already-resolved company's ticker in this
    article's cascade -- both endpoints of any llm_only company edge are
    enum-constrained to this list (same enum-constraint discipline as
    build_company_tool's parent_ticker), so the model can never invent a
    company. Omitted entirely when fewer than 2 tickers are available (no
    two distinct companies to link)."""
    properties = {
        "verifications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "applicable": {"type": "boolean"},
                    "pruned_reason": {"type": "string"},
                },
                "required": ["index", "applicable"],
            },
        },
    }
    required = ["verifications"]
    if len(valid_tickers) >= 2:
        properties["llm_only_edges"] = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "from_ticker": {"type": "string", "enum": valid_tickers},
                    "to_ticker": {"type": "string", "enum": valid_tickers},
                    "relation": {"type": "string", "enum": EDGE_RELATIONS},
                    "direction": {"type": "string", "enum": ["bullish", "bearish"]},
                    "note": {"type": "string"},
                },
                "required": ["from_ticker", "to_ticker", "relation", "direction", "note"],
            },
        }
    return {
        "type": "function",
        "function": {
            "name": "record_edge_verification",
            "description": "Verify proposed transmission-chain edges and optionally add company-to-company edges.",
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


def _sector_attachment_edges(companies: list[CompanyMention]) -> list[dict]:
    """Purely programmatic -- no LLM call. Connects every resolved company
    to its own sector node so the graph is fully traversable news ->
    mechanism -> sector -> company, regardless of whether this article's
    event_type has a CHAINS entry at all. Tagged source="llm_only" per this
    plan's Global Constraints (the source enum has no 4th value for
    "programmatic", not a claim the LLM produced these specific edges)."""
    edges = []
    for company in companies:
        if not company.sector or not company.ticker:
            continue
        edges.append({
            "from": {"kind": NODE_SECTOR, "label": company.sector},
            "to": {"kind": "company", "label": company.ticker},
            "relation": "demand",
            "direction": company.direction,
            "note": f"{company.name} is one of the companies the {company.sector} sector's cascade reaches.",
            "source": "llm_only",
        })
    return edges


def _generate_edges(client, facts: str, event_type: str | None, companies: list[CompanyMention]) -> list[dict]:
    """Propose (via CHAINS), verify (via one LLM call, never invents), and
    always attach every company to its sector node. See this plan's Global
    Constraints for the edge dict shape and the degrade-safely contract."""
    edges: list[dict] = []
    proposed = get_chain(event_type)

    if proposed:
        valid_tickers = [c.ticker for c in companies if c.ticker]
        tool = build_edge_verify_tool(valid_tickers)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"{_EDGE_VERIFY_FRAMING}\n\n"
                    f"Facts: {facts}\n\n"
                    "Proposed edges:\n" + "\n".join(
                        f'{i}. {e["from"]["label"]} -[{e["relation"]}]-> {e["to"]["label"]} ({e["direction"]}): {e["note"]}'
                        for i, e in enumerate(proposed)
                    ) + "\n\n"
                    "Companies available for llm_only edges:\n" + "\n".join(
                        f"- {c.ticker} ({c.name}, {c.sector})" for c in companies if c.ticker
                    )
                ),
            },
        ]
        try:
            response = client.chat.completions.create(
                model=FALLBACK_MODEL, max_tokens=2048, tools=[tool],
                tool_choice={"type": "function", "function": {"name": "record_edge_verification"}},
                messages=messages,
            )
            message = response.choices[0].message
            tool_call = next((tc for tc in (message.tool_calls or []) if tc.function.name == "record_edge_verification"), None)
            if tool_call is None:
                raise ValueError("No record_edge_verification tool_use block")
            arguments = json.loads(tool_call.function.arguments)
            verifications = {v["index"]: v for v in arguments.get("verifications", [])}

            for i, proposed_edge in enumerate(proposed):
                v = verifications.get(i)
                if v is None:
                    edges.append({
                        **proposed_edge, "source": "rulebook_verified",
                        "note": f"{proposed_edge['note']} [UNVERIFIED: model returned no verification for this edge]",
                    })
                elif v.get("applicable", True):
                    edges.append({**proposed_edge, "source": "rulebook_verified"})
                else:
                    pruned_reason = v.get("pruned_reason") or "marked not applicable"
                    edges.append({
                        **proposed_edge, "source": "rulebook_pruned",
                        "note": f"{proposed_edge['note']} [PRUNED: {pruned_reason}]",
                    })

            for llm_edge in arguments.get("llm_only_edges", []):
                edges.append({
                    "from": {"kind": "company", "label": llm_edge["from_ticker"]},
                    "to": {"kind": "company", "label": llm_edge["to_ticker"]},
                    "relation": llm_edge["relation"], "direction": llm_edge["direction"],
                    "note": llm_edge["note"], "source": "llm_only",
                })
        except Exception as exc:
            logger.warning("edge verification call failed, falling back to unverified proposed chain: %s", exc)
            edges = [
                {**e, "source": "rulebook_verified", "note": f"{e['note']} [UNVERIFIED: verification call failed]"}
                for e in proposed
            ]

    edges.extend(_sector_attachment_edges(companies))
    return edges


def analyze_article(client, title: str, content: str) -> AnalysisOutput:
    """Runs the sector-cascade chain (see module docstring for why the call
    count now scales with cascade sector count) and composes the result into the
    same AnalysisOutput shape app.pipeline.py already consumes. Failure
    handling (see docs/superpowers/specs/2026-07-20-sector-cascade-
    reasoning-design.md): a facts (stage 1) or primary-sector (stage 2)
    failure propagates, failing the whole article -- identical to the old
    single-call analyze_article's behavior. A failure at any later stage
    truncates the pipeline there: everything produced by stages that
    already succeeded is still returned. Per-sector cascade-company
    failures (stages 5/7) are retried and, if still unresolved, recorded
    as gaps rather than truncating the pipeline (see
    _identify_cascade_companies_per_sector).
    """
    facts_result = _extract_facts(client, title, content)
    primary_sectors = _identify_sectors(client, facts_result.facts, parent_sectors=None)

    all_companies: list = []
    all_gaps: list[dict] = []
    if not primary_sectors:
        return AnalysisOutput(
            category=facts_result.category, event_type=facts_result.event_type,
            companies=all_companies, gaps=all_gaps,
        )

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
        except Exception as exc:
            logger.warning("cascade stage 4 (L1 cascade sectors) failed, truncating: %s", exc)
            l1_sectors = []
        if l1_sectors:
            l1_companies, l1_gaps = _identify_cascade_companies_per_sector(
                client, facts_result.facts, l1_sectors, impact_level="indirect_l1",
                parent_pool=l1_parent_tickers_present,
            )
        else:
            l1_companies, l1_gaps = [], []
        all_companies.extend(l1_companies)
        all_gaps.extend(l1_gaps)

        l2_parent_tickers_present = [c for c in l1_companies if c.ticker]
        if l1_sectors and l2_parent_tickers_present:
            try:
                l2_sectors = _identify_sectors(client, facts_result.facts, parent_sectors=l1_sectors)
            except Exception as exc:
                logger.warning("cascade stage 6 (L2 cascade sectors) failed, truncating: %s", exc)
                l2_sectors = []
            if l2_sectors:
                l2_companies, l2_gaps = _identify_cascade_companies_per_sector(
                    client, facts_result.facts, l2_sectors, impact_level="indirect_l2",
                    parent_pool=l2_parent_tickers_present,
                )
            else:
                l2_companies, l2_gaps = [], []
            all_companies.extend(l2_companies)
            all_gaps.extend(l2_gaps)

    try:
        edges = _generate_edges(client, facts_result.facts, facts_result.event_type, all_companies)
    except Exception as exc:
        logger.warning("edge generation failed entirely, returning no edges: %s", exc)
        edges = []

    return AnalysisOutput(
        category=facts_result.category, event_type=facts_result.event_type,
        companies=all_companies, gaps=all_gaps, edges=edges,
    )
