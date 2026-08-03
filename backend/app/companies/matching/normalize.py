"""Canonical form for company names. Pure -- no I/O, no DB.

Every rung of the match ladder compares normalized strings for EXACT
equality. The old resolver's substring matching (``name in c.name or
c.name in name``) is what produced silent mismatches, so nothing here
introduces partial matching.

Geography tokens ("india", "bharat") are deliberately NOT stripped: they
discriminate between genuinely different companies (Apollo Tyres vs Apollo
Hospitals, Bharat Gears vs Bharat Seats), and removing them manufactures
collisions the ladder would then have to resolve by guessing.
"""
import re

# End-anchored only. "Co" inside "Coal India" is a word, not a suffix.
LEGAL_SUFFIXES = (
    "limited", "ltd", "private", "pvt", "corporation", "corp",
    "company", "co", "incorporated", "inc", "plc",
)

_PUNCTUATION = re.compile(r"[^a-z0-9\s]")
_WHITESPACE = re.compile(r"\s+")


def normalize_name(raw: str | None) -> str:
    if not raw:
        return ""
    text = raw.strip().lower().replace("&", " and ")
    text = _PUNCTUATION.sub("", text)
    text = _WHITESPACE.sub(" ", text).strip()
    if not text:
        return ""

    parts = text.split(" ")
    while len(parts) > 1 and parts[-1] in LEGAL_SUFFIXES:
        parts.pop()
    return " ".join(parts)


def tokens(raw: str | None) -> frozenset[str]:
    normalized = normalize_name(raw)
    return frozenset(normalized.split(" ")) if normalized else frozenset()
