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


# Unicode block each language's native script lives in -- (first, last)
# codepoint inclusive. Used to catch a real failure mode confirmed in
# production: the model returns text that isn't English (so the "echoed
# English" guard misses it) but also isn't actually in the requested
# language -- e.g. Hindi asked for and got Romanized Hinglish ("US iran ke
# tel niryat...") or, once, Japanese. A response with zero characters in
# its target script is essentially never a real translation, English or
# otherwise, into that language.
SCRIPT_RANGES = {
    "hi": (0x0900, 0x097F),  # Devanagari
    "mr": (0x0900, 0x097F),  # Devanagari
    "gu": (0x0A80, 0x0AFF),  # Gujarati
    "ml": (0x0D00, 0x0D7F),  # Malayalam
    "te": (0x0C00, 0x0C7F),  # Telugu
    "ta": (0x0B80, 0x0BFF),  # Tamil
    "kn": (0x0C80, 0x0CFF),  # Kannada
    "pa": (0x0A00, 0x0A7F),  # Gurmukhi
    "bn": (0x0980, 0x09FF),  # Bengali
}


def has_expected_script(lang: str, text: str) -> bool:
    """True if `text` contains at least one character from the script
    `lang` is natively written in -- False for empty/very short text (not
    enough signal either way) so callers should only treat False as a real
    failure for non-trivial text."""
    lo, hi = SCRIPT_RANGES.get(lang, (None, None))
    if lo is None:
        return True  # no known script range for this lang -- don't gate on it
    return any(lo <= ord(ch) <= hi for ch in text)
