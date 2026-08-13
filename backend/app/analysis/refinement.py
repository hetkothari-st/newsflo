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
import logging
import re
import time

from openai import RateLimitError

from app.analysis.claude_client import FALLBACK_MODEL, MODEL, SYSTEM_PROMPT, tier_kwargs
from app.companies.matching.normalize import normalize_name
from app.config import settings
from app.models import AlertRippleLayer, Company, CompanyAlias, TimelineEffect
from app.reasoning.compliance import PERCENT_RE, TARGET_PRICE_RE, validate_no_advice_language, validate_or_none

logger = logging.getLogger(__name__)

EVENT_SUMMARY_FRAMING = (
    "Summarize this news event for a retail investor with no finance "
    "background. summary_short must be 12 words or fewer -- the single "
    "most important, plain-language takeaway. summary_long must be "
    "exactly two sentences, plain language, no jargon (unpack any finance "
    "term you use). Do not include any percentage, price, price target, "
    "or buy/sell/hold language -- describe what happened and why it "
    "matters, not whether to trade on it. Set is_unconfirmed to true ONLY "
    "when the event is an unverified report, rumor, or speculation, or "
    "when a named party has denied it -- an officially announced or "
    "confirmed event is false. Closed world: describe ONLY what the "
    "supplied facts state. Never introduce companies, numbers, causes, "
    "or consequences the facts do not contain; if the facts are too thin "
    "to summarize, return nothing rather than guessing."
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
                    "is_unconfirmed": {
                        "type": "boolean",
                        "description": "true ONLY for an unverified report/rumor/speculation or a denied claim; false for an officially announced or confirmed event.",
                    },
                },
                "required": ["summary_short", "summary_long", "is_unconfirmed"],
            },
        },
    }


def _call_event_summary_tool(client, title: str, facts: str) -> dict | None:
    """Returns the parsed tool-call arguments, or None on any failure --
    a malformed/truncated JSON response, an exhausted RateLimitError
    fallback, or any other client error all degrade to None rather than
    raising, same "never crash the alert" discipline as
    app.market.measure.measure_company_move."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"{EVENT_SUMMARY_FRAMING}\n\nTitle: {title}\n\nFacts: {facts}"},
    ]
    tool = build_event_summary_tool()

    def _call(model: str):
        return client.chat.completions.create(
            model=model, max_tokens=512, tools=[tool],
            tool_choice={"type": "function", "function": {"name": "record_event_summary"}},
            messages=messages, **tier_kwargs("event_summary"),
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


def generate_event_summary(client, title: str, facts: str) -> dict | None:
    """Returns {"summary_short", "summary_long"} (either may be None if it
    never passed validation, even after one retry), or None entirely if
    NEITHER field ever became usable. Never raises -- a malformed or
    missing tool-call response degrades to None, same "never crash the
    alert" discipline as app.market.measure.measure_company_move."""
    first = _call_event_summary_tool(client, title, facts)
    if first is None:
        return None

    summary_short = validate_or_none(first.get("summary_short"))
    summary_long = validate_or_none(first.get("summary_long"))

    if summary_short is None or summary_long is None:
        retry = _call_event_summary_tool(client, title, facts)
        if retry is not None:
            if summary_short is None:
                summary_short = validate_or_none(retry.get("summary_short"))
            if summary_long is None:
                summary_long = validate_or_none(retry.get("summary_long"))

    if summary_short is None and summary_long is None:
        return None
    # Rumor/denial classification (spec v2 §4.3). Only a literal boolean
    # counts; anything else degrades to None (leave Alert.is_unconfirmed
    # unset -- reads as confirmed) rather than guessing.
    raw_unconfirmed = first.get("is_unconfirmed")
    is_unconfirmed = raw_unconfirmed if isinstance(raw_unconfirmed, bool) else None
    return {
        "summary_short": summary_short,
        "summary_long": summary_long,
        "is_unconfirmed": is_unconfirmed,
    }


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


