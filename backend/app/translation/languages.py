# The languages news content gets machine-translated into. English is the
# language everything is stored/analyzed in already, so it is never itself a
# translation target -- there is no ArticleTranslation/etc. row for "en".
TARGET_LANGS = ["hi", "mr", "gu", "ml", "te", "ta", "kn", "pa", "bn"]

# Used only inside Groq prompts (telling the model which language is which
# code) -- never shown in the UI, which renders each language's own native
# name (see frontend/src/lib/i18n.ts) instead of these English names.
LANG_NAMES = {
    "hi": "Hindi",
    "mr": "Marathi",
    "gu": "Gujarati",
    "ml": "Malayalam",
    "te": "Telugu",
    "ta": "Tamil",
    "kn": "Kannada",
    "pa": "Punjabi",
    "bn": "Bengali",
}

ALL_LANGS = ["en", *TARGET_LANGS]


def normalize_lang(lang: str | None) -> str:
    """Any unrecognized/missing lang silently maps to English -- callers never
    need to validate `lang` themselves before querying translation tables."""
    return lang if lang in ALL_LANGS else "en"
