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


# ---- Stage B: dossier history/developments from the FULL extract ----
# Plaintext extracts delimit sections with "== Heading ==" lines. Level-2
# headings partition the article; deeper levels ("=== 2020s ===") stay
# folded into their parent's body -- a decade subsection of History is
# still History.
_SECTION_HEADING = re.compile(r"^==\s*([^=].*?)\s*==\s*$", re.MULTILINE)

_HISTORY_HEADINGS = ("history", "corporate history", "company history")
_DEVELOPMENTS_HEADINGS = ("recent developments", "recent history", "recent events")

_YEAR = re.compile(r"\b(19|20)\d{2}\b")

# The dossier's history block reads as a few short paragraphs; developments
# as a brief pointer. Whole-sentence bounded, like the lead summary.
HISTORY_MAX_CHARS = 900
HISTORY_HARD_CHARS = 1400
DEVELOPMENTS_MAX_CHARS = 500
DEVELOPMENTS_HARD_CHARS = 800


def sections(full_extract: str) -> dict[str, str]:
    """{lowercased level-2 heading: body} for a full plaintext extract.
    The pre-heading lead is not returned (Stage A already owns the lead)."""
    text = full_extract or ""
    result: dict[str, str] = {}
    matches = list(_SECTION_HEADING.finditer(text))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        heading = match.group(1).strip().lower()
        # First occurrence wins -- a duplicated heading later in the page
        # (rare vandalism/format noise) must not overwrite the real one.
        result.setdefault(heading, text[start:end].strip())
    return result


def recent_paragraphs(section_text: str, cutoff_year: int, max_year: int) -> list[str]:
    """Paragraphs (blank-line separated) that carry a year token within
    [cutoff_year, max_year], original order. A paragraph with no year at
    all is unverifiable as 'recent' and is dropped, never guessed."""
    kept: list[str] = []
    for raw in (section_text or "").split("\n\n"):
        # Drop nested sub-heading LINES ("=== 2020s ===") but keep the
        # paragraph text they precede -- a sub-heading often shares its
        # blank-line block with the first paragraph beneath it.
        lines = [line for line in raw.split("\n") if not line.strip().startswith("=")]
        paragraph = " ".join(" ".join(lines).split())
        if not paragraph:
            continue
        years = [int(m.group(0)) for m in _YEAR.finditer(paragraph)]
        if any(cutoff_year <= year <= max_year for year in years):
            kept.append(paragraph)
    return kept


def bounded_text(paragraphs: list[str], max_chars: int, hard_chars: int) -> str | None:
    """Tail-anchored whole-sentence bounding: paragraphs arrive in
    chronological order, so when the budget forces a cut, the MOST RECENT
    (last) paragraphs are kept -- truncating from the front would keep the
    oldest of the 'recent' window and silently drop the newest material.
    None when nothing usable remains."""
    if not paragraphs:
        return None
    joined = " ".join(paragraphs)
    if len(joined) <= max_chars:
        return joined if len(joined) >= _MIN_DESCRIPTION_CHARS else None

    kept: list[str] = []
    total = 0
    for paragraph in reversed(paragraphs):
        if kept and total + len(paragraph) > max_chars:
            break
        kept.insert(0, paragraph)
        total += len(paragraph) + 1
    out = " ".join(kept)
    if len(out) > hard_chars:
        # A single paragraph larger than the whole budget: keep its TAIL
        # (the most recent sentences), opening on a sentence boundary.
        tail = out[-hard_chars:]
        split = _SENTENCE_SPLIT.split(tail)
        out = " ".join(split[1:]).strip() if len(split) > 1 else tail
    # No stub check here: this branch only runs when the source exceeded
    # the budget, so substance exists -- a short kept tail is still the
    # most recent real material, not a stub.
    return out or None


def find_section(section_map: dict[str, str], headings: tuple[str, ...]) -> str | None:
    for heading in headings:
        if heading in section_map:
            return section_map[heading]
    return None


def source_url(title: str) -> str:
    """Stable, human-checkable URL for the article a description came from.
    Stored alongside the text so any claim can be traced back."""
    import urllib.parse

    return "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"), safe="/:()',.-&!")
