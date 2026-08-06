"""Sector-first, multi-step cascade reasoning: replaces the old single-call
app.analysis.claude_client.analyze_article with a staged chain (facts ->
primary sectors -> primary companies -> cascade sectors L1 -> cascade
companies L1 -> cascade sectors L2 -> cascade companies L2). See
docs/superpowers/specs/2026-07-20-sector-cascade-reasoning-design.md.

Originally a fixed 7 calls total. Confirmed in production that bundling
several sectors' company lookup into one call degrades to an empty
response (each company's required fields are verbose enough that 5-7
sectors' worth doesn't fit one tool call's token budget, and the model
returns nothing rather than a partial result) and, worse, overflows the
providers' per-minute token ceilings outright (a 413, i.e. zero companies)
-- so EVERY company-identification stage, direct (3) and cascade (5/7)
alike, now makes one call PER SECTOR via _identify_companies_per_sector.
The total call count therefore scales with how many sectors are actually
found (1 for facts + 1 for primary sectors + N per sector at each company
stage + 1 per cascade sector level), not a fixed 7.

All three stage functions below (_extract_facts, _identify_sectors,
_identify_companies) are pure: given a client and inputs, they issue one
logical LLM call and return parsed, validated output, raising on a
genuinely malformed response (no tool_use block). The orchestrator
(analyze_article) is responsible for sequencing them and for the
truncate-on-failure behavior described in the design spec.

"One logical call" now means up to TOOL_CALL_ATTEMPTS physical attempts:
every forced tool call in this module goes through _retry_forced_tool_call,
which retries the identical request when the model returns garbage instead
of a usable tool call (no tool_use block / 400 tool_use_failed /
unparseable arguments JSON). See that helper and
_is_stochastic_tool_failure for the exact allow-list and for why rate
limits, auth failures, and 413s are deliberately NOT retried there.
"""
import json
import logging

from openai import BadRequestError, RateLimitError

from app.reasoning.playbooks import PLAYBOOKS_TEXT
from app.reasoning.rulebook import (
    CHAIN_FALLBACK_KEEP_EVENT_TYPES, CHAINS, EDGE_RELATIONS, NODE_SECTOR, RULEBOOK_DIGEST,
    RULEBOOK_TEXT, get_chain,
)

from app.analysis.claude_client import (
    FALLBACK_MODEL, GROQ_TPM_CEILING, MODEL, SYSTEM_PROMPT, tier_kwargs,
)
from app.analysis.schemas import (
    CATEGORIES, EVENT_TYPES, SECTOR_DEFINITIONS, SECTORS, TIME_HORIZONS,
    AnalysisOutput, CompanyMention, FactsResult, SectorFinding,
)
from app.analysis.verification import verify_companies
from app.companies.candidates import (
    MAX_CANDIDATES_PER_PROMPT, candidate_companies, candidate_tickers, format_candidates,
)
from app.companies.supply_links import prompting as supply_link_prompting
from app.models import Company

logger = logging.getLogger(__name__)

# Every forced tool call in this module (tool_choice pinned to one function)
# gets this many attempts before it gives up and raises. Confirmed repeatedly
# in production: the SAME article, minutes apart, produced "no record_sectors
# tool_use block" (model answered in prose), a 400 tool_use_failed with a
# trailing `"}` artifact, a 400 tool_use_failed with an empty generation
# ("Tool choice is required, but model did not call a tool"), and once a valid
# payload wrapped in a ```json fence instead of a tool call -- and the
# identical prompt succeeded on a later attempt. These are stochastic
# small-model failures (openai/gpt-oss-20b, llama-3.3-70b-versatile on Groq),
# not deterministic ones, so a bounded retry of the identical request is the
# correct remedy. 3 keeps the worst case bounded (and, in _identify_companies,
# multiplies with the model-fallback ladder rather than replacing it).
TOOL_CALL_ATTEMPTS = 3


class MissingToolCallError(ValueError):
    """A 200 OK response that carried no tool_use block for the forced tool
    -- the model answered in prose (or in a markdown ```json fence) despite
    tool_choice pinning it to exactly one function.

    A distinct type rather than a bare ValueError so _is_stochastic_tool_failure
    can retry THIS and nothing else that happens to be a ValueError: pydantic's
    ValidationError is a ValueError subclass too, and a schema our own code
    can no longer satisfy is a real bug that must surface immediately, not be
    retried three times and then re-raised. Still subclasses ValueError so
    existing callers/tests that catch ValueError keep working."""


def _is_tool_use_failed(exc: Exception) -> bool:
    """True only for Groq's 400 `code: "tool_use_failed"` -- the model
    emitted a malformed tool-call blob (confirmed live: a llama-style
    `<function=record_sector_companies>{...}` string with unbalanced
    brackets, and separately an empty generation reported as "Tool choice is
    required, but model did not call a tool") that Groq's parser could not
    turn into a tool call at all.

    Matches structurally on BadRequestError.code, never on the exception's
    message text: that message embeds the model's entire failed generation
    verbatim, which is long and unstable content to substring-match against.
    A BadRequestError with any OTHER code (e.g. a genuinely malformed schema
    on our side) must NOT match here -- see _call_with_model_fallback's own
    docstring for why that distinction matters."""
    return isinstance(exc, BadRequestError) and exc.code == "tool_use_failed"


def _is_stochastic_tool_failure(exc: Exception) -> bool:
    """True for the three ways a forced tool call comes back as garbage the
    model could plausibly get right on an identical retry:

      1. MissingToolCallError -- 200 OK, no tool_use block (prose, or a
         ```json fence, instead of a tool call).
      2. A 400 `tool_use_failed` -- the provider itself could not parse the
         model's tool-call blob.
      3. json.JSONDecodeError on the tool arguments -- a tool call came back
         but its `arguments` string is not valid JSON (confirmed live: a
         trailing `"}` artifact).

    This is a strict ALLOW-list, not a deny-list, and that is deliberate.
    Everything else propagates on the first failure:

      - RateLimitError -- already handled by model/key rotation
        (_call_with_model_fallback, and the key rotation in claude_client);
        hammering a rate-limited endpoint two more times makes it worse.
      - AuthenticationError / any other 4xx -- a bad key or a malformed
        schema on OUR side is deterministic; retrying only delays the loud
        failure that should surface it.
      - 413 "Request too large" -- retrying the IDENTICAL oversized prompt
        cannot succeed. The direct-company stage's existing slim-prompt retry
        (a genuinely DIFFERENT, shorter prompt) is the right remedy there.

    A deny-list would have quietly swept all of those in as new failure modes
    appear, which is exactly the drift this helper exists to prevent."""
    if isinstance(exc, MissingToolCallError):
        return True
    if isinstance(exc, json.JSONDecodeError):
        return True
    return _is_tool_use_failed(exc)


