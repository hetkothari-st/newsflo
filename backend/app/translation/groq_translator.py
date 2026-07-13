import json

from openai import OpenAI

from app.analysis.claude_client import FALLBACK_MODEL, GROQ_BASE_URL, RotatingClient
from app.translation.languages import LANG_NAMES, TARGET_LANGS

# Translation deliberately never routes through Anthropic (unlike
# app.analysis.claude_client.build_client, which is Anthropic-first) -- it is
# a strictly easier task than financial analysis, and keeping it Groq-only
# means the multi-language rollout never competes for Anthropic credit. It also
# deliberately always uses FALLBACK_MODEL rather than MODEL: FALLBACK_MODEL
# has its own, separate Groq daily-quota bucket (see claude_client.py's
# comment on this), so translation traffic can never cannibalize the
# analysis pipeline's MODEL budget -- the two features simply cannot starve
# each other.
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
    "matching the style of the source."
)


def build_translation_client(groq_api_keys: list[str]) -> RotatingClient | OpenAI:
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
    per_lang_schema = {
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
    }
    return {
        "type": "function",
        "function": {
            "name": "record_translations",
            "description": (
                "Translate the article title/content and each company's "
                "rationale/key_points into every requested language. The "
                "`companies` array in each language MUST be in EXACTLY the "
                "same order as the input -- position i corresponds to "
                "position i in the input list. Never translate or "
                "transliterate company names, tickers, or numbers."
            ),
            "parameters": {
                "type": "object",
                "properties": {lang: per_lang_schema for lang in TARGET_LANGS},
                "required": TARGET_LANGS,
            },
        },
    }


def translate_alert(client, *, title: str, content: str, companies: list[dict]) -> dict:
    """One Groq call translating an article's title/content plus every one of
    its companies' rationale/key_points into all TARGET_LANGS languages at once.

    `companies` is `[{"rationale": ..., "key_points": [...]}, ...]`, in the
    same order as the Alert's AlertCompany rows -- the response's per-language
    `companies` arrays are returned in that same positional order so callers
    can zip them back onto the original rows by index.

    Returns `{lang: {"title": ..., "content": ..., "companies": [...]}, ...}`
    for every lang in TARGET_LANGS.
    """
    companies_text = "\n".join(
        f"{i + 1}. Rationale: {c['rationale']}\n   Key points: {c['key_points']}"
        for i, c in enumerate(companies)
    )
    user_content = (
        f"Translate the following into {', '.join(LANG_NAMES.values())}.\n\n"
        f"Title: {title}\n\nContent: {content or '(no content)'}\n\n"
        f"Companies (translate each rationale/key_points, preserve this exact "
        f"order, do not translate company names -- none are given here, only "
        f"reasoning text):\n{companies_text or '(no companies)'}"
    )

    response = client.chat.completions.create(
        model=TRANSLATION_MODEL,
        # TARGET_LANGS languages x up to 5 companies' rationale+key_points is
        # substantially more output than the single-language analysis call
        # (which needed 4096, see claude_client.py) -- budgeted up accordingly
        # to avoid the same truncation/parse-failure trap. Scales with
        # len(TARGET_LANGS); re-check this budget if more languages are added.
        max_tokens=16000,
        tools=[_alert_translation_schema(len(companies))],
        tool_choice={"type": "function", "function": {"name": "record_translations"}},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    )

    message = response.choices[0].message
    tool_calls = message.tool_calls or []
    tool_call = next((tc for tc in tool_calls if tc.function.name == "record_translations"), None)
    if tool_call is None:
        raise ValueError(f"Translation response contained no tool_use block for article: {title!r}")
    return json.loads(tool_call.function.arguments)


def _category_translation_schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "record_category_translations",
            "description": (
                "Translate each category label into every requested "
                "language. Each language's array MUST be the same length "
                "and same order as the input categories list."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    lang: {"type": "array", "items": {"type": "string"}} for lang in TARGET_LANGS
                },
                "required": TARGET_LANGS,
            },
        },
    }


def translate_categories(client, categories: list[str]) -> dict:
    """One call translating a batch of distinct category strings (e.g.
    "oil_energy", "banking") into all TARGET_LANGS languages. Returns
    `{lang: [translated_label, ...]}` in the same order as `categories`.
    """
    numbered = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(categories))
    response = client.chat.completions.create(
        model=TRANSLATION_MODEL,
        max_tokens=4096,
        tools=[_category_translation_schema()],
        tool_choice={"type": "function", "function": {"name": "record_category_translations"}},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Translate each of these news category labels (underscores "
                    "mean separate words, e.g. 'oil_energy' means 'Oil & "
                    f"Energy') into {', '.join(LANG_NAMES.values())}, same "
                    f"order, same count:\n{numbered}"
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
    return json.loads(tool_call.function.arguments)
