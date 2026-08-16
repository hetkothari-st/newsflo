"""THE ANTI-HALLUCINATION GATE FOR THE LEDGER ITSELF (phase file Task 1.3).

    "an ExposureProposal without a non-empty excerpt that literally appears
     in the source document is discarded"

Everything else in V5 protects the OUTPUT from fabrication. This protects the
INPUT: a fabricated excerpt that gets past this check becomes a permanent,
sourced-looking ledger row that every later event computes on, and no
downstream firewall can catch it because by then it IS the record.

THE CHECKS, in the order they run:

  1. an excerpt exists and is long enough to locate a claim. `MIN_EXCERPT_CHARS`
     exists because "the" appears verbatim in every filing ever written: a
     containment test over a fragment is not evidence of anything.
  2. the proposal says WHERE (source_page). A claim nobody can turn back to
     a page is not reviewable, and review is the only path into the ledger.
  3. the excerpt appears in the document text, after whitespace
     normalisation ONLY (see documents.normalize_whitespace -- no case
     folding, no punctuation stripping; each extra normalisation widens what
     counts as "the document said this").
  4. the excerpt appears ON the cited page. A citation that does not locate
     the claim is not a citation. When the page label cannot be read as a
     page number (e.g. "F-12" or "Note 11"), the page-level check is
     recorded as UNVERIFIED rather than silently passed.
"""
from dataclasses import dataclass
import re

from app.ingest.filings.documents import SourceDocument, normalize_whitespace

# Long enough that a match is evidence rather than coincidence, short enough
# that a one-line disclosure still fits.
MIN_EXCERPT_CHARS = 24

# A page LABEL, not "the first integer anywhere in the string" (fix round 1,
# M4). "Note 11" is a note reference and reading it as page 11 mislabels the
# citation -- it fails closed, but it fails closed for the wrong reason and
# tells the reviewer a page number nobody wrote. Anything this does not match
# takes the UNVERIFIED path instead.
_PAGE_NUMBER = re.compile(r"^\s*(?:p|p\.|pg|pg\.|page)?\s*(\d+)\s*$",
                          re.IGNORECASE)


@dataclass(frozen=True)
class VerbatimResult:
    ok: bool
    reason: str | None = None
    page_number: int | None = None
    page_verified: bool = False


def contains_verbatim(document_text: str, excerpt: str) -> bool:
    """Literal containment, whitespace-normalised on both sides."""
    needle = normalize_whitespace(excerpt)
    if not needle:
        return False
    return needle in normalize_whitespace(document_text)


def page_number_from(source_page: str) -> int | None:
    """The page index a label denotes, or None when the label is not a page
    reference at all ("Note 11", "F-12", "11.2")."""
    match = _PAGE_NUMBER.match(str(source_page or ""))
    return int(match.group(1)) if match else None


def check_excerpt(document: SourceDocument, *, excerpt: str | None,
                  source_page: str | None) -> VerbatimResult:
    text = normalize_whitespace(excerpt or "")
    if not text:
        return VerbatimResult(False, "NO_EXCERPT")
    if len(text) < MIN_EXCERPT_CHARS:
        return VerbatimResult(False, "EXCERPT_TOO_SHORT")
    if not str(source_page or "").strip():
        return VerbatimResult(False, "NO_SOURCE_PAGE")
    if not contains_verbatim(document.text, text):
        return VerbatimResult(False, "EXCERPT_NOT_IN_DOCUMENT")

    page_number = page_number_from(source_page)
    if page_number is None:
        # A non-numeric label ("F-12", "Note 11"). The claim IS in the
        # document; we simply cannot check the label against a page index.
        return VerbatimResult(True, None, None, page_verified=False)

    page_text = document.page_text(page_number)
    if page_text is None or text not in page_text:
        return VerbatimResult(False, "EXCERPT_NOT_ON_CITED_PAGE", page_number)
    return VerbatimResult(True, None, page_number, page_verified=True)
