import json
import os

from openai import OpenAI

from app.analysis.claude_client import MODEL, GROQ_BASE_URL, AnthropicAdapter, RotatingClient
from app.translation import nllb_translator
from app.translation.languages import LANG_NAMES, TARGET_LANGS

# Self-hosted (NLLB via CTranslate2, see nllb_translator.py) is the
# ideal default: no per-minute token cap, no cost, no cross-account key
# juggling. But it loads a 1.3B-parameter model (int8-quantized) into
# process memory on first use and keeps it resident for the process's
# whole life -- confirmed in production (2026-07-24 crash investigation):
# the Railway deploy target for this service is too small to hold that
# model alongside FastAPI + scheduler + DB pool, and the process was
# silently OOM-killed a few translation cycles after boot (no exception,
# no traceback -- just the container killing the process).
#
# Provider reality check (2026-07-30, verified live against every
# provisioned key): Anthropic 401 (invalid key), OpenAI 429 (quota
# exhausted), OpenRouter 401 (dead key), Gemini 429 (quota exhausted) --
# Groq is the only working provider. Its pain point was model CHOICE, not
# the provider: translation previously shared llama-3.3-70b with the
# analysis pipeline, and Groq rate-limits PER MODEL, so analysis traffic
# 429-starved translation into multi-minute, frozen-looking drains.
# Translation now runs on openai/gpt-oss-120b -- its own per-model quota
# bucket (no contention with analysis), verified live to produce clean
# native-script output through this exact tool schema. Override with the
# TRANSLATION_PROVIDER env var ("nllb" | "anthropic" | "groq").
TRANSLATION_PROVIDER = os.environ.get("TRANSLATION_PROVIDER", "groq").strip().lower()
TRANSLATION_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"

# openai/gpt-oss-120b, deliberately NOT the analysis pipeline's MODEL
# (llama-3.3-70b-versatile): Groq rate-limits per model, and sharing the
# analysis model's bucket meant analysis traffic 429-starved translation
# (confirmed in production: a 429 storm capped every recent alert's
# translation). gpt-oss-120b has its own quota bucket and was verified
# live to produce clean native-script output through this exact
# multi-field tool schema. (The smaller candidates fail it: 8b-instant
# returns Romanized Hinglish, gpt-oss-20b couldn't hold the schema,
# qwen3.6-27b fails the forced tool call outright -- all verified live.)
TRANSLATION_MODEL = "openai/gpt-oss-120b"

# Groq's free tier still caps per-minute tokens, but translation now has
# its OWN per-model bucket (gpt-oss-120b, nothing else uses it) -- the old
# 20s spacing existed to survive sharing the analysis model's bucket. A
# light delay keeps a full-language drain inside the per-minute budget
# without making the progress bar look frozen. Anthropic has no such
# per-minute wall at this account's scale, so it runs several calls at
# once with no artificial delay. See job.py's MAX_CONCURRENT_TRANSLATIONS.
RECOMMENDED_THROTTLE_SECONDS = 3.0 if TRANSLATION_PROVIDER == "groq" else 0.0

SYSTEM_PROMPT = (
    "You are a professional financial-news translator working across English "
    "and major Indian languages. You translate faithfully and naturally, in "
    "a neutral news register -- never summarizing, never adding commentary, "
    "never dropping information. You NEVER translate or transliterate company "
    "names, stock tickers, or numeric figures (percentages, currency amounts, "
    "dates) -- those are copied through byte-for-byte identical in every "
    "language. Rationale text keeps its original sentence/paragraph "
    "structure; key_points stay short terse fragments (not full sentences), "
    "matching the style of the source.\n\n"
    "CRITICAL: every text field you record (title, content, rationale, "
    "key_points, labels) MUST be written entirely in the target language's "
    "own script. Returning the English source text unchanged in an output "
    "field is ALWAYS wrong, even for short or seemingly-simple phrases -- "
    "there is no such thing as text that doesn't need translating. Before "
    "recording your answer, check every field: if it still reads as "
    "English, translate it before calling the tool."
)


def build_translation_client(
    groq_api_keys: list[str], anthropic_api_key: str | None = None
) -> RotatingClient | OpenAI | AnthropicAdapter | None:
    """A single client -- used for the low-volume category-translation path,
    which doesn't need per-lane parallelism (see build_translation_clients
    for the alert-translation path, which does). NLLB needs no client at
    all (no API key, local model) -- translate_categories ignores it."""
    if TRANSLATION_PROVIDER == "nllb":
        return None
    if TRANSLATION_PROVIDER == "anthropic":
        if not anthropic_api_key:
            raise ValueError("TRANSLATION_PROVIDER is 'anthropic' but no anthropic_api_key was given")
        return AnthropicAdapter(anthropic_api_key, model=TRANSLATION_ANTHROPIC_MODEL)
    if len(groq_api_keys) > 1:
        return RotatingClient(groq_api_keys, base_url=GROQ_BASE_URL)
    return OpenAI(api_key=groq_api_keys[0], base_url=GROQ_BASE_URL)