def _retry_forced_tool_call(attempt_fn, *, stage: str, attempts: int = TOOL_CALL_ATTEMPTS):
    """Run `attempt_fn` up to `attempts` times, retrying ONLY the stochastic
    garbage-output failures `_is_stochastic_tool_failure` recognises.

    `attempt_fn` must perform the whole forced-tool-call round trip -- issue
    the request AND extract/parse the tool arguments -- because two of the
    three retryable failures (no tool_use block, unparseable arguments)
    happen after the HTTP call returns 200. Anything it raises that is not a
    stochastic failure propagates immediately, untouched; so does the final
    attempt's failure, which callers already handle (analyze_article
    truncates the pipeline at the failed stage).

    The single shared implementation is the point: every forced-tool-call
    stage in this module routes through here, so the retry policy cannot
    drift between stages the way four pasted try/excepts would.

    Each retry logs at WARNING with the stage name and attempt number, so the
    real production failure rate of these calls is measurable from logs
    rather than invisible behind a silent recovery."""
    for attempt in range(1, attempts + 1):
        try:
            return attempt_fn()
        except Exception as exc:
            if attempt >= attempts or not _is_stochastic_tool_failure(exc):
                raise
            logger.warning(
                "%s: malformed forced tool call on attempt %d/%d, retrying: %s",
                stage, attempt, attempts, exc,
            )
    raise AssertionError("unreachable: the loop above either returns or raises")


def _forced_tool_arguments(response, tool_name: str, context: str = "") -> dict:
    """Pull the forced tool call out of `response` and parse its JSON
    arguments. Raises MissingToolCallError when the model returned no such
    tool call, or json.JSONDecodeError when the arguments blob is malformed
    -- both retryable classes, raised identically for every stage so
    _retry_forced_tool_call sees one consistent shape."""
    message = response.choices[0].message
    tool_calls = message.tool_calls or []
    tool_call = next((tc for tc in tool_calls if tc.function.name == tool_name), None)
    if tool_call is None:
        raise MissingToolCallError(f"No {tool_name} tool_use block{context}")
    return json.loads(tool_call.function.arguments)


FACTS_INSTRUCTIONS = (
    "Read this news article closely and extract its core facts and economic "
    "mechanism -- what actually happened, the key entities/numbers/geography "
    "involved, and WHY it matters economically.\n\n"
    "Write down the concrete specifics the article states: the real-world "
    "entities it NAMES (companies, institutions, regulators, governments, "
    "countries, products), the figures and dates, the stated cause, and "
    "whether the event is officially confirmed or is an unverified report, "
    "rumor, or denied claim. Every later step of this analysis -- including "
    "the plain-language reader summary, the per-company explanations, and "
    "the timeline -- reads ONLY what you write here and never the article "
    "again, so a specific the article states and you omit is lost for the "
    "whole analysis.\n\n"
    "What you must NOT do is infer: do not name companies or sectors the "
    "article does not itself name, and do not judge which of them are "
    "affected or in which direction -- naming the affected universe is a "
    "later step's job. Report the article's ground truth; leave the "
    "reasoning about consequences to the steps that follow.\n\n"
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
                            "prose. Name the entities the article itself names and keep "
                            "its figures, dates and confirmed/unconfirmed status; do NOT "
                            "add companies or sectors it doesn't name, and do not judge "
                            "which are affected."
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

    def _attempt() -> dict:
        response = client.chat.completions.create(
            model=FALLBACK_MODEL,
            max_tokens=1024,
            tools=[build_facts_tool()],
            tool_choice={"type": "function", "function": {"name": "record_facts"}},
            messages=messages,
            **tier_kwargs("extract_facts"),
        )
        return _forced_tool_arguments(response, "record_facts", f" for article: {title!r}")

    arguments = _retry_forced_tool_call(_attempt, stage="extract_facts")
    # Validation stays OUTSIDE the retry on purpose: a ValidationError here
    # means well-formed JSON that our schema rejects, which is not the
    # stochastic garbage class -- see _is_stochastic_tool_failure.
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
            "FIRST, classify the event before naming anything: is it "
            "fundamentally bullish, bearish, or neutral? TEMPORARY or "
            "STRUCTURAL? COMPANY-SPECIFIC or INDUSTRY-WIDE? What actually "
            "drives the market reaction (demand destruction/acceleration, "
            "timing delay, margin pressure, cost inflation, competitive "
            "pressure, execution risk, regulatory risk, sentiment only, "
            "one-time event)? A company-specific, temporary event -- one "
            "firm's earnings miss, stock move, CEO commentary, or execution "
            "stumble -- usually affects ONLY that company's own sector, and "
            "often not even that: it is NOT evidence about its industry, its "
            "theme, or companies that merely share a buzzword with it.\n\n"
            "THEN identify EVERY financial, business, or economic sector this "
            "news directly reaches -- not just the single most obvious one. A "
            "real event almost always lands on several sectors at once: the "
            "one the story is literally about, plus every other sector whose "
            "own economics the SAME event touches directly. Work through the "
            "transmission channels deliberately, one at a time, before you "
            "stop: who manufactures the thing involved, who supplies its "
            "components and raw materials, who buys or operates it, who "
            "maintains and services it, who builds or runs the infrastructure "
            "it depends on, who finances or insures it, who regulates it, and "
            "who competes with it. Include a sector whenever you can state a "
            "specific channel like that for it. Stopping at the headline "
            "sector while three or four others have a genuine, statable "
            "channel is a failure of thoroughness, not caution -- a later "
            "step re-reads every company you surface and removes the ones "
            "that do not hold up, so a sector with a real channel is not "
            "risky to name; a sector with no channel is.\n\n"
            "For each, give its direction "
            "(bullish/bearish) and a one-line mechanism explaining WHY that "
            "sector is affected. Zero sectors is a correct answer when nothing "
            "in the facts genuinely supports one -- this is common and "
            "expected, not a failure: an accident, disaster, crime, or "
            "human-interest story has zero real sectors unless the facts "
            "themselves state a concrete economic consequence (e.g. a "
            "disaster that destroys a named facility, or triggers a stated "
            "insurance/supply-chain effect). Do not manufacture a mechanism "
            "just to have something to report -- 'this could affect "
            "sentiment', 'this relates to the broader economy', or 'this is "
            "part of the AI/EV/green-energy theme' is not a real mechanism. "
            "The instruction above to be thorough does NOT weaken this: "
            "breadth means not missing a sector that has a real channel, "
            "never inventing a channel so that a sector can be listed. A "
            "story with no economic mechanism at all still returns zero "
            "sectors, however thorough you are being."
        )
        framing += (
            "\n\nConsult the KNOWN TRANSMISSION CHAINS reference below. When a "
            "chain's trigger genuinely matches these facts, follow its sector "
            "branches -- adapted to this article's specifics, and dropping any "
            "branch whose stated condition doesn't hold here. When none "
            "matches, reason from first principles. Never include a sector "
            "just because it appears in a chain -- the mechanism must hold "
            "for THIS article."
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
            "it out. Final reality check per sector: would an institutional "
            "investor actually rotate into or out of that sector TODAY "
            "because of THIS news? If not, leave it out. For each sector you "
            "DO include, give its direction, a one-line mechanism, and which "
            "of the already-identified sectors it's rippling from "
            "(parent_sector)."
        )
        parent_context = f"\n\nAlready-identified sectors this may ripple from:\n{parent_lines}"
        valid_parents = [s.sector for s in parent_sectors]

    # Digest is only injected on the primary branch -- the cascade branches
    # (stage 4/6) already carry a longer prompt (parent sectors + cascade
    # framing) and RULEBOOK_DIGEST's chains describe the DIRECT/primary
    # transmission, not a further ripple hop, so it isn't the right
    # reference for those calls anyway.
    digest_block = f"KNOWN TRANSMISSION CHAINS:\n{RULEBOOK_DIGEST}\n\n" if parent_sectors is None else ""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"{framing}\n\n"
                f"SECTOR DEFINITIONS:\n{SECTOR_DEFINITIONS}\n\n"
                f"{digest_block}"
                f"Facts: {facts}"
                f"{parent_context}"
            ),
        },
    ]
    tool = build_sector_tool(cascade=parent_sectors is not None, valid_parents=valid_parents)

    def _attempt() -> dict:
        response = client.chat.completions.create(
            model=FALLBACK_MODEL,
            max_tokens=2048,
            tools=[tool],
            tool_choice={"type": "function", "function": {"name": "record_sectors"}},
            messages=messages,
            **tier_kwargs("identify_sectors"),
        )
        return _forced_tool_arguments(response, "record_sectors")

    arguments = _retry_forced_tool_call(_attempt, stage="identify_sectors")
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
#
# COMPRESSED HARD (2026-08) and it must STAY compressed. Every rule that was
# here is still here; only the wording is shorter. What was deliberately
# removed is the EXPLANATION of the schema's optional fields (risks,
# assumptions, unknowns, alternative_hypothesis, evidence_refs) -- they now
# cost one clause instead of six lines, because they are no longer required
# (see _COMPANY_ITEM_REQUIRED) and a 20B model fills them poorly anyway.
# The reason for all of this is a hard token budget, not taste: see
# tests/test_prompt_budget.py and GROQ_TPM_CEILING. Adding prose back here
# is the single easiest way to break company identification in production
# again, which is exactly how it broke.
_COMPANY_FIELD_INSTRUCTIONS = (
    "- ticker: the EXACT symbol as traded, suffix included (\"MARUTI.NS\", "
    "not \"MARUTI\"). A wrong suffix fails to resolve and the company is "
    "silently dropped, so use null rather than a close-but-wrong guess.\n"
    "- name: the real legal name (\"Maruti Suzuki India Ltd.\") -- the only "
    "fallback when the ticker is null or wrong.\n"
    "- rationale: the mechanism for THAT company -- its specific role "
    "(producer vs refiner vs distributor; never assume one role per "
    "sector), its market position, and a real precedent if you know one. "
    "Explain WHY this news moves THIS company and HOW; never restate a "
    "price or number the article already reports as if it were analysis.\n"
    "- key_points: 1-2 plain sentences (15-30 words each) a reader with "
    "ZERO finance background understands on one read. Spell out the chain: "
    "[what happened] -> [what it changes for this company: costs, sales, "
    "profit, what its customers do] -> [why that is good or bad]. Unpack "
    "any jargon you use (never leave \"margin compression\" bare). "
    "Forbidden: restating the article's own numbers; vague sentiment with "
    "no mechanism; a generic, always-true company fact; a sentence an "
    "ordinary reader would have to look up.\n"
    "- reasons: 1-4 short, distinct, individually-citable reasons for the "
    "direction call.\n"
    "- time_horizon: exactly one of Immediate, Short-Term, Medium-Term, "
    "Long-Term -- when the mechanism actually plays out.\n"
    "- risks, assumptions, unknowns, alternative_hypothesis and "
    "evidence_refs are OPTIONAL: fill them only when you have something "
    "specific and real.\n\n"
    "Never invent a number, study or historical case you are not genuinely "
    "confident is real -- an honest qualitative statement beats a "
    "fabricated statistic every time."
)

