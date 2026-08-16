"""Writing parsed coefficients and candidate edges to the database.

THIS MODULE IS NEVER CALLED IN PRODUCTION TODAY, because there is no
published table in this repo to call it with. It exists so that when the
owner acquires one, loading it is a transcription rather than a design.

It refuses to write anything without `table_year` and `source_url`. That is
the whole guarantee: there is no code path from "a number someone believed"
to `io_coefficient`, only from "a cell in a published table at a URL".
"""
from datetime import datetime, timezone
from typing import Iterable, Mapping

from sqlalchemy import text


class IOLoadError(ValueError):
    """A coefficient or edge was offered without its provenance."""


def _require_provenance(table_year: int, source_url: str) -> None:
    if not source_url:
        raise IOLoadError(
            "io_coefficient rows require a source_url. A coefficient with no "
            "published origin is exactly the fabrication this table exists "
            "to make impossible.")
    if not table_year:
        raise IOLoadError("io_coefficient rows require a table_year")


def load_coefficients(session, rows: Iterable[Mapping], *, table_year: int,
                      source_url: str) -> int:
    """Insert (or replace) coefficient rows for one published table year."""
    _require_provenance(table_year, source_url)
    written = 0
    for row in rows:
        session.execute(text(
            "INSERT OR REPLACE INTO io_coefficient (source_industry, "
            "target_industry, table_year, direct_coeff, total_coeff, "
            "source_url, loaded_at) VALUES (:source_industry, "
            ":target_industry, :table_year, :direct_coeff, :total_coeff, "
            ":source_url, :loaded_at)"), {
                "source_industry": str(row["source_industry"]),
                "target_industry": str(row["target_industry"]),
                "table_year": int(table_year),
                "direct_coeff": float(row["direct_coeff"]),
                "total_coeff": float(row["total_coeff"]),
                "source_url": source_url,
                "loaded_at": datetime.now(timezone.utc).isoformat()})
        written += 1
    return written


def load_candidate_edges(session, edges: Iterable[Mapping]) -> int:
    """Queue candidate edges for review. Idempotent on `edge_id`, which is
    content-addressed, so re-running the bootstrap does not grow the queue.

    An edge already carrying a `reviewed_by` is NOT overwritten: a re-run of
    the bootstrap must never quietly un-review a decision a person made.
    """
    written = 0
    for edge in edges:
        if edge.get("reviewed_by"):
            raise IOLoadError(
                f"{edge['edge_id']}: candidate edges are queued UNREVIEWED. "
                "Approving one is app/ledger/edge_review.approve_edge, which "
                "records who did it.")
        existing = session.execute(text(
            "SELECT reviewed_by, review_status FROM mechanism_edge "
            "WHERE edge_id = :edge_id"), {"edge_id": edge["edge_id"]}).first()
        if existing is not None:
            continue
        session.execute(text(
            "INSERT INTO mechanism_edge (edge_id, from_node, to_node, "
            "exposure_tag, relationship_type, distance, io_total_coeff, "
            "derivation, reviewed_by, review_status, confidence, source_url, "
            "table_year) VALUES (:edge_id, :from_node, :to_node, "
            ":exposure_tag, :relationship_type, :distance, :io_total_coeff, "
            ":derivation, NULL, :review_status, :confidence, :source_url, "
            ":table_year)"), dict(edge))
        written += 1
    return written