# On Anthropic (no per-minute wall at this account's scale), this many
# concurrent requests share ONE client/key safely -- there's only one
# account, so "lanes" don't map to distinct quota buckets the way they do
# on Groq.
ANTHROPIC_CONCURRENCY = 6


def build_translation_clients(
    groq_api_keys: list[str], anthropic_api_key: str | None = None
) -> list[RotatingClient | OpenAI | AnthropicAdapter | None]:
    """One entry per independent lane translate_pending_alerts should run
    concurrently (see job.py). For Groq, `groq_api_keys` must be keys from
    genuinely SEPARATE accounts (separate per-minute quota buckets) -- pass
    Settings.translation_groq_api_keys here, not groq_api_keys_extra, which
    are same-org rotation keys sharing ONE bucket and wouldn't add real
    parallel throughput (they'd just have two lanes racing for the same
    budget). Each key gets its own client/lane, throttled independently
    within that lane. For Anthropic, returns the SAME client repeated
    ANTHROPIC_CONCURRENCY times -- true concurrent requests on one client,
    no per-lane throttling needed. For NLLB, always a single `[None]` lane
    -- it's one local model instance, not a per-account quota; CTranslate2
    already parallelizes internally (nllb_translator.py's inter_threads),
    so extra Python-level lanes would just have threads fight over the same
    CPU cores and model handle for no real throughput gain.
    """
    if TRANSLATION_PROVIDER == "nllb":
        return [None]
    if TRANSLATION_PROVIDER == "anthropic":
        if not anthropic_api_key:
            raise ValueError("TRANSLATION_PROVIDER is 'anthropic' but no anthropic_api_key was given")
        client = AnthropicAdapter(anthropic_api_key, model=TRANSLATION_ANTHROPIC_MODEL)
        return [client] * ANTHROPIC_CONCURRENCY
    if not groq_api_keys:
        raise ValueError("TRANSLATION_PROVIDER is 'groq' but no groq_api_keys were given")
    return [OpenAI(api_key=key, base_url=GROQ_BASE_URL) for key in groq_api_keys]


def _alert_translation_schema(num_companies: int) -> dict:
    # NOTE on the summary_short/summary_long and per-company `why` fields
    # (spec-v2 card surfaces): the source value may be an empty string when
    # the alert predates those fields or the LLM refinement never produced
    # them -- the model is asked to return an empty string back for an
    # empty input, and validation skips script checks on empty fields.
    company_schema = {
        "type": "object",
        "properties": {
            "rationale": {"type": "string"},
            "key_points": {"type": "array", "items": {"type": "string"}},
            "why": {"type": "string"},
        },
        "required": ["rationale", "key_points", "why"],
    }
    return {
        "type": "function",
        "function": {
            "name": "record_translation",
            "description": (
                "Record the translation of the article title/content, the "
                "event summaries, and each company's rationale/key_points/"
                "why into ONE target language. The `companies` array MUST "
                "be in EXACTLY the same order as the input -- position i "
                "corresponds to position i in the input list. An input "
                "field given as an empty string is returned as an empty "
                "string. Never translate or transliterate company names, "
                "tickers, or numbers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "summary_short": {"type": "string"},
                    "summary_long": {"type": "string"},
                    "companies": {
                        "type": "array",
                        "items": company_schema,
                        "minItems": num_companies,
                        "maxItems": num_companies,
                    },
                },
                "required": ["title", "content", "summary_short", "summary_long", "companies"],
            },
        },
    }