# Was wired into the direct stage's (stage 3) primary attempt as the
# rulebook/playbook-bearing variant -- it's no longer used by
# _identify_companies at all. Even scoped to one sector's candidates, a
# prompt carrying this block measures 16,284-17,243 tokens (2026-08
# measurement), over BOTH Groq models' GROQ_TPM_CEILING (claude_client.py)
# regardless of which model serves it, so an attempt built from this constant
# would 413 unconditionally -- see the comment at _identify_companies for
# the full reasoning. Left defined (and still directly tested) as a record of
# the rulebook-citing instructions and for any future caller whose prompt
# doesn't also carry a multi-candidate grounding block.
COMPANY_RATIONALE_INSTRUCTIONS = (
    f"{_COMPANY_FIELD_INSTRUCTIONS}\n"
    "- evidence_refs: one entry per `reasons` item -- either a rule id from "
    "ECONOMIC REASONING RULES below (e.g. \"RULE_REPO_RATE_CUT\"), a quoted "
    "or closely paraphrased fact from the article (prefix \"article: \"), "
    "or a specific historical precedent you actually know (prefix "
    "\"historical: \").\n\n"
    "Consult the ECONOMIC REASONING RULES and SECTOR PLAYBOOKS below. When a "
    "rule genuinely applies: include its rule id verbatim as one entry in that "
    "company's evidence_refs, then ADAPT its mechanism to this article's "
    "specifics -- name the actual numbers, companies, and conditions from the "
    "news. Copying rule text verbatim into rationale or key_points is "
    "forbidden: the rules are generic priors, your output must be this "
    "article's specific story. The article's own facts always override a "
    "rule's generic direction -- when they conflict, follow the article and "
    "do not cite the rule. Respect each rule's 'only if' conditions -- a "
    "conditional branch whose condition doesn't hold here does not apply. If "
    "no rule matches, reason from first principles and cite no rule id -- do "
    "not force-fit one.\n"
    f"ECONOMIC REASONING RULES:\n{RULEBOOK_TEXT}\n\n"
    f"SECTOR PLAYBOOKS:\n{PLAYBOOKS_TEXT}"
)

