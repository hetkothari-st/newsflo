"""Snapshot layout for rating-announcement discovery + rationale document
fetching (Task 3). Mirrors app.companies.universe.snapshot's split:
fetchers.py writes here; later stages (extract.py, loader.py) read only
from here.

Pure path/filesystem logic -- no network, no DB.

Layout::

    <root>/index/<iso-date>.json          -- one combined announcements page per fetch day
    <root>/docs/<scrip_code>/<sha16>.pdf  -- the fetched rationale document
    <root>/docs/<scrip_code>/<sha16>.url  -- sidecar: the source URL (provenance + resume)
    <root>/docs/<scrip_code>/<sha16>.meta.json -- sidecar: {scrip_code, company_name, agency, news_date}
    <root>/docs/<scrip_code>/<sha16>.done -- written once extract.py has processed the pdf
"""
import hashlib
from datetime import date, datetime
from pathlib import Path

DEFAULT_ROOT = "data/ratings"
INDEX_DIRNAME = "index"
DOCS_DIRNAME = "docs"


def index_path(root: str, day: date) -> Path:
    return Path(root) / INDEX_DIRNAME / f"{day.isoformat()}.json"


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def doc_path(root: str, scrip_code: str, url: str) -> Path:
    return Path(root) / DOCS_DIRNAME / str(scrip_code) / f"{_url_hash(url)}.pdf"


def url_sidecar_path(pdf_path: Path) -> Path:
    return Path(pdf_path).with_suffix(".url")


def meta_sidecar_path(pdf_path: Path) -> Path:
    pdf_path = Path(pdf_path)
    return pdf_path.with_name(pdf_path.stem + ".meta.json")


def done_marker_path(pdf_path: Path) -> Path:
    return Path(pdf_path).with_suffix(".done")


def fetched_doc_urls(root: str) -> set[str]:
    """Source URLs already fetched, anywhere under ``<root>/docs`` -- read
    from the ``.url`` sidecar written next to each pdf. This is the resume
    set for fetch_documents: a rerun skips any target whose URL already
    has a sidecar, so a rate-limit or crash partway through only costs the
    remainder."""
    base = Path(root) / DOCS_DIRNAME
    if not base.is_dir():
        return set()
    urls = set()
    for sidecar in base.glob("*/*.url"):
        try:
            urls.add(sidecar.read_text(encoding="utf-8").strip())
        except OSError:
            continue
    return urls


def pending_docs(root: str) -> list[Path]:
    """PDFs already fetched but not yet marked extracted (no ``.done``
    sidecar). Task 7's extraction drain consumes this list."""
    base = Path(root) / DOCS_DIRNAME
    if not base.is_dir():
        return []
    return [p for p in base.glob("*/*.pdf") if not done_marker_path(p).exists()]


def mark_extracted(pdf_path: Path) -> None:
    done_marker_path(pdf_path).write_text("", encoding="utf-8")


def parse_news_date(value) -> date | None:
    """meta.json's news_date is BSE's raw NEWS_DT string (an ISO-ish
    datetime, e.g. "2026-08-04T17:47:01.793"). Best-effort parse to a date
    for loader.apply_extraction's recency gate -- returns None on a
    missing or unparsable value.

    Callers MUST treat None as a genuine failure (count "errored", skip the
    doc, leave it pending for a retry) rather than defaulting to
    date.today(): a stale document whose news_date is missing or garbage
    would otherwise be stamped with today's date and permanently clobber
    genuinely newer stored links (reproduced: a stale 2023 doc stamped
    today replaced 2026 links). Previously duplicated in app.scheduler and
    backfill_supply_links.py as ``_parse_news_date``; both now import this
    one copy."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None
