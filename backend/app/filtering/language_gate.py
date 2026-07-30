"""English-only gate for the feed: the ingestion sources deliver the same
wire press release in several languages (Spanish/Japanese/Arabic
BusinessWire mirrors, confirmed in production), and a mixed-language feed
is broken UX -- the feed is ALWAYS English by default; other languages
come only from the user's own translation picker.

Deterministic, no LLM, no external dependency:
1. Script test -- a meaningful share of non-Latin letters (Devanagari,
   CJK, Arabic, Cyrillic, ...) means not-English.
2. Stopword test for Latin-script languages (Spanish/French/German/
   Portuguese mirrors look ASCII) -- compare hits of high-frequency
   English function words vs their foreign counterparts.

Fails OPEN (English) when there's no signal either way -- silently
dropping a real English story is worse than letting one odd headline
through.
"""
import re

_ENGLISH_STOPWORDS = {
    "the", "and", "of", "to", "in", "for", "on", "with", "at", "by", "from",
    "as", "is", "are", "was", "were", "be", "has", "have", "after", "over",
    "says", "said", "will", "its", "new", "up", "down", "amid", "into",
}

# High-frequency function words that are distinctive of the non-English
# Latin-script languages the wire mirrors actually arrive in (es/fr/de/pt/it).
# Deliberately excludes words that are also common English words.
_FOREIGN_STOPWORDS = {
    # Spanish / Portuguese
    "el", "la", "los", "las", "una", "uno", "del", "para", "por", "con",
    "su", "sus", "como", "más", "año", "años", "empresa", "acciones",
    "anuncia", "inicia", "sobre", "entre", "hasta", "según", "millones",
    "com", "uma", "não", "são", "após", "milhões",
    # French
    "le", "les", "des", "une", "du", "et", "dans", "pour", "sur", "avec",
    "aux", "été", "après", "millions",
    # German
    "der", "die", "das", "und", "für", "mit", "von", "nach", "über", "bei",
    "eine", "einen", "wird", "hat", "millionen",
    # Italian
    "il", "gli", "della", "delle", "nel", "per", "con", "una", "più",
}

_NON_LATIN_SHARE_THRESHOLD = 0.15


def is_english_text(title: str, content: str = "") -> bool:
    sample = f"{title} {content[:500]}"

    letters = [ch for ch in sample if ch.isalpha()]
    if not letters:
        return True  # numbers/tickers only -- no language signal, fail open
    non_latin = sum(1 for ch in letters if ord(ch) > 0x024F)
    if non_latin / len(letters) > _NON_LATIN_SHARE_THRESHOLD:
        return False

    words = re.findall(r"[a-záéíóúñüàèçäöûêôîãõ]+", sample.lower())
    english_hits = sum(1 for w in words if w in _ENGLISH_STOPWORDS)
    foreign_hits = sum(1 for w in words if w in _FOREIGN_STOPWORDS)
    if foreign_hits > english_hits:
        return False
    return True