def _call_impact_why_tool(client, title: str, facts: str, companies: list[dict]) -> dict[str, str]:
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
            "content": f"{IMPACT_WHY_FRAMING}\n\nArticle: {title}\n\nFacts: {facts}\n\nCompanies:\n{company_lines}",
        },
    ]
    tool = build_impact_why_tool(tickers)

    def _call(model: str):
        return client.chat.completions.create(
            model=model, max_tokens=2048, tools=[tool],
            tool_choice={"type": "function", "function": {"name": "record_impact_whys"}},
            messages=messages, **tier_kwargs("impact_whys"),
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


def generate_impact_whys(client, title: str, facts: str, companies: list[dict]) -> dict[str, str]:
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
    first = _call_impact_why_tool(client, title, facts, companies)

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
        retry = _call_impact_why_tool(client, title, facts, retry_companies)
        for ticker in retry_tickers:
            text = validate_or_none(retry.get(ticker))
            if text is not None:
                result[ticker] = text

    return result


# Spec §5 standard relationship types -- the closed vocabulary a generated
# section's tag must come from (the tag renders in the layer header).
RIPPLE_RELATIONSHIP_TYPES = [
    "DIRECT", "SELLER", "USER", "SUPPLIER", "CUSTOMER", "BYPRODUCT", "SUBSTITUTE",
    "COMPETITOR", "PROTECTED", "EXPOSED", "RATE_BENEFICIARY", "RATE_SENSITIVE",
    "DEFENSIVE_ROTATION", "SECTOR_WIDE",
]

RIPPLE_LAYERS_FRAMING = (
    "Group this news event's affected companies into the sections a "
    "market-impact card should show -- adapt the sections to THIS story. "
    "Classic shapes to reuse WHEN they fit: commodity news often splits "
    "into producers / refiners & marketers / by-products / heavy users; "
    "rate news into banks vs NBFCs / rate-sensitive demand / defensive "
    "rotation; tariff news into protected makers / exposed users / "
    "suppliers / substitutes. Invent a different, story-specific section "
    "when none of those describes the real mechanism. Each section: a "
    "title like 'Winners — <short label>' / 'Losers — <short label>' (or "
    "'Direct — <label>' / a plain label for mixed or rotation sections), "
    "one relationship type from the allowed list, a one-line plain-"
    "language note explaining why this GROUP moves together, and the "
    "tickers that belong to it (every ticker exactly once, only from the "
    "provided list). Sentence case, no jargon, no percentages, no "
    "buy/sell/hold language. Never use the words buy, sell, hold, or any "
    "rating or price-target language in a title or note -- such a section "
    "is discarded entirely."
)


def build_ripple_layers_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "record_ripple_layers",
            "description": "Group the affected companies into story-specific card sections.",
            "parameters": {
                "type": "object",
                "properties": {
                    "layers": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "relationship": {"type": "string", "enum": RIPPLE_RELATIONSHIP_TYPES},
                                "note": {"type": "string"},
                                "tickers": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["title", "relationship", "note", "tickers"],
                        },
                    },
                },
                "required": ["layers"],
            },
        },
    }


