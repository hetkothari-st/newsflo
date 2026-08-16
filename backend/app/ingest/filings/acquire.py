"""STAGE A -- acquisition. "Never discard the source document."

Two deliberately separate functions:

  `fetch_artefact`  needs an INJECTED fetcher. This module opens no socket
                    and imports no HTTP client: a pipeline that can fetch by
                    default is a pipeline that fetches during a test run.
  `store_artefact`  writes the bytes to disk under a content-addressed path
                    and records the row (URL, retrieval timestamp, sha256,
                    byte size). Idempotent on (sha256, url), so re-running an
                    acquisition never duplicates or overwrites.

The stored artefact is what every later verbatim check is ultimately
answerable to. It is written once and never mutated.
"""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import hashlib
import uuid

from sqlalchemy import text

from app.ledger.db import commit_if_owned


class AcquisitionError(RuntimeError):
    """Acquisition could not proceed. Never a silent no-op."""


@dataclass(frozen=True)
class StoredArtefact:
    artefact_id: str
    storage_path: str
    content_sha256: str
    byte_size: int
    created: bool


def fetch_artefact(url: str, *, fetcher: Callable[[str], bytes] | None) -> bytes:
    """Fetch bytes using an injected callable.

    There is no default fetcher on purpose. Passing one is a deliberate act
    by an operator running an acquisition; nothing in the test suite or the
    scheduler can trigger a network call by omission."""
    if fetcher is None:
        raise AcquisitionError(
            f"no fetcher supplied for {url}. Acquisition never opens a "
            "connection by default -- pass an explicit fetcher.")
    content = fetcher(url)
    if not content:
        raise AcquisitionError(f"fetcher returned no content for {url}")
    return content


def store_artefact(session, *, company_id: int | None, url: str, content: bytes,
                   media_type: str, source_type: str, retrieved_at: datetime,
                   artefacts_dir: Path | str,
                   fiscal_period: str | None = None) -> StoredArtefact:
    """Persist the raw document and its provenance row."""
    digest = hashlib.sha256(content).hexdigest()
    existing = session.execute(text(
        "SELECT artefact_id, storage_path, byte_size FROM filing_artefact "
        "WHERE content_sha256 = :sha AND source_url = :url"),
        {"sha": digest, "url": url}).first()
    if existing is not None:
        return StoredArtefact(existing[0], existing[1], digest,
                              int(existing[2] or len(content)), created=False)

    root = Path(artefacts_dir)
    # Content-addressed: the same bytes always land in the same place, and a
    # write can never clobber a different document.
    relative = Path(digest[:2]) / f"{digest}.bin"
    destination = root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        destination.write_bytes(content)

    artefact_id = str(uuid.uuid4())
    session.execute(text(
        "INSERT INTO filing_artefact (artefact_id, company_id, source_url, "
        "source_type, media_type, content_sha256, byte_size, storage_path, "
        "fiscal_period, retrieved_at) VALUES (:artefact_id, :company_id, :url, "
        ":source_type, :media_type, :sha, :size, :path, :fiscal_period, "
        ":retrieved_at)"), {
            "artefact_id": artefact_id, "company_id": company_id, "url": url,
            "source_type": source_type, "media_type": media_type, "sha": digest,
            "size": len(content), "path": str(relative).replace("\\", "/"),
            "fiscal_period": fiscal_period, "retrieved_at": retrieved_at})
    commit_if_owned(session)
    return StoredArtefact(artefact_id, str(relative).replace("\\", "/"), digest,
                          len(content), created=True)


def load_artefact(session, artefact_id: str, *, artefacts_dir: Path | str) -> bytes:
    row = session.execute(text(
        "SELECT storage_path FROM filing_artefact WHERE artefact_id = :id"),
        {"id": artefact_id}).first()
    if row is None:
        raise AcquisitionError(f"no artefact {artefact_id!r}")
    return (Path(artefacts_dir) / row[0]).read_bytes()