# The rulebook/playbook-free variant. Originally written for cascade stages
# (5/7) only -- those calls already carry a longer prompt (multiple sectors +
# a parent-company list + the anti-division-naming rules below), and a real
# production test showed the combined weight pushed the model to return a
# degenerate empty tool call instead of reasoning through it -- but now used
# unconditionally by _identify_companies for the direct stage too (see that
# function's own comment): even scoped to one sector, adding the rulebook
# block back in measures over BOTH Groq models' per-minute ceilings, so no
# _identify_companies call ever has the rulebook available to cite.
# evidence_refs here is scoped to what's actually available in this call
# (article facts + real-world knowledge), not a rulebook that isn't provided.
CASCADE_COMPANY_RATIONALE_INSTRUCTIONS = (
    f"{_COMPANY_FIELD_INSTRUCTIONS}\n"
    "- evidence_refs (optional): up to one entry per `reasons` item -- an "
    "article fact (prefix \"article: \") or a precedent you actually know "
    "(prefix \"historical: \")."
)

# Shared by both company stages (direct and cascade). The breadth this asks
# for is safe ONLY because of the two rails that bracket it: the model can
# select nothing outside the CANDIDATE COMPANIES block (real DB rows,
# enum-constrained, see app.companies.candidates), and everything it does
# select is re-read by app.analysis.verification, which is the pipeline's
# precision stage. The failure this replaces was the opposite of noise: a
# 737 MAX certification story returning three companies because the framing
# told the model that naming "1-3 real companies per sector" was the normal
# outcome. Breadth here must always come from selecting more REAL candidates,
# never from ranking a sector's constituents by size -- that is what put a
# food-delivery company on a crude-oil story, and it stays disabled.
_BREADTH_INSTRUCTION = (
    "BE THOROUGH, NOT REPRESENTATIVE. Work down the candidate list and name "
    "EVERY company the mechanism genuinely reaches, not a sample of the "
    "obvious ones. Five, ten or more is correct whenever the candidates "
    "support it; stopping at two or three while a sixth qualifies is a "
    "failure, not restraint. Look past the largest names to the component "
    "suppliers, materials makers, operators, service providers and smaller "
    "specialists -- those are most often missed. Selecting more is safe: "
    "every entry is a real, tradeable company and a later step removes any "
    "whose mechanism does not hold up.\n\n"
    "What is forbidden is inventing or stretching. Each company you include "
    "needs a specific channel stated for THAT company -- a cost line, a "
    "revenue line, a customer/supplier/competitor relationship, or a "
    "regulatory exposure. \"It is a major player in this sector\" is not a "
    "channel."
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
# risks / assumptions / unknowns / alternative_hypothesis / evidence_refs are
# deliberately NOT required (2026-08). They cost tokens twice -- input tokens
# to explain in _COMPANY_FIELD_INSTRUCTIONS, output tokens to generate -- and
# a 20B model produces them poorly. Dropping them from `required` is what
# bought the prompt back under openai/gpt-oss-20b's 8,000 TPM ceiling, which
# is what lets the reliable-tool-calling model serve this stage at all (see
# tests/test_prompt_budget.py). The properties stay in the schema, so a model
# that has something real to say still may -- they are optional, not gone.
#
# Everything downstream already tolerates their absence: schemas.
# CompanyMention defaults them to []/None, app.companies.resolution passes
# whatever it got, app.pipeline._build_alert_company reads them with
# `.get(...) or []`, and the API serializers decode a missing column to [].
# The ONE place absence was NOT tolerated was scoring -- an empty
# evidence_refs used to drive app.reasoning.confidence's evidence AND
# rulebook components to a hard 0.0 and put every company under
# app.pipeline.CONFIDENCE_FLOOR. Fixed there, in compute_confidence; see its
# comment before changing either end.
_COMPANY_ITEM_REQUIRED = [
    "name", "direction", "magnitude_low", "magnitude_high", "rationale", "key_points",
    "time_horizon", "reasons",
]


def build_company_tool(parent_tickers: list[str] | None, valid_tickers: list[str] | None = None) -> dict:
    """parent_tickers=None builds the direct/primary-stage tool (stage 3, no
    parent_ticker field). A non-empty list builds a cascade-stage tool
    (stages 5/7), adding a parent_ticker field enum-constrained to
    parent_tickers so the model cannot invent a nonexistent parent.

    valid_tickers, when given, enum-constrains `ticker` to companies that
    actually exist in the database (see app.companies.candidates) -- the
    model selects from real rows instead of recalling a symbol. Left
    unconstrained (nullable string) when None, preserving the ungrounded
    behavior for callers with no DB session.
    """
    properties = dict(_COMPANY_ITEM_PROPERTIES)
    required = list(_COMPANY_ITEM_REQUIRED)
    if valid_tickers:
        properties["ticker"] = {"type": "string", "enum": valid_tickers}
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


def _call_with_model_fallback(call_fn, model: str, call_name: str, fallback_model: str = FALLBACK_MODEL):
    """Try `model`; retry once on `fallback_model`, with the identical
    prompt, on either a RateLimitError (quota/rate-limited) or a
    tool_use_failed 400 (the model's tool-call structure was unparseable).

    `fallback_model` defaults to FALLBACK_MODEL (gpt-oss-20b) -- the shape
    every OTHER caller of this function wants. _identify_companies is the one
    exception: its slim-prompt ladder passes `model`/`fallback_model` derived
    from GROQ_TPM_CEILING (claude_client.py) instead -- see the comment at
    that call site for why the budget map, not a hardcoded guess, decides
    which model goes first there.

    Any other exception -- and a second failure on `fallback_model`, of any
    kind -- propagates untouched. This is deliberate: a malformed schema on
    OUR side also raises a 400, and silently swallowing it here would let
    the caller return an empty company list indistinguishable from "no
    companies found", which is worse than a loud failure.
    """
    try:
        return call_fn(model)
    except RateLimitError:
        logger.warning(
            "%s: rate-limited on model=%s, retrying once on fallback_model=%s",
            call_name, model, fallback_model,
        )
        return call_fn(fallback_model)
    except BadRequestError as exc:
        if not _is_tool_use_failed(exc):
            raise
        logger.warning(
            "%s: tool_use_failed on model=%s, retrying once on fallback_model=%s",
            call_name, model, fallback_model,
        )
        return call_fn(fallback_model)


# Ceiling on the whole assembled company-stage request -- system + user
# message + serialized tool schema. Lives here, next to the prompt it
# constrains, and is imported by tests/test_prompt_budget.py, which measures
# a real assembled prompt against it. It must stay under the SMALLEST
# GROQ_TPM_CEILING (openai/gpt-oss-20b's 8,000), with the margin absorbing
# the response tokens Groq bills against the same per-minute budget.
COMPANY_PROMPT_TOKEN_BUDGET = 6_500

# _identify_companies' prompt is always the SLIM (no rulebook/playbook)
# variant -- see the comment at that function for why the full variant was
# dropped entirely.
#
# This ladder was INVERTED (llama first) and is now back the right way up.
# The reason for the inversion was purely SIZE: the slim prompt measured
# 10,565-11,524 tokens, inside MODEL's (llama) 12,000 GROQ_TPM_CEILING but
# over FALLBACK_MODEL's (gpt-oss) 8,000, so gpt-oss 413'd on nearly every
# article. But llama fails record_sector_companies' nested tool schema
# constantly, so putting it first traded a 413 for a tool_use_failed and
# produced the same ZERO companies either way -- measured in production at 47
# of the last 48 alerts.
#
# The prompt has since been cut under COMPANY_PROMPT_TOKEN_BUDGET, which is
# under EVERY ceiling in GROQ_TPM_CEILING, so size no longer picks the model.
# Schema quality does, and the ladder is now the same one every other stage
# in this module uses: FALLBACK_MODEL (openai/gpt-oss-20b) is built for
# reliable nested tool/function calling and actually satisfies this schema,
# so it is PRIMARY; MODEL (llama-3.3-70b) is the one-retry FALLBACK, useful
# because it is a separate quota bucket that still answers when gpt-oss is
# rate-limited. See FALLBACK_MODEL's own comment in claude_client.py.
#
# The guard on all of this is tests/test_prompt_budget.py: it fails if the
# prompt outgrows the budget, or if the budget outgrows the smallest ceiling.
# Without it there is nothing to stop the next paragraph of prompt prose from
# quietly putting this stage back over gpt-oss's ceiling -- which is exactly
# how it broke, so do not reorder this ladder to "fix" a size problem. Fix
# the size.
_SLIM_PROMPT_PRIMARY_MODEL = FALLBACK_MODEL
_SLIM_PROMPT_FALLBACK_MODEL = MODEL

# Ceiling on how many already-identified companies a CASCADE-stage prompt
# lists as chainable parents (and enum-constrains parent_ticker to). Each
# entry costs a prompt line AND a tool-schema enum entry, and the pool is the
# entire previous company stage's output across every sector -- so it grows
# with exactly the breadth _BREADTH_INSTRUCTION asks for. Uncapped, a good
# primary stage produces a cascade prompt that exceeds the token ceiling and
# returns ZERO cascade companies, which is the failure this whole module was
# just repaired for. 20 is well above the number of distinct parents any real
# cascade link actually chains from.
MAX_PARENT_POOL = 20


def _identify_companies(
    client, facts: str, sectors: list[SectorFinding], impact_level: str,
    parent_pool: list[CompanyMention] | None, session=None,
) -> list[CompanyMention]:
    """sectors: the sector(s) to find companies within (from a prior
    _identify_sectors call). impact_level: stamped onto every returned
    CompanyMention programmatically (never asked of the LLM). parent_pool:
    for a cascade stage, the companies (from the previous company-stage)
    each returned company must chain from via parent_ticker; None for the
    direct/primary stage (stage 3).

    Every pipeline caller now reaches this through
    _identify_companies_per_sector and passes exactly ONE sector -- a
    multi-sector list still works (older tests use one), but it rebuilds the
    prompt-size problem that made this stage fail outright, so do not call it
    that way from the pipeline."""
    sector_lines = "\n".join(f"- {s.sector} ({s.direction}): {s.mechanism}" for s in sectors)
    if parent_pool is None:
        framing = (
            "For each sector below, name the companies genuinely, directly "
            "affected -- both winners and losers (one sector can hold both, "
            "e.g. importers vs exporters on a currency move). Reason from "
            "the event company's real business-relationship graph -- its "
            "suppliers, customers, competitors, substitutes, distribution "
            "partners, infrastructure and financing partners -- never from "
            "theme or keyword similarity, and never force-fit. Reality check "
            "per company: would a professional equity analyst put it in a "
            "SAME-DAY research note on THIS event? If the link is thematic, "
            "speculative, or merely same-industry, exclude it. Zero "
            "companies for a sector is correct when none genuinely fit."
            f"\n\n{_BREADTH_INSTRUCTION}"
        )
        parent_context = ""
        parent_tickers = None
    else:
        # Filtered from the SAME iteration so names and tickers can never
        # misalign -- do not build parent_tickers and parent_lines from two
        # separately-filtered lists and zip() them; a parent_pool entry
        # with no ticker would then pair the wrong name with the wrong
        # ticker.
        # Capped (see MAX_PARENT_POOL): parent_pool is the WHOLE previous
        # company stage's output, which the breadth instruction actively
        # pushes upward -- an uncapped pool is a prompt term that grows with
        # our own success and silently re-breaks the token budget
        # tests/test_prompt_budget.py defends. Truncation keeps the earliest
        # entries, which are the previous stage's own sector-by-sector order,
        # not an arbitrary reshuffle.
        with_tickers = [c for c in parent_pool if c.ticker][:MAX_PARENT_POOL]
        parent_tickers = [c.ticker for c in with_tickers]
        parent_lines = "\n".join(f"- {c.ticker} ({c.name})" for c in with_tickers)
        framing = (
            "For each sector below, name the companies affected as a ripple "
            "from the already-identified companies listed. Every company "
            "MUST chain from one of those via parent_ticker (the exact "
            "ticker string) through a real economic link -- supplier, "
            "customer, or close competitor -- not shared sector "
            "membership.\n\n"
            "The sector's one-line reason below is real but SECTOR-level. "
            "Both halves of your job are required: (1) name companies the "
            "mechanism genuinely reaches, and (2) for each, state HOW it "
            "hits THAT company's own business -- its revenue exposure, cost "
            "structure or customer base -- not a copy of the sector reason "
            "and not a description of what the company does.\n\n"
            f"{_BREADTH_INSTRUCTION}\n\n"
            "But do not force it. If the mechanism only reaches through "
            "vague language (\"changing consumer spending\", \"increased "
            "engagement\") rather than a specific cost, revenue line or "
            "customer relationship, that is not a company-level link -- zero "
            "companies is then the honest answer. Reality check per company: "
            "would a professional equity analyst put it in a SAME-DAY "
            "research note on THIS event? One company's own temporary "
            "stumble (an earnings miss, a stock drop, CEO commentary) does "
            "NOT ripple to companies that merely share its theme -- for "
            "those, few or zero is correct.\n\n"
            "Each company MUST be a separate, independently listed company "
            "with its own ticker -- NEVER a division, segment, subsidiary or "
            "business unit of a company already named above. \"[Company] - "
            "[Segment] Division\" is the SAME company again, cannot resolve "
            "to a real record, and is not a cascade link; name a genuinely "
            "different company in that sector instead of dropping the "
            "sector."
        )
        parent_context = f"\n\nMust chain from one of these companies:\n{parent_lines}"

    # Grounding (see app.companies.candidates): give the model the real
    # companies in these sectors so it selects rather than recalls. session
    # is None for callers with no DB (older tests) -- those stay ungrounded.
    valid_tickers: list[str] | None = None
    candidate_block = ""
    known_relationships = ""
    if session is not None:
        candidates = candidate_companies(session, [s.sector for s in sectors])

        # Supply-links grounding (app.companies.supply_links.prompting):
        # event_tickers = the already-identified companies this call chains
        # from (parent_tickers is None at the direct/primary stage, where no
        # company is known yet -- that stage stays ungrounded by links, same
        # as before this module existed). Resolved counterparties not
        # already in the candidate list are appended to it BEFORE the
        # MAX_CANDIDATES_PER_PROMPT cap below, so that cap still binds.
        known_relationships, extra_tickers = supply_link_prompting.known_relationships_block(
            session, parent_tickers or [],
        )
        if extra_tickers:
            existing_tickers = {c.ticker for c in candidates}
            new_tickers = [t for t in extra_tickers if t not in existing_tickers]
            if new_tickers:
                candidates = candidates + (
                    session.query(Company).filter(Company.ticker.in_(new_tickers)).all()
                )
        candidates = candidates[:MAX_CANDIDATES_PER_PROMPT]

        if candidates:
            valid_tickers = candidate_tickers(candidates)
            candidate_block = (
                "\n\nCANDIDATE COMPANIES -- choose ONLY from this list. These are "
                "the real, tradeable companies in the sectors above, with what "
                "each actually does. A company not in this list cannot be "
                "recorded, so do not name one. Selecting NONE of them for a "
                "sector is a correct answer when none genuinely fits.\n"
                + format_candidates(candidates)
            )

    # Always the slim (no rulebook/playbook) variant, for BOTH the direct and
    # cascade stages -- see CASCADE_COMPANY_RATIONALE_INSTRUCTIONS' own
    # comment and the model-selection comment in _attempt below for why the
    # rulebook-bearing COMPANY_RATIONALE_INSTRUCTIONS is never reachable here.
    rationale_instructions = CASCADE_COMPANY_RATIONALE_INSTRUCTIONS
    if known_relationships:
        # Additive only: zero stored links means known_relationships == ""
        # and rationale_instructions is untouched, so the composed prompt
        # stays byte-identical to before this block existed (see
        # tests/test_supply_links.py's byte-identical-when-empty test and
        # tests/test_cascade.py's untouched prompt-shape tests).
        rationale_instructions = f"{rationale_instructions}\n\n{known_relationships}"

    def _compose(instructions: str) -> str:
        """Stable prefix first, variable content last (cost-optimization
        phase 2). `framing` and `instructions` are per-stage constants, while
        only the facts/sectors/parents block changes between calls. Leading
        with the constants makes the cacheable prefix as long as it can be,
        which matters most exactly where this call is repeated: EVERY
        company stage now runs it once per sector, re-sending identical
        instructions every time.

        The closing line is not filler. The old ordering put the field
        instructions immediately before the answer, and that adjacency is
        worth keeping; a one-line pointer buys it back for ~20 tokens
        without splitting the cacheable prefix. Nothing about the
        instructions themselves changes here -- only where they sit
        relative to the data they apply to.

        `candidate_block` (the real DB companies this call must choose from)
        rides the variable tail, not the prefix: it is derived from THIS
        call's sectors, so it is not cacheable, and it must stay adjacent to
        the sector lines it enumerates.
        """
        return (
            f"{framing}\n\n"
            f"{instructions}\n\n"
            f"Facts: {facts}\n\n"
            f"Sectors:\n{sector_lines}"
            f"{parent_context}"
            f"{candidate_block}\n\n"
            "Now apply the instructions above to these facts and sectors, "
            "filling in every field exactly as they specify."
        )

    tool = build_company_tool(parent_tickers if parent_tickers else None, valid_tickers=valid_tickers)

    def _attempt() -> dict:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _compose(rationale_instructions)},
        ]

        def _call(model: str):
            return client.chat.completions.create(
                model=model,
                max_tokens=8192,
                tools=[tool],
                tool_choice={"type": "function", "function": {"name": "record_sector_companies"}},
                messages=messages,
                **tier_kwargs("identify_companies"),
            )

        # Ladder order (gpt-oss primary, llama fallback) and the reasoning
        # behind it live with _SLIM_PROMPT_PRIMARY_MODEL above -- it is now
        # the SAME ordering every other stage in this module uses, because
        # the prompt fits every GROQ_TPM_CEILING and size no longer decides.
        #
        # A full-rulebook attempt used to be tried first for the direct
        # stage (parent_pool is None), with this slim ladder as its retry on
        # failure. It has been removed outright, not just reordered: even
        # scoped to one sector's candidates, a full-rulebook prompt measures
        # 16,284-17,243 tokens -- over BOTH models' GROQ_TPM_CEILING
        # regardless of order, so that attempt was a guaranteed wasted call
        # and a guaranteed 413 on every single article, never once serving a
        # real request. Swapping RULEBOOK_TEXT for the smaller RULEBOOK_
        # DIGEST was considered and rejected: digest+playbooks still adds
        # roughly 2.5k tokens on top of the measured slim range, landing
        # around 13.1k-14.1k -- still over BOTH ceilings, so it would have
        # stayed a guaranteed failure too, just a smaller one. There is
        # currently no rulebook-bearing prompt shape for this stage that
        # fits either model, so the direct stage runs on the same slim,
        # rulebook-free ladder as the cascade stages (parent_pool is not
        # None) -- see rationale_instructions above.
        response = _call_with_model_fallback(
            _call, _SLIM_PROMPT_PRIMARY_MODEL, call_name="identify_companies",
            fallback_model=_SLIM_PROMPT_FALLBACK_MODEL,
        )

        return _forced_tool_arguments(response, "record_sector_companies")

    # This stage already had a model-fallback ladder. The stochastic retry
    # wraps it rather than duplicating it: one attempt here is a full ladder,
    # and a ladder that ends in garbage output is retried up to
    # TOOL_CALL_ATTEMPTS times -- the same shared policy every other
    # forced-tool-call stage gets.
    arguments = _retry_forced_tool_call(_attempt, stage="identify_companies")

    # Provider-side enum enforcement is not reliable for nested array items
    # (see the SECTORS filter at the end of _identify_sectors for the same
    # failure mode confirmed in production). When grounding is active, drop
    # any ticker outside the candidate list rather than letting an invented
    # symbol through to resolution.
    allowed = set(valid_tickers) if valid_tickers else None

    mentions: list[CompanyMention] = []
    for group in arguments.get("sector_companies", []):
        sector = group.get("sector")
        for company in group.get("companies", []):
            if allowed is not None and company.get("ticker") not in allowed:
                logger.warning(
                    "dropping off-candidate ticker %r (%r) from grounded company stage",
                    company.get("ticker"), company.get("name"),
                )
                continue
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


