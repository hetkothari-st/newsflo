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
from datetime import date
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
