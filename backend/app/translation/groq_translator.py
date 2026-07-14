import json

from openai import OpenAI

from app.analysis.claude_client import MODEL, GROQ_BASE_URL, AnthropicAdapter, RotatingClient
from app.translation.languages import LANG_NAMES, TARGET_LANGS

# Anthropic hit this account's usage cap (confirmed in production: every
# call started failing with "You have reached your specified API usage
# limits", not resetting until 2026-08-01) -- back on Groq, whose free-tier
# limit is a continuously-renewing per-MINUTE cap rather than an exhausted
# account-wide one. Flip to "anthropic" again once that cap resets or a
# funded/higher-limit key is available.
TRANSLATION_PROVIDER = "groq"  # "anthropic" | "groq"
TRANSLATION_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"

# Deliberately MODEL (llama-3.3-70b-versatile), not FALLBACK_MODEL, despite
# the analysis pipeline's own preference for keeping translation off MODEL's
# shared quota bucket (see claude_client.py). Confirmed in production:
# FALLBACK_MODEL's structured-output reliability on this multi-field
# translation schema was bad enough to be unusable -- most calls either
# failed the tool call outright ("Failed to call a function") or, worse,
# silently returned garbage (Romanized Hinglish, or once literal Japanese,
# instead of the requested language). MODEL was reliable across repeated
# trials. Translation's call volume stays low (throttled, small batches),
# so the contention risk with the analysis pipeline's own MODEL usage is
# accepted as the lesser problem.
TRANSLATION_MODEL = MODEL

# Groq's free tier caps translation calls at a small tokens-per-minute
# budget (confirmed in production: a single combined multi-language call was
# rejected outright at ~17000 requested tokens against FALLBACK_MODEL's 6000
# TPM limit) -- concurrent calls would each eat into that same shared budget
# within the same rolling minute, so Groq gets throttled down to fully
# sequential with real spacing between calls. Anthropic has no such
# per-minute wall at this account's scale, so it runs several calls at once
# with no artificial delay. See job.py's MAX_CONCURRENT_TRANSLATIONS.
RECOMMENDED_THROTTLE_SECONDS = 20.0 if TRANSLATION_PROVIDER == "groq" else 0.0

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
) -> RotatingClient | OpenAI | AnthropicAdapter:
    """A single client -- used for the low-volume category-translation path,
    which doesn't need per-lane parallelism (see build_translation_clients
    for the alert-translation path, which does)."""
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
) -> list[RotatingClient | OpenAI | AnthropicAdapter]:
    """One entry per independent lane translate_pending_alerts should run
    concurrently (see job.py). For Groq, `groq_api_keys` must be keys from
    genuinely SEPARATE accounts (separate per-minute quota buckets) -- pass
    Settings.translation_groq_api_keys here, not groq_api_keys_extra, which
    are same-org rotation keys sharing ONE bucket and wouldn't add real
    parallel throughput (they'd just have two lanes racing for the same
    budget). Each key gets its own client/lane, throttled independently
    within that lane. For Anthropic, returns the SAME client repeated
    ANTHROPIC_CONCURRENCY times -- true concurrent requests on one client,
    no per-lane throttling needed.
    """
    if TRANSLATION_PROVIDER == "anthropic":
        if not anthropic_api_key:
            raise ValueError("TRANSLATION_PROVIDER is 'anthropic' but no anthropic_api_key was given")
        client = AnthropicAdapter(anthropic_api_key, model=TRANSLATION_ANTHROPIC_MODEL)
        return [client] * ANTHROPIC_CONCURRENCY
    if not groq_api_keys:
        raise ValueError("TRANSLATION_PROVIDER is 'groq' but no groq_api_keys were given")
    return [OpenAI(api_key=key, base_url=GROQ_BASE_URL) for key in groq_api_keys]


def _alert_translation_schema(num_companies: int) -> dict:
    company_schema = {
        "type": "object",
        "properties": {
            "rationale": {"type": "string"},
            "key_points": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["rationale", "key_points"],
    }
    return {
        "type": "function",
        "function": {
            "name": "record_translation",
            "description": (
                "Record the translation of the article title/content and "
                "each company's rationale/key_points into ONE target "
                "language. The `companies` array MUST be in EXACTLY the "
                "same order as the input -- position i corresponds to "
                "position i in the input list. Never translate or "
                "transliterate company names, tickers, or numbers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "companies": {
                        "type": "array",
                        "items": company_schema,
                        "minItems": num_companies,
                        "maxItems": num_companies,
                    },
                },
                "required": ["title", "content", "companies"],
            },
        },
    }


def translate_alert(client, *, lang: str, title: str, content: str, companies: list[dict]) -> dict:
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

    `companies` is `[{"rationale": ..., "key_points": [...]}, ...]`, in the
    same order as the Alert's AlertCompany rows -- the response's
    `companies` array is returned in that same positional order so callers
    can zip it back onto the original rows by index.

    Returns `{"title": ..., "content": ..., "companies": [...]}` for the
    requested language.
    """
    companies_text = "\n".join(
        f"{i + 1}. Rationale: {c['rationale']}\n   Key points: {c['key_points']}"
        for i, c in enumerate(companies)
    )
    user_content = (
        f"Translate the following into {LANG_NAMES[lang]}.\n\n"
        f"Title: {title}\n\nContent: {content or '(no content)'}\n\n"
        f"Companies (translate each rationale/key_points, preserve this exact "
        f"order, do not translate company names -- none are given here, only "
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
