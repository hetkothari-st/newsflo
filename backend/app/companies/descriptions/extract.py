"""Stage 2: pure. Parses a snapshotted Wikipedia page into (a) the exchange
identifiers that PROVE which company the article is about and (b) the
description sentence itself. No network, no DB.

The two halves are deliberately separate. Identifiers decide WHETHER we may
use an article at all; the text decides WHAT we store. An article that
yields good text but no identifier is discarded -- omit rather than
mismatch.
"""
import re

# Infobox templates only. Deliberately NOT bare "BSE: 500325" or a
# bseindia.com URL: article bodies cite the exchange's site for unrelated
# companies (a competitor's filing, an acquisition target's shareholding
# page), and a citation URL is not a claim about who the article is about.
# The {{BSE|...}}/{{NSE|...}} templates only ever appear in `traded_as`.
#
# Non-matches this must keep on rejecting:
#   {{LSE|RIGD}}        -- a different exchange, same shape
#   [[BSE SENSEX]]      -- a wikilink to an index, no pipe after "BSE"
#   {{BSE SENSEX}}      -- a template for the index, no pipe after "BSE"
_BSE_TEMPLATE = re.compile(r"\{\{\s*bse\s*\|\s*(\d{6})\s*(?:\||\}\})", re.IGNORECASE)
_NSE_TEMPLATE = re.compile(r"\{\{\s*nse\s*\|\s*([A-Za-z0-9&\-]{1,20})\s*(?:\||\}\})", re.IGNORECASE)
# Indian equity ISINs are INE + 9 alphanumerics. INF is mutual funds, INn is
# debt -- neither is in `companies`, so restricting to INE costs nothing and
# keeps the pattern from matching prose.
_ISIN = re.compile(r"\b(INE[0-9A-Z]{9})\b")

_MIN_DESCRIPTION_CHARS = 40
_MAX_DESCRIPTION_CHARS = 400
_HARD_TRUNCATE_CHARS = 600

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# A lead that begins like this is not about a company.
_REJECT_PREFIXES = (
    "this article",
    "this is a list",
)
# "<Name> may refer to:" -- the index-page lead. It is not a prefix: the
# phrase follows the title. Bounded to the opening so a company whose real
# description happens to contain the words further down survives.
_REJECT_PHRASES = ("may refer to",)
_REJECT_PHRASE_WINDOW = 120


class ArticleRefs:
    """Exchange identifiers found in one article's wikitext."""

    __slots__ = ("bse_codes", "nse_symbols", "isins")

    def __init__(self, bse_codes: set[str], nse_symbols: set[str], isins: set[str]):
        self.bse_codes = bse_codes
        self.nse_symbols = nse_symbols
        self.isins = isins

    def __bool__(self) -> bool:
        return bool(self.bse_codes or self.nse_symbols or self.isins)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"ArticleRefs(bse={sorted(self.bse_codes)}, "
            f"nse={sorted(self.nse_symbols)}, isin={sorted(self.isins)})"
        )


def parse_refs(wikitext: str) -> ArticleRefs:
    """Exchange identifiers asserted by the article's infobox.

    Returns every identifier found, including contradictory ones. Deciding
    that two identifiers point at two different companies is the loader's
    job -- it is the only layer that knows what a code resolves to."""
    if not wikitext:
        return ArticleRefs(set(), set(), set())
    return ArticleRefs(
        bse_codes={m for m in _BSE_TEMPLATE.findall(wikitext)},
        nse_symbols={m.upper() for m in _NSE_TEMPLATE.findall(wikitext)},
        isins={m for m in _ISIN.findall(wikitext)},
    )


def is_disambiguation(wikitext: str) -> bool:
    lowered = (wikitext or "").lower()
    return "{{disambiguation" in lowered or "{{disambig" in lowered


def summarize(extract_text: str) -> str | None:
    """Whole sentences from the article lead, up to ~400 characters.

    Returns None when there is nothing worth storing -- a stub, a
    disambiguation lead, an empty extract. None means "leave the column
    alone", never "write an empty string": a blank description renders as a
    confidently empty answer, which is worse than no answer.
    """
    text = " ".join((extract_text or "").split())
    if not text:
        return None

    lowered = text.lower()
    if any(lowered.startswith(prefix) for prefix in _REJECT_PREFIXES):
        return None
    opening = lowered[:_REJECT_PHRASE_WINDOW]
    if any(phrase in opening for phrase in _REJECT_PHRASES):
        return None

    sentences = _SENTENCE_SPLIT.split(text)
    out = ""
    for sentence in sentences:
        candidate = f"{out} {sentence}".strip() if out else sentence
        if out and len(candidate) > _MAX_DESCRIPTION_CHARS:
            break
        out = candidate
        if len(out) >= _MAX_DESCRIPTION_CHARS:
            break

    # A single opening sentence longer than the whole budget: keep it rather
    # than discard the article, but do not let it run unbounded.
    if len(out) > _HARD_TRUNCATE_CHARS:
        out = out[:_HARD_TRUNCATE_CHARS].rsplit(" ", 1)[0].rstrip(",;:") + "…"

    if len(out) < _MIN_DESCRIPTION_CHARS:
        return None
    return out


def source_url(title: str) -> str:
    """Stable, human-checkable URL for the article a description came from.
    Stored alongside the text so any claim can be traced back."""
    import urllib.parse

    return "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"), safe="/:()',.-&!")
