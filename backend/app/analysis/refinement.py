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
import time

from openai import RateLimitError

from app.analysis.claude_client import FALLBACK_MODEL, MODEL, SYSTEM_PROMPT, tier_kwargs
from app.config import settings
from app.models import AlertRippleLayer, Company, TimelineEffect
from app.reasoning.compliance import validate_or_none

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
    "confirmed event is false."
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
    "buy/sell/hold language."
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
        return client.chat.completions.create(
            model=model, max_tokens=1536, tools=[tool],
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
            return []
        arguments = json.loads(tool_call.function.arguments)

        known_tickers = {c["ticker"] for c in companies}
        seen: set[str] = set()
        validated = []
        for layer in arguments.get("layers", []):
            if layer.get("relationship") not in RIPPLE_RELATIONSHIP_TYPES:
                continue
            layer_title = validate_or_none(layer.get("title"))
            note = validate_or_none(layer.get("note"))
            if not layer_title or not note:
                continue
            tickers = [
                t for t in layer.get("tickers", [])
                if t in known_tickers and t not in seen
            ]
            if not tickers:
                continue
            seen.update(tickers)
            validated.append({
                "title": layer_title, "relationship": layer["relationship"],
                "note": note, "tickers": tickers,
            })
        return validated
    except Exception:
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

    summary = generate_event_summary(client, article.title, facts)
    if summary:
        alert.summary_short = summary.get("summary_short")
        alert.summary_long = summary.get("summary_long")
        if summary.get("is_unconfirmed") is not None:
            alert.is_unconfirmed = 1 if summary["is_unconfirmed"] else 0

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

    for effect in generate_timeline_effects(client, article.title, facts):
        session.add(TimelineEffect(alert_id=alert.id, horizon=effect["horizon"], description=effect["description"]))

    # Story-adaptive card-back sections (spec §5): every affected company
    # (measured or exposure-only) is offered to the model for grouping --
    # exposure rows still belong in a section, they just carry no number.
    layer_companies = []
    for ac in alert_companies:
        company = session.get(Company, ac.company_id)
        if company is None:
            continue
        layer_companies.append({
            "ticker": company.ticker, "name": company.name,
            "sector": company.sector, "sub_sector": company.sub_sector,
            "direction": ac.direction, "why": ac.why,
        })
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
