"""TASK 3.4 -- the mechanism-edge review queue.

Same shape as Phase 1's exposure review (`app/ledger/review.py`), because it
is the same discipline applied to a different artefact: a machine PROPOSES,
a person DECIDES, and the decision is recorded with a name on it.

WHAT IS IN THE QUEUE. Edges whose `derivation` is IO_TABLE or EMPIRICAL and
which nobody has reviewed. Those are the two derivations that produce
hypotheses in bulk -- an input-output table proposes thousands of
industry-to-industry requirements, an event study proposes every industry
that moved -- and neither may be walked by discovery until reviewed
(addendum A2.4, A3.2). AUTHORED edges are not in the queue: they were
written by a person in the first place.

WHAT REJECTION MEANS. A rejected edge is RETAINED with its reason and is
never traversed again (invariant 12). Deleting it would throw away the one
record that stops the same coefficient being re-proposed and re-considered
every time the bootstrap runs.

Ranked by `io_total_coeff` descending: the biggest transmission channels are
worth a reviewer's time first.
"""
from datetime import datetime, timezone

from sqlalchemy import text

REVIEWABLE_DERIVATIONS = ("IO_TABLE", "EMPIRICAL")


class EdgeReviewError(ValueError):
    """A review action that would leave the record incomplete."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def pending_edges(session, limit: int = 200) -> list[dict]:
    return [dict(row) for row in session.execute(text(
        "SELECT * FROM mechanism_edge "
        "WHERE derivation IN ('IO_TABLE', 'EMPIRICAL') "
        "  AND reviewed_by IS NULL "
        "  AND review_status = 'PENDING' "
        "ORDER BY COALESCE(io_total_coeff, 0) DESC, edge_id ASC "
        "LIMIT :limit"), {"limit": int(limit)}).mappings().all()]


def rejected_edges(session, limit: int = 200) -> list[dict]:
    return [dict(row) for row in session.execute(text(
        "SELECT * FROM mechanism_edge WHERE review_status = 'REJECTED' "
        "ORDER BY reviewed_at DESC, edge_id ASC LIMIT :limit"),
        {"limit": int(limit)}).mappings().all()]


def get_edge(session, edge_id: str) -> dict | None:
    row = session.execute(text(
        "SELECT * FROM mechanism_edge WHERE edge_id = :edge_id"),
        {"edge_id": edge_id}).mappings().first()
    return dict(row) if row else None


def approve_edge(session, edge_id: str, *, reviewed_by: str,
                 note: str | None = None) -> dict:
    """Approve one edge. After this it is walkable by discovery, and the
    person who made that true is on the row."""
    reviewer = (reviewed_by or "").strip()
    if not reviewer:
        raise EdgeReviewError(
            "an approval needs a reviewer: an IO_TABLE or EMPIRICAL edge is a "
            "hypothesis until a named human says what the mechanism is")
    edge = get_edge(session, edge_id)
    if edge is None:
        raise EdgeReviewError(f"no such edge: {edge_id}")
    if str(edge["review_status"]) != "PENDING":
        raise EdgeReviewError(
            f"{edge_id} is already {edge['review_status']}; a decision is not "
            "re-taken silently")

    session.execute(text(
        "UPDATE mechanism_edge SET reviewed_by = :reviewed_by, "
        "reviewed_at = :reviewed_at, review_status = 'APPROVED', "
        "review_note = :note WHERE edge_id = :edge_id"), {
            "reviewed_by": reviewer, "reviewed_at": _now(),
            "note": note, "edge_id": edge_id})
    return get_edge(session, edge_id)


def reject_edge(session, edge_id: str, *, reviewed_by: str, reason: str) -> dict:
    """Reject one edge. It is kept, with the reason, and can never be walked
    (invariant 12)."""
    reviewer = (reviewed_by or "").strip()
    if not reviewer:
        raise EdgeReviewError("a rejection needs a reviewer")
    if not (reason or "").strip():
        raise EdgeReviewError(
            "a rejection needs a reason: 'no' with no reason is not reviewable "
            "and cannot stop the same coefficient being re-proposed")
    edge = get_edge(session, edge_id)
    if edge is None:
        raise EdgeReviewError(f"no such edge: {edge_id}")

    session.execute(text(
        "UPDATE mechanism_edge SET review_status = 'REJECTED', "
        "review_note = :reason, reviewed_by = :reviewed_by, "
        "reviewed_at = :reviewed_at WHERE edge_id = :edge_id"), {
            "reason": reason.strip(), "reviewed_by": reviewer,
            "reviewed_at": _now(), "edge_id": edge_id})
    return get_edge(session, edge_id)


def edge_queue_stats(session) -> dict:
    row = session.execute(text(
        "SELECT "
        " sum(CASE WHEN review_status = 'PENDING' AND reviewed_by IS NULL "
        "          AND derivation IN ('IO_TABLE','EMPIRICAL') THEN 1 ELSE 0 END) "
        "   AS pending, "
        " sum(CASE WHEN review_status = 'APPROVED' THEN 1 ELSE 0 END) AS approved, "
        " sum(CASE WHEN review_status = 'REJECTED' THEN 1 ELSE 0 END) AS rejected, "
        " sum(CASE WHEN derivation = 'AUTHORED' THEN 1 ELSE 0 END) AS authored, "
        " count(*) AS total "
        "FROM mechanism_edge")).mappings().first()
    return {key: int(value or 0) for key, value in dict(row).items()}


def open_coverage_gaps(session, limit: int = 200) -> list[dict]:
    """TASK 3.5's queue, surfaced in the same console.

    A row here is an industry that MOVED and that the graph cannot explain.
    It is a work item for whoever authors mechanisms -- never something that
    publishes, because it has no mechanism by definition."""
    return [dict(row) for row in session.execute(text(
        "SELECT * FROM coverage_gap WHERE status = 'OPEN' "
        "ORDER BY priority DESC, industry ASC LIMIT :limit"),
        {"limit": int(limit)}).mappings().all()]