def generate_ripple_layers(client, title: str, facts: str, companies: list[dict]) -> list[dict]:
    """Story-adaptive card-back sections (spec §5): returns
    [{"title", "relationship", "note", "tickers"}, ...] or [] on any
    failure / empty result -- read time then falls back to the static
    archetype template and generic buckets. Validation: relationship must
    be in the closed vocabulary (schema-enforced, re-checked), tickers
    are filtered to the alert's own affected set, a ticker claimed twice
    keeps only its first section, and a layer left with no tickers is
    dropped. Companies NOT claimed by any layer are handled at read time
    (appended to fallback buckets), never invented here.

    ``companies`` is [{"ticker", "name", "sector", "sub_sector",
    "direction", "why"}, ...] -- the real analyzed attributes the model
    groups by.
    """
    if not companies:
        return []
    lines = "\n".join(
        f"- {c['ticker']}: {c['name']} | sector {c['sector']}"
        + (f"/{c['sub_sector']}" if c.get("sub_sector") else "")
        + f" | {c['direction']}"
        + (f" | {c['why']}" if c.get("why") else "")
        for c in companies
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"{RIPPLE_LAYERS_FRAMING}\n\nTitle: {title}\n\nFacts: {facts}\n\n"
            f"Affected companies:\n{lines}"
        )},
    ]
    tool = build_ripple_layers_tool()

    def _call(model: str):
        # 1536 was too tight for this tool's nested per-layer schema
        # (title/relationship/note/tickers x N sections) -- the same
        # starved-response failure mode documented in
        # cascade.py::_identify_companies_per_sector, where a
        # too-small budget for a nested-array response makes the model
        # return no tool call at all rather than a partial one.
        return client.chat.completions.create(
            model=model, max_tokens=4096, tools=[tool],
            tool_choice={"type": "function", "function": {"name": "record_ripple_layers"}},
            messages=messages, **tier_kwargs("ripple_layers"),
        )

    try:
        try:
            response = _call(MODEL)
        except RateLimitError:
            response = _call(FALLBACK_MODEL)
        message = response.choices[0].message
        tool_call = next((tc for tc in (message.tool_calls or []) if tc.function.name == "record_ripple_layers"), None)
        if tool_call is None:
            logger.warning(
                "ripple-layer generation returned no tool call for %d companies", len(companies),
            )
            return []
        arguments = json.loads(tool_call.function.arguments)

        known_tickers = {c["ticker"] for c in companies}
        seen: set[str] = set()
        validated = []
        for layer in arguments.get("layers", []):
            if layer.get("relationship") not in RIPPLE_RELATIONSHIP_TYPES:
                logger.warning("ripple layer rejected: bad relationship %r", layer.get("relationship"))
                continue
            layer_title = validate_or_none(layer.get("title"))
            note = validate_or_none(layer.get("note"))
            if not layer_title or not note:
                logger.warning(
                    "ripple layer rejected by compliance: title=%r note=%r",
                    layer.get("title"), layer.get("note"),
                )
                continue
            tickers = [
                t for t in layer.get("tickers", [])
                if t in known_tickers and t not in seen
            ]
            if not tickers:
                logger.warning(
                    "ripple layer %r rejected: no known unclaimed tickers in %r",
                    layer_title, layer.get("tickers"),
                )
                continue
            seen.update(tickers)
            validated.append({
                "title": layer_title, "relationship": layer["relationship"],
                "note": note, "tickers": tickers,
            })
        if not validated:
            logger.warning("ripple-layer generation produced no valid layers from %d raw layers",
                           len(arguments.get("layers", [])))
        return validated
    except Exception as exc:
        logger.warning("ripple-layer generation failed: %s", exc)
        return []


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
    "what unfolds, not whether to trade on it. Closed world: reason only "
    "from the supplied facts. Never name companies, figures, or causal "
    "chains the facts do not support; skipping every horizon is a valid "
    "answer when the facts say nothing about how the effect unfolds."
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


