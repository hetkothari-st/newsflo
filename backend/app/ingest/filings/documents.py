"""The text layer: a filing as pages of text, with its provenance attached.

Everything downstream (the verbatim gate, the LLM extractor, the
deterministic parsers) reads a `SourceDocument`, never a file path and never
a PDF. That is what lets the same pipeline run over a PDF, an XBRL-adjacent
text rendition, or a plain-text fixture -- and what keeps the verbatim check
honest: it compares against exactly the text the extractor was shown.

pypdf is the only PDF reader in this repo (pdfplumber is not installed and
the controller adaptation forbids new dependencies). Where pypdf's text
extraction fails on an unusual layout, that is a documented limitation of
the acquisition path, not a licence to accept an unverifiable excerpt --
`verbatim.py` still refuses anything it cannot find in the text it has.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

import hashlib
import io
import re

_WHITESPACE = re.compile(r"\s+")


def normalize_whitespace(value: str) -> str:
    """The ONE normalisation the verbatim check permits: runs of whitespace
    collapse to a single space, and the ends are stripped. Nothing else --
    no case folding, no punctuation stripping, no unicode folding. Every
    additional normalisation widens what counts as "the document said this"."""
    return _WHITESPACE.sub(" ", value or "").strip()


@dataclass(frozen=True)
class SourceDocument:
    url: str
    retrieved_at: datetime
    media_type: str
    sha256: str
    pages: tuple[str, ...]

    @property
    def text(self) -> str:
        return normalize_whitespace("\n".join(self.pages))

    def page_text(self, page_number: int) -> str | None:
        """1-based, like a human citing a page."""
        if page_number < 1 or page_number > len(self.pages):
            return None
        return normalize_whitespace(self.pages[page_number - 1])


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def document_from_pages(pages: Sequence[str], *, url: str, retrieved_at: datetime,
                        media_type: str = "text/plain") -> SourceDocument:
    cleaned = tuple(str(page) for page in pages)
    return SourceDocument(
        url=url, retrieved_at=retrieved_at, media_type=media_type,
        sha256=_sha256("\n\f\n".join(cleaned).encode("utf-8")), pages=cleaned)


def document_from_pdf(content: bytes, *, url: str,
                      retrieved_at: datetime) -> SourceDocument:
    """One page of text per PDF page, with the ORIGINAL bytes hashed -- the
    hash identifies the artefact, not our rendition of it."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    pages = tuple((page.extract_text() or "") for page in reader.pages)
    return SourceDocument(url=url, retrieved_at=retrieved_at,
                          media_type="application/pdf", sha256=_sha256(content),
                          pages=pages)


def document_from_bytes(content: bytes, *, url: str, retrieved_at: datetime,
                        media_type: str) -> SourceDocument:
    if media_type == "application/pdf":
        return document_from_pdf(content, url=url, retrieved_at=retrieved_at)
    text = content.decode("utf-8", errors="replace")
    # A form feed is the page break in a text rendition of a filing.
    return SourceDocument(url=url, retrieved_at=retrieved_at,
                          media_type=media_type, sha256=_sha256(content),
                          pages=tuple(text.split("\f")))
