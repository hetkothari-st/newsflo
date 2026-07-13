import json

from openai import OpenAI

from app.analysis.claude_client import FALLBACK_MODEL, GROQ_BASE_URL, AnthropicAdapter, RotatingClient
from app.translation.languages import LANG_NAMES, TARGET_LANGS

# TEMPORARY, for testing only -- set back to "groq" once done testing (the
# original Groq-only design still applies then: see the comment that used to
# live here about keeping translation off Anthropic's credit). While "on",
# every translation call goes through Anthropic instead of Groq, using the
# cheapest current model to keep token cost down; this sidesteps Groq's free-
# tier per-minute token cap (confirmed in production to reject even a single
# per-language alert-translation call) while testing the feature end-to-end.
TRANSLATION_PROVIDER = "anthropic"  # "anthropic" | "groq"
TRANSLATION_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"

TRANSLATION_MODEL = FALLBACK_MODEL

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
    if TRANSLATION_PROVIDER == "anthropic":
        if not anthropic_api_key:
            raise ValueError("TRANSLATION_PROVIDER is 'anthropic' but no anthropic_api_key was given")
        return AnthropicAdapter(anthropic_api_key, model=TRANSLATION_ANTHROPIC_MODEL)
    if len(groq_api_keys) > 1:
        return RotatingClient(groq_api_keys, base_url=GROQ_BASE_URL)
    return OpenAI(api_key=groq_api_keys[0], base_url=GROQ_BASE_URL)


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
        # Groq's TPM limit is checked against REQUESTED tokens (prompt +
        # max_tokens), not actual usage -- so max_tokens directly eats into
        # the per-minute budget whether or not the model uses it all. One
        # language's title/content/rationale/key_points for up to 5
        # companies is realistically well under 2048 output tokens; keeping
        # the ceiling here (rather than reusing the 4096 the single-language
        # ANALYSIS call needs, which reasons from scratch rather than
        # translating existing text) leaves headroom to fit multiple calls
        # inside this account's 6000 TPM cap on FALLBACK_MODEL.
        max_tokens=2048,
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