def translate_alert(
    client, *, lang: str, title: str, content: str, companies: list[dict],
    summary_short: str = "", summary_long: str = "",
) -> dict:
    """One Groq call translating a single article's title/content plus every
    one of its companies' rationale/key_points into ONE target language.

    Deliberately one call per (alert, language) rather than one call
    covering every language at once: a single multi-language call requests
    far more output tokens than Groq's tokens-per-minute cap allows on this
    account's tier for FALLBACK_MODEL (confirmed in production -- a 9-
    language combined call was rejected outright with a 413 "Request too
    large" TPM error), and asking the model for 9 languages' worth of
    nested JSON in one shot measurably increased schema-adherence failures
    on this smaller model. A single language's output is small and simple
    enough to fit comfortably under the per-minute budget and to get right.

    `companies` is `[{"rationale": ..., "key_points": [...], "why": ...},
    ...]` (why may be an empty string), in the same order as the Alert's
    AlertCompany rows -- the response's `companies` array is returned in
    that same positional order so callers can zip it back onto the
    original rows by index. summary_short/summary_long are the alert's
    event summaries (spec-v2 card gist), empty strings when absent.

    Returns `{"title": ..., "content": ..., "summary_short": ...,
    "summary_long": ..., "companies": [...]}` for the requested language.
    """
    if TRANSLATION_PROVIDER == "nllb":
        return nllb_translator.translate_alert(
            lang=lang, title=title, content=content, companies=companies,
            summary_short=summary_short, summary_long=summary_long,
        )
    companies_text = "\n".join(
        f"{i + 1}. Rationale: {c['rationale']}\n   Key points: {c['key_points']}\n   Why: {c.get('why') or '(empty)'}"
        for i, c in enumerate(companies)
    )
    user_content = (
        f"Translate the following into {LANG_NAMES[lang]}.\n\n"
        f"Title: {title}\n\nContent: {content or '(no content)'}\n\n"
        f"Summary short: {summary_short or '(empty)'}\n\n"
        f"Summary long: {summary_long or '(empty)'}\n\n"
        f"Companies (translate each rationale/key_points/why, preserve this "
        f"exact order, a field marked (empty) is recorded as an empty string, "
        f"do not translate company names -- none are given here, only "
        f"reasoning text):\n{companies_text or '(no companies)'}"
    )

    response = client.chat.completions.create(
        model=TRANSLATION_MODEL,
        # Matches the single-language ANALYSIS call's budget on this same
        # model (claude_client.py) -- that value was tuned up from 1024
        # after real truncation/parse failures on a similarly-shaped
        # multi-company response, and translation output is comparable in
        # size to the source it's translating. A truncated response fails
        # here anyway (missing/malformed JSON -> caught, retried), so
        # there's no cost to erring generous.
        max_tokens=4096,
        tools=[_alert_translation_schema(len(companies))],
        tool_choice={"type": "function", "function": {"name": "record_translation"}},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    )

    message = response.choices[0].message
    tool_calls = message.tool_calls or []
    tool_call = next((tc for tc in tool_calls if tc.function.name == "record_translation"), None)
    if tool_call is None:
        raise ValueError(f"Translation response contained no tool_use block for article: {title!r}")
    return json.loads(tool_call.function.arguments)


def _category_translation_schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "record_category_translations",
            "description": (
                "Translate each category label into the requested "
                "language. The output array MUST be the same length and "
                "same order as the input categories list."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "labels": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["labels"],
            },
        },
    }


def translate_categories(client, lang: str, categories: list[str]) -> list[str]:
    """One call translating a batch of distinct category strings (e.g.
    "oil_energy", "banking") into ONE target language -- category batches
    are small/cheap regardless of language count, so (unlike per-alert
    translation) batching multiple categories into a single per-language
    call stays comfortably under the TPM cap. Returns translated labels in
    the same order as `categories`.
    """
    if TRANSLATION_PROVIDER == "nllb":
        # NLLB is a pure translation model, not instruction-following -- it
        # has no prompt to tell it "oil_energy" means "Oil & Energy", so
        # underscore-joined category strings must be turned into an actual
        # English phrase before translation, same substitution the LLM
        # prompt spells out in words for itself below.
        phrases = [c.replace("_", " ").title() for c in categories]
        return nllb_translator.translate_categories(phrases, lang)
    numbered = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(categories))
    response = client.chat.completions.create(
        model=TRANSLATION_MODEL,
        max_tokens=2048,
        tools=[_category_translation_schema()],
        tool_choice={"type": "function", "function": {"name": "record_category_translations"}},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Translate each of these news category labels (underscores "
                    "mean separate words, e.g. 'oil_energy' means 'Oil & "
                    f"Energy') into {LANG_NAMES[lang]}, same order, same "
                    f"count:\n{numbered}"
                ),
            },
        ],
    )
    message = response.choices[0].message
    tool_calls = message.tool_calls or []
    tool_call = next(
        (tc for tc in tool_calls if tc.function.name == "record_category_translations"), None
    )
    if tool_call is None:
        raise ValueError("Category translation response contained no tool_use block")
    return json.loads(tool_call.function.arguments)["labels"]