def _call_timeline_tool(client, title: str, facts: str) -> list[dict]:
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
        {"role": "user", "content": f"{TIMELINE_FRAMING}\n\nTitle: {title}\n\nFacts: {facts}"},
    ]
    tool = build_timeline_tool()

    def _call(model: str):
        return client.chat.completions.create(
            model=model, max_tokens=1536, tools=[tool],
            tool_choice={"type": "function", "function": {"name": "record_timeline_effects"}},
            messages=messages, **tier_kwargs("timeline_effects"),
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


def generate_timeline_effects(client, title: str, facts: str) -> list[dict]:
    """Returns [{"horizon", "description"}, ...], zero or more -- only for
    horizons the model gave genuine distinct content for AND whose
    description passes validation, retrying once (batched) for any
    horizon that failed validation, then dropping it if still invalid.
    Unrecognized horizon values are dropped during parsing in
    _call_timeline_tool and never reach here, so they are never
    persisted or retried. Never raises -- see _call_timeline_tool."""
    first = _call_timeline_tool(client, title, facts)

    valid = []
    invalid_horizons = []
    for entry in first:
        text = validate_or_none(entry["description"])
        if text is not None:
            valid.append({"horizon": entry["horizon"], "description": text})
        else:
            invalid_horizons.append(entry["horizon"])

    if invalid_horizons:
        retry_by_horizon = {e["horizon"]: e["description"] for e in _call_timeline_tool(client, title, facts)}
        for horizon in invalid_horizons:
            text = validate_or_none(retry_by_horizon.get(horizon))
            if text is not None:
                valid.append({"horizon": horizon, "description": text})

    return valid


# --- Task 13: post-generation closed-world validation + mechanism sanitizer ---

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_CLAUSE_SPLIT_RE = re.compile(r"[,;]")


def _sanitize_mechanism(mechanism: str | None) -> str | None:
    """Fallback for a strict-mode mechanism that fails validate_or_none
    ONLY because of a percentage or price-target fragment (spec §32,
    INV-014): the mechanism is otherwise a genuine, gate-validated,
    company-specific explanation, so this salvages it by stripping just
    the offending sentence -- or, if only part of a sentence is flagged,
    just the offending comma/semicolon-separated clause -- rather than
    discarding the whole thing the way validate_or_none does. Reuses
    compliance.py's own PERCENT_RE/TARGET_PRICE_RE so this can never judge
    something "clean" that the compliance gate would reject elsewhere.

    Returns the surviving remainder, or None if nothing survives (every
    sentence was flagged and had no salvageable clause) or if the
    remainder still fails full compliance validation (e.g. it happens to
    also contain buy/sell/hold language) -- a percentage must never reach
    ac.why through this path either.
    """
    if not mechanism:
        return None
    kept_sentences = []
    for sentence in _SENTENCE_SPLIT_RE.split(mechanism.strip()):
        sentence = sentence.strip()
        if not sentence:
            continue
        if not (PERCENT_RE.search(sentence) or TARGET_PRICE_RE.search(sentence)):
            kept_sentences.append(sentence)
            continue
        kept_clauses = [
            clause.strip() for clause in _CLAUSE_SPLIT_RE.split(sentence)
            if clause.strip() and not (PERCENT_RE.search(clause) or TARGET_PRICE_RE.search(clause))
        ]
        if kept_clauses:
            kept_sentences.append(", ".join(kept_clauses))
    if not kept_sentences:
        return None
    remainder = " ".join(kept_sentences).strip()
    return remainder if validate_no_advice_language(remainder).is_valid else None


# Closed-world percent token: matches compliance.py's PERCENT_RE shape
# (unsigned here -- we only need the numeral to check literal presence in
# alert_facts, a sign doesn't change whether the digits are grounded).
_PERCENT_TOKEN_RE = re.compile(r"(\d+(?:\.\d+)?)\s?%")

# Bounded, conservative n-gram extraction (n=1..3) over contiguous runs of
# capitalized words -- the cheap proxy for "looks like a proper noun
# phrase" this validator uses instead of a real NER model. Words joined by
# '&' or '.' (e.g. "L&T", "D.B.Corp") stay inside one token.
_CAP_WORD_RE = re.compile(r"[A-Za-z][A-Za-z&.]*")

# Frequent capitalized false positives that are not company names -- common
# sentence-leading words, generic institution words, and regulator/
# government references that either never appear in company_aliases or
# would falsely implicate a same-named company if they did. Kept small and
# reviewed rather than exhaustive: the validator's own "only reject on a
# definitive alias-DB hit" discipline is the real safety net, this list
# just avoids wasting DB lookups on the noisiest cases.
_NGRAM_STOPLIST = {
    "the", "a", "an", "this", "that", "these", "those",
    "india", "indian", "bharat",
    "government", "ministry", "state", "union", "central", "national",
    "reserve", "bank", "reserve bank", "reserve bank of india",
    "sebi", "rbi", "nse", "bse",
    "today", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
}


def _extract_capitalized_ngrams(text: str) -> list[str]:
    """Contiguous 1..3-word n-grams built only from runs of consecutive
    capitalized words (a simple proper-noun-phrase heuristic) -- a run
    breaks at the first lowercase-leading word, so "Tata Motors reported"
    yields "Tata", "Motors", "Tata Motors" but never "Motors reported"."""
    words = _CAP_WORD_RE.findall(text or "")
    runs: list[list[str]] = []
    current: list[str] = []
    for word in words:
        if word[:1].isupper():
            current.append(word)
        else:
            if current:
                runs.append(current)
            current = []
    if current:
        runs.append(current)

    ngrams = []
    for run in runs:
        for n in (1, 2, 3):
            for i in range(len(run) - n + 1):
                ngrams.append(" ".join(run[i:i + n]))
    return ngrams


def validate_closed_world(
    text: str | None, alert_facts: str | None, allowed_company_names: set[str], session,
) -> str | None:
    """Post-generation gate for prose the compliance regexes alone can't
    catch: a percentage that IS present but was never in the source facts
    (a fabricated figure dressed up as a real one), or a company named that
    the alert never actually covers (a hallucinated participant). Applies
    to Alert.summary_short/summary_long and each TimelineEffect.description
    -- text that is company-agnostic, plain-language prose that never
    carries a number by design (spec: "closed world: describe ONLY what
    the supplied facts state"), so unlike the per-company `why` there is
    no salvageable partial version: any violation drops the WHOLE field/
    entry, mirroring validate_or_none's all-or-nothing contract.

    ``allowed_company_names`` is the alert's own tracked companies (built
    by the caller from alert_companies); a company name matched in `text`
    that is NOT in that set is still allowed if it appears literally in
    ``alert_facts`` -- mentioned-in-the-source-evidence is not a
    hallucination, it's the closed world the framing prompts already ask
    the model to reason from.

    Returns ``text`` unchanged, or None if rejected. Never raises: a
    CompanyAlias lookup failure (DB unavailable, mid-migration, etc.)
    fails OPEN with a logged warning -- this validator is a second-order
    safety net over non-truth-bearing prose (it can never turn a wrong
    summary into a right one, only sometimes catch an obviously fabricated
    one), so its own unavailability must not silently erase every summary
    and timeline entry an alert would otherwise have.
    """
    if not text:
        return None

    facts = alert_facts or ""
    for match in _PERCENT_TOKEN_RE.finditer(text):
        numeral = match.group(1)
        if numeral not in facts:
            logger.info(
                "closed-world validation rejected text: percent %r not found in alert facts", match.group(0),
            )
            return None

    try:
        facts_lower = facts.lower()
        for candidate in _extract_capitalized_ngrams(text):
            if len(candidate) < 4:
                continue
            normalized = normalize_name(candidate)
            if not normalized or normalized in _NGRAM_STOPLIST:
                continue
            alias = session.query(CompanyAlias).filter(CompanyAlias.normalized == normalized).first()
            if alias is None:
                continue
            company = session.get(Company, alias.company_id)
            if company is None:
                continue
            if company.name in allowed_company_names:
                continue
            if candidate.lower() in facts_lower:
                continue
            logger.info(
                "closed-world validation rejected text: named company %r (company_id=%s) "
                "not in the alert's company set and not found in alert facts",
                company.name, company.id,
            )
            return None
    except Exception as exc:
        logger.warning("closed-world company validation unavailable (%s); failing open", exc)
        return text

    return text


def divergence_line(economic_effect: str | None, reaction_direction: str | None) -> str | None:
    """Deterministic template for the one case the feed must call out
    explicitly: the fundamental exposure thesis (economic_effect: positive
    /negative/mixed/uncertain/no_material_impact, app.analysis.impact_graph)
    and the observed market reaction (reaction_direction: positive/
    negative/flat/unknown, app.market.measure.classify_reaction) point in
    OPPOSITE directions. Pure and total -- no DB, no LLM, exact strings so
    Task 16's serialization can render it verbatim. Every other combination
    (both agree, either is mixed/uncertain/no_material_impact, or the
    reaction is flat/unknown) returns None: there is nothing genuinely
    divergent to say, and this function only ever states a fact the
    measurement layer already computed, never a prediction.
    """
    if economic_effect == "negative" and reaction_direction == "positive":
        return "Stock is currently moving up despite a negative fundamental exposure thesis."
    if economic_effect == "positive" and reaction_direction == "negative":
        return "Stock is currently moving down despite a positive fundamental exposure thesis."
    return None


def refine_alert(client, session, alert, article, alert_companies: list, market_moves: list) -> None:
    """Populate the LLM-explanation fields on an already-measured,
    already-persisted alert: Alert.summary_short/summary_long,
    AlertCompany.why (only for companies with a real measured excess
    move), and TimelineEffect rows. Called from app.pipeline._persist_alert
    once measurement (MarketMove) already exists for this alert's
    companies -- never before. Never raises: any generation function
    returning None/empty simply leaves the corresponding field(s) unset,
    same "omit rather than fabricate" discipline as the rest of this
    pipeline.

    Reasons from ``alert.facts`` -- the stage-1 distilled article the
    cascade itself reasoned from (app.analysis.cascade._extract_facts) --
    not from the raw article body. Two reasons, in this order: refinement
    then explains the SAME evidence base the cascade used to pick these
    companies and directions (previously the two layers could disagree
    because they were reading different text), and the ~1500-token article
    stops being re-sent on all four of the calls below. ``article`` is
    still taken for its title (cheap, and the headline is the one piece of
    framing `facts` deliberately does not repeat) and as the fallback text
    for an alert with no stored facts -- one persisted before this shipped,
    or reused from such an alert via the dedup path.
    """
    facts = alert.facts or article.full_content or article.content

    # The alert's own tracked companies -- the base allow-list
    # validate_closed_world checks a named company against (a company
    # mentioned in the source facts but NOT tracked here is still allowed,
    # validate_closed_world itself falls back to a literal-substring check
    # against `facts` for that case).
    allowed_company_names = {
        company.name for company in (
            session.get(Company, ac.company_id) for ac in alert_companies
        ) if company is not None
    }

    summary = generate_event_summary(client, article.title, facts)
    if summary:
        summary_short = validate_closed_world(
            summary.get("summary_short"), facts, allowed_company_names, session)
        summary_long = validate_closed_world(
            summary.get("summary_long"), facts, allowed_company_names, session)
        if summary.get("summary_short") is not None and summary_short is None:
            logger.info("refine_alert: summary_short dropped by closed-world validation for alert_id=%s", alert.id)
        if summary.get("summary_long") is not None and summary_long is None:
            logger.info("refine_alert: summary_long dropped by closed-world validation for alert_id=%s", alert.id)
        alert.summary_short = summary_short
        alert.summary_long = summary_long
        if summary.get("is_unconfirmed") is not None:
            alert.is_unconfirmed = 1 if summary["is_unconfirmed"] else 0

    # V4 strict closed-world explanations (spec §32, INV-014): the
    # per-company "why" IS the gate-validated mechanism -- already
    # company-specific, one line, and derived from evidence. The legacy
    # impact_whys call (which handed the model the measured direction and
    # asked it to invent a story for it) is exactly the market-move
    # rationalization the spec forbids, so it never runs in strict mode.
    # The mechanism has already passed the closed-world evidence gate
    # upstream, so the only thing that can still block it here is the
    # compliance regex (a % or price-target phrase); _sanitize_mechanism
    # salvages the rest of an otherwise-valid mechanism rather than
    # discarding a genuine, specific explanation over one flagged clause.
    strict_gated = settings.impact_engine_v4_strict and any(
        ac.display_tier for ac in alert_companies)
    if strict_gated:
        for ac in alert_companies:
            if ac.display_tier in ("primary", "secondary_deep_dive", "secondary") and ac.mechanism:
                ac.why = validate_or_none(ac.mechanism) or _sanitize_mechanism(ac.mechanism)
    else:
        moves_by_company_id = {m.company_id: m for m in market_moves}
        measured = []
        for ac in alert_companies:
            move = moves_by_company_id.get(ac.company_id)
            if move is not None and move.measurement_status == "ok" and move.excess_move_pct is not None:
                company = session.get(Company, ac.company_id)
                if company is not None:
                    measured.append({
                        "ticker": company.ticker, "name": company.name,
                        "direction": ac.direction, "excess_move_pct": move.excess_move_pct,
                        "_alert_company": ac,
                    })

        if measured:
            whys = generate_impact_whys(client, article.title, facts, [
                {k: v for k, v in m.items() if k != "_alert_company"} for m in measured
            ])
            for m in measured:
                why = whys.get(m["ticker"])
                if why:
                    m["_alert_company"].why = why

    # Delete-before-insert (INV-009, 2026-08-12): refine_alert used to
    # append, so any re-run (manual re-refinement, a retried deferred pass,
    # fix_direction_contradiction-style scripts) duplicated every timeline
    # row and card-back section. Regeneration replaces, never accumulates.
    session.query(TimelineEffect).filter_by(alert_id=alert.id).delete()
    for effect in generate_timeline_effects(client, article.title, facts):
        description = validate_closed_world(effect["description"], facts, allowed_company_names, session)
        if description is None:
            logger.info(
                "refine_alert: timeline effect dropped by closed-world validation "
                "for alert_id=%s horizon=%s", alert.id, effect["horizon"],
            )
            continue
        session.add(TimelineEffect(alert_id=alert.id, horizon=effect["horizon"], description=description))

    # Story-adaptive card-back sections (spec §5): every affected company
    # (measured or exposure-only) is offered to the model for grouping --
    # exposure rows still belong in a section, they just carry no number.
    # Only analyzed rows are offered for grouping. A sector-inference row is
    # deterministic fan-out (top-N-by-index-tier within a sector), so asking
    # the model to write a story-specific section around it invites exactly
    # the fabricated-specificity this pipeline avoids elsewhere -- and a
    # generated section claims tickers before bucket assignment runs
    # (app.market.ripple_layers.compute_ripple_layers), so it would also
    # bypass the SECTOR_WIDE routing. Fan-out rows always fall through to
    # the SECTOR_WIDE bucket at read time.
    # Strict mode renders sections deterministically from the gate output
    # (app.market.ripple_layers._strict_sections) -- an LLM-authored
    # section would never be read, so the call is simply not paid for.
    if strict_gated:
        return
    layer_companies = []
    for ac in alert_companies:
        if ac.basis == "sector_inference":
            continue
        company = session.get(Company, ac.company_id)
        if company is None:
            continue
        layer_companies.append({
            "ticker": company.ticker, "name": company.name,
            "sector": company.sector, "sub_sector": company.sub_sector,
            "direction": ac.direction, "why": ac.why,
        })
    session.query(AlertRippleLayer).filter_by(alert_id=alert.id).delete()
    for position, layer in enumerate(generate_ripple_layers(client, article.title, facts, layer_companies)):
        session.add(AlertRippleLayer(
            alert_id=alert.id, position=position,
            title=layer["title"], relationship=layer["relationship"],
            note=layer["note"], tickers_json=json.dumps(layer["tickers"]),
        ))


# --- Deferred refinement (docs: cost-optimization phase 5) ---

# A pending alert that keeps failing must not be retried forever. Same
# retry-cap discipline as app.models.TranslationFailure's attempts column:
# past this many tries the alert is marked "failed" and simply keeps the
# null refinement fields every consumer already tolerates.
MAX_REFINEMENT_ATTEMPTS = 3

REFINEMENT_PENDING = "pending"
REFINEMENT_DONE = "done"
REFINEMENT_FAILED = "failed"


def run_pending_refinements(client, session, limit: int | None = None, throttle_seconds: float = 0) -> int:
    """Refine alerts that were persisted with their refinement deferred,
    oldest first. Returns how many were refined.

    Taking these four calls off the analysis run's critical path is the
    point: they are the only LLM work in this pipeline that nothing waits
    on -- an alert is stored, measured, matched to holdings and broadcast
    before refinement contributes anything, and every field it writes is
    nullable at every read site. Running them here means they no longer
    compete with the cascade for the provider's rate-limit headroom, and it
    is the shape a provider batch queue needs (one pass, N independent
    items, no caller blocked on the result).

    Per-alert failures are contained: an alert whose refinement raises is
    counted and left pending for the next pass, up to
    MAX_REFINEMENT_ATTEMPTS, and never stops the others in the batch.
    """
    from app.models import Alert, AlertCompany, MarketMove

    pending = (
        session.query(Alert)
        .filter(Alert.refinement_status == REFINEMENT_PENDING)
        .order_by(Alert.id)
        .limit(limit if limit is not None else settings.refinement_batch_limit)
        .all()
    )

    refined = 0
    for alert in pending:
        alert_companies = session.query(AlertCompany).filter_by(alert_id=alert.id).all()
        market_moves = session.query(MarketMove).filter_by(alert_id=alert.id).all()
        try:
            refine_alert(client, session, alert, alert.article, alert_companies, market_moves)
            alert.refinement_status = REFINEMENT_DONE
            refined += 1
        except Exception:
            alert.refinement_attempts = (alert.refinement_attempts or 0) + 1
            if alert.refinement_attempts >= MAX_REFINEMENT_ATTEMPTS:
                alert.refinement_status = REFINEMENT_FAILED
                logger.exception(
                    "deferred refinement gave up on alert_id=%s after %s attempts; "
                    "it keeps the null refinement fields every reader already tolerates",
                    alert.id, alert.refinement_attempts,
                )
            else:
                logger.exception(
                    "deferred refinement failed for alert_id=%s (attempt %s), leaving it pending",
                    alert.id, alert.refinement_attempts,
                )
        session.commit()
        time.sleep(throttle_seconds)

    if pending:
        logger.info("deferred refinement pass: %s of %s pending alerts refined", refined, len(pending))
    return refined