def _identify_companies_per_sector(
    client, facts: str, sectors: list[SectorFinding], impact_level: str,
    parent_pool: list[CompanyMention] | None, session=None,
) -> tuple[list[CompanyMention], list[dict]]:
    """Calls _identify_companies ONCE PER SECTOR rather than bundling every
    sector into one call. Serves BOTH company stages: the direct/primary
    stage (stage 3, parent_pool=None) and the cascade stages (5/7, with a
    parent_pool) -- one implementation, so the per-sector call shape, the
    retry, and the gap recording cannot drift between them.

    Confirmed in production for the cascade stages first: bundling 5-7
    cascade sectors (each company requires a long rationale/key_points/
    reasons/evidence_refs/risks/assumptions/unknowns block, easily 500+
    tokens) into a single max_tokens=8192 tool call made the model return a
    degenerate empty response (no exception, just `{}` -- silently zero
    companies) even though every sector had a genuine, findable answer. The
    SAME sectors, called one at a time, reliably produced rich, correct,
    multi-company results.

    The direct stage was exempted from this on the theory that it has few
    enough sectors for bundling to be safe. Measured in production (2026-08)
    that was wrong, and in a harder way than a degraded answer: its bundled
    prompt carried EVERY primary sector's candidate block at once and billed
    17,607 tokens (11,888 with the rulebook dropped), over the per-minute
    token ceiling of BOTH available models -- openai/gpt-oss-20b at 8,000 TPM
    and llama-3.3-70b-versatile at 12,000 -- so every article 413'd here and
    got ZERO direct companies. One sector per call carries one sector's
    candidates, which fits both ceilings with room to spare (see
    app.companies.candidates for the measured budget).

    A failure on one sector is retried once (2 attempts total) before being
    recorded as a gap dict in the returned gaps list -- never silently
    dropped, so a genuine transient failure (rate limit, malformed
    response) is distinguishable from "this sector genuinely has no
    companies" (which returns normally with an empty list, not a gap). A gap
    on one sector does not lose another sector's results -- which is the
    other half of what the direct stage gains here: it used to be one call
    whose single failure cost the article every direct company at once.

    This 2-attempt loop sits OUTSIDE _identify_companies' own
    _retry_forced_tool_call, and the two are complementary rather than
    redundant: this one catches every exception (a rate limit that outlived
    the key/model rotation reaches here and becomes a gap), while the inner
    one retries only the stochastic garbage-output classes. The `attempts: 2`
    recorded on the gap counts THIS loop's sector-level attempts, which is
    what the gap is about.
    """
    mentions: list[CompanyMention] = []
    gaps: list[dict] = []
    for sector in sectors:
        last_error: str | None = None
        succeeded = False
        for attempt in range(2):  # try once, retry once
            try:
                mentions.extend(_identify_companies(
                    client, facts, [sector], impact_level=impact_level,
                    parent_pool=parent_pool, session=session,
                ))
                succeeded = True
                break
            except Exception as exc:
                last_error = str(exc)
        if not succeeded:
            logger.warning(
                "%s company lookup for sector %r failed after retry, recording gap: %s",
                impact_level, sector.sector, last_error,
            )
            gaps.append({
                "sector": sector.sector,
                "impact_level": impact_level,
                # parent_pool is a POOL of companies this sector's lookup
                # chains from, not a single one (and None entirely on the
                # direct stage) -- there is no single correct parent_ticker
                # to attribute a whole-sector failure to, so this is
                # intentionally left None rather than picking (and thereby
                # misrepresenting) just the first entry.
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


def _sector_mechanism_edges(sectors: list[SectorFinding]) -> list[dict]:
    """One edge per distinct sector actually found, from "news" straight to
    that sector node, carrying the sector's own real one-line `mechanism`
    text (see build_sector_tool: "One-line explanation of why this sector
    is affected") as its note -- purely programmatic, reusing text the LLM
    already generated at whichever cascade stage (primary/L1/L2) first
    named this sector, not a new call.

    This is the ONLY edge in the graph that carries genuine, per-article,
    sector-level reasoning. Every other sector-touching edge is either
    static (CHAINS' hardcoded per-event-type text) or company-specific
    (_sector_attachment_edges' generic per-company template, and each
    company's own rationale, which explains that company's OWN exposure,
    not the sector's). Reported live bug: the frontend's sector-level WHY
    explanation was reading a single company's rationale and showing it as
    if it were the sector's own reasoning -- misleading when a sector has
    several companies with different individual angles. This edge gives it
    a real sector-level source to read instead.

    Deduplicated by sector (first occurrence wins, i.e. the most direct
    stage a sector was named at) so a sector reached at multiple cascade
    stages -- e.g. also as an L1 ripple target after being primary -- gets
    exactly one mechanism note on its node, not several competing ones.
    """
    edges = []
    seen_sectors: set[str] = set()
    for finding in sectors:
        if finding.sector in seen_sectors:
            continue
        seen_sectors.add(finding.sector)
        edges.append({
            "from": {"kind": "news", "label": "news"},
            "to": {"kind": NODE_SECTOR, "label": finding.sector},
            "relation": "correlation",
            "direction": finding.direction,
            "note": finding.mechanism,
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

        def _attempt() -> dict:
            response = client.chat.completions.create(
                model=FALLBACK_MODEL, max_tokens=2048, tools=[tool],
                tool_choice={"type": "function", "function": {"name": "record_edge_verification"}},
                messages=messages,
                **tier_kwargs("generate_edges"),
            )
            return _forced_tool_arguments(response, "record_edge_verification")

        try:
            # Retried on the stochastic garbage classes before the fallback
            # below fires: dropping (or leaving unverified) a whole proposed
            # chain because one small-model call answered in prose is exactly
            # the avoidable loss TOOL_CALL_ATTEMPTS exists for.
            arguments = _retry_forced_tool_call(_attempt, stage="generate_edges")
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
            if event_type in CHAIN_FALLBACK_KEEP_EVENT_TYPES:
                logger.warning("edge verification call failed, falling back to unverified proposed chain: %s", exc)
                edges = [
                    {**e, "source": "rulebook_verified", "note": f"{e['note']} [UNVERIFIED: verification call failed]"}
                    for e in proposed
                ]
            else:
                # This event_type's chain covers several distinct news
                # families (see CHAIN_FALLBACK_KEEP_EVENT_TYPES docstring in
                # rulebook.py) -- without verification an unverified
                # canonical chain risks charting the wrong SUBJECT entirely,
                # not just the wrong direction. Drop the proposed edges
                # rather than keep a possibly-mismatched chain; company-
                # attachment edges below still proceed as usual.
                logger.warning(
                    "edge verification call failed for non-fallback-safe event_type %r, dropping proposed chain: %s",
                    event_type, exc,
                )
                edges = []

    edges.extend(_sector_attachment_edges(companies))
    return edges


# Event types whose mechanism is genuinely broad enough that "every prominent
# company in this sector has some exposure" is a defensible claim -- a rate,
# commodity, currency, or trade/policy move really does reach costs, credit,
# or spending across a whole sector.
#
# Everything else is narrow: one company's earnings, one deal, one contract
# win. For those, sector-wide fan-out asserts an exposure that does not
# exist, which is most of what made alerts balloon to 35 companies. A narrow
# story's companies come from the analyzed stages alone.
BROAD_EVENT_TYPES = frozenset({
    "repo_rate_change", "inflation", "macro_data", "fiscal_policy",
    "monsoon_weather", "crude_oil", "commodity_price", "currency_move",
    "global_rates", "trade_policy",
})


def _sector_fanout_mentions(
    sectors: list[SectorFinding], impact_level: str,
) -> list[CompanyMention]:
    """Deterministic sector-wide fan-out: whatever specific companies the LLM
    named for a sector (direct or cascade alike) is confirmed in production to
    vary wildly in coverage for the same sector (one oil-price alert named 8
    companies, another named only Reliance). One sector-wide mention per
    sector lets app.companies.resolution.resolve_companies's top-N-by-
    index-tier fan-out (TOP_N_SECTOR_COMPANIES) fill in that sector's other
    real, prominent constituents regardless of what the LLM enumerated --
    already deduplicated against the LLM's own picks by resolve_companies's
    seen_company_ids, so a company already named is never added twice.

    impact_level is stamped onto every returned mention. The sole caller
    (analyze_article) only ever invokes this at the primary/direct level --
    fan-out is deliberately never applied to a cascade sector (see
    BROAD_EVENT_TYPES's usage below: "a cascade sector is already one hop
    from the news; fanning it out ... stacks a generic claim on top of an
    indirect one") -- so parent_ticker is always left at its default (None)
    here; a direct-level CompanyMention needs no parent to chain from.

    magnitude_low/high are placeholders (this is a sector, not a company the
    LLM ever estimated a range for) -- unused by feed-v2 (which only ever
    displays the real measured excess_move_pct), only read by the legacy
    /api/alerts router.
    """
    return [
        CompanyMention(
            name=f"{sector.sector} sector", is_direct=False, sector=sector.sector,
            direction=sector.direction, magnitude_low=1.0, magnitude_high=3.0,
            rationale=f"Sector-wide exposure via {sector.sector}: {sector.mechanism}",
            time_horizon="Short-Term", impact_level=impact_level,
        )
        for sector in sectors
    ]


def analyze_article(client, title: str, content: str, session=None) -> AnalysisOutput:
    """Runs the sector-cascade chain (see module docstring for why the call
    count now scales with cascade sector count) and composes the result into the
    same AnalysisOutput shape app.pipeline.py already consumes. Failure
    handling (see docs/superpowers/specs/2026-07-20-sector-cascade-
    reasoning-design.md): a facts (stage 1) or primary-sector (stage 2)
    failure propagates, failing the whole article -- identical to the old
    single-call analyze_article's behavior. A failure at any later stage
    truncates the pipeline there: everything produced by stages that
    already succeeded is still returned. Per-sector company failures --
    now at EVERY company stage, direct (3) and cascade (5/7) alike -- are
    retried and, if still unresolved, recorded as gaps rather than
    truncating the pipeline (see _identify_companies_per_sector).
    """
    facts_result = _extract_facts(client, title, content)
    primary_sectors = _identify_sectors(client, facts_result.facts, parent_sectors=None)

    all_companies: list = []
    all_gaps: list[dict] = []
    # Every SectorFinding this article's cascade names, across all stages --
    # feeds _sector_mechanism_edges below so each sector node's WHY note is
    # the real, per-article reasoning the LLM already gave for THAT sector,
    # not a company's own rationale mislabeled as the sector's.
    all_sectors: list[SectorFinding] = list(primary_sectors)
    if not primary_sectors:
        return AnalysisOutput(
            category=facts_result.category, event_type=facts_result.event_type,
            companies=all_companies, gaps=all_gaps, facts=facts_result.facts,
        )

    # One call per primary sector, same as the cascade stages -- a bundled
    # call carried every sector's candidate block at once and exceeded both
    # models' per-minute token ceilings, costing the article every direct
    # company (see _identify_companies_per_sector). A sector that still fails
    # after its retry becomes a gap and no longer takes the other sectors'
    # companies down with it, so there is nothing left to "truncate" here.
    primary_companies, primary_gaps = _identify_companies_per_sector(
        client, facts_result.facts, primary_sectors, impact_level="direct",
        parent_pool=None, session=session,
    )
    all_companies.extend(primary_companies)
    all_gaps.extend(primary_gaps)

    # Fan-out only for genuinely broad events, and only at the primary level.
    # A cascade sector is already one hop from the news; fanning it out to
    # every prominent constituent stacks a generic claim on top of an
    # indirect one, which is where the worst noise came from (auto and
    # banking names on a crude-oil story via L1/L2 fan-out).
    fanout_allowed = facts_result.event_type in BROAD_EVENT_TYPES
    if fanout_allowed:
        all_companies.extend(_sector_fanout_mentions(primary_sectors, impact_level="direct"))

    l1_parent_tickers_present = [c for c in primary_companies if c.ticker]
    if l1_parent_tickers_present:
        try:
            l1_sectors = _identify_sectors(client, facts_result.facts, parent_sectors=primary_sectors)
        except Exception as exc:
            logger.warning("cascade stage 4 (L1 cascade sectors) failed, truncating: %s", exc)
            l1_sectors = []
        all_sectors.extend(l1_sectors)
        if l1_sectors:
            l1_companies, l1_gaps = _identify_companies_per_sector(
                client, facts_result.facts, l1_sectors, impact_level="indirect_l1",
                parent_pool=l1_parent_tickers_present, session=session,
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
            all_sectors.extend(l2_sectors)
            if l2_sectors:
                l2_companies, l2_gaps = _identify_companies_per_sector(
                    client, facts_result.facts, l2_sectors, impact_level="indirect_l2",
                    parent_pool=l2_parent_tickers_present, session=session,
                )
            else:
                l2_companies, l2_gaps = [], []
            all_companies.extend(l2_companies)
            all_gaps.extend(l2_gaps)

    # Verification (see app.analysis.verification): the only stage that asks
    # whether a company BELONGS rather than asking for more companies. Runs
    # once over the whole assembled list, after every generative stage and
    # before edges, so a dropped company never reaches the graph either.
    all_companies = verify_companies(client, facts_result.facts, title, all_companies)

    try:
        edges = _generate_edges(client, facts_result.facts, facts_result.event_type, all_companies)
    except Exception as exc:
        logger.warning("edge generation failed entirely, returning no edges: %s", exc)
        edges = []
    edges.extend(_sector_mechanism_edges(all_sectors))

    return AnalysisOutput(
        category=facts_result.category, event_type=facts_result.event_type,
        companies=all_companies, gaps=all_gaps, edges=edges, facts=facts_result.facts,
    )
