"""TASK 3.3 (the graph half) -- walking `mechanism_edge` from a shock
variable.

A breadth-first walk, so the FIRST time a node is reached is by its shortest
path and `graph_distance` is the shortest hop count -- which matters, because
the distance chooses the exposure threshold a candidate must clear.

TWO RULES THE WALK ENFORCES, both of which are the difference between a
causal graph and a correlation dump:

  * an IO_TABLE or EMPIRICAL edge with no `reviewed_by` is NOT WALKED
    (addendum A2.4 and A3.2). Input-output tables are a hypothesis generator
    published at industry granularity with a multi-year lag; an event study
    is a statistic. Either may propose an edge. Neither may BE one until a
    named human has said what the mechanism is.
  * a REJECTED edge is never walked again, and is never deleted either
    (invariant 12) -- the reviewer's "no" is part of the record.

`distance` on the row is the AUTHOR'S hop length for that edge and is carried
through untouched; `graph_distance` on the result is a property of the PATH
and is computed here. They are two different numbers and are never merged.
"""
from collections import deque
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text

# A hypothesis until a human says otherwise (addendum A2.4, A3.2).
REVIEW_REQUIRED_DERIVATIONS = ("IO_TABLE", "EMPIRICAL")


@dataclass(frozen=True)
class GraphEdge:
    edge_id: str
    from_node: str
    to_node: str
    exposure_tag: str
    relationship_type: str
    derivation: str
    confidence: float
    io_total_coeff: float | None
    # The author's hop length for this edge, as stored.
    authored_distance: int
    # The number of hops from the shock variable to `to_node`, computed by
    # this walk. NEVER the same field as `authored_distance`, and never
    # `directness` -- see invariant 4.
    graph_distance: int


_SELECT = """
SELECT edge_id, from_node, to_node, exposure_tag, relationship_type,
       distance, derivation, reviewed_by, review_status, confidence,
       io_total_coeff, effective_from, effective_to
FROM mechanism_edge
WHERE from_node = :node
  AND review_status <> 'REJECTED'
  AND (effective_from IS NULL OR effective_from <= :as_of)
  AND (effective_to IS NULL OR effective_to >= :as_of)
ORDER BY edge_id ASC
"""


def usable(row) -> bool:
    """Whether this edge may be used in DISCOVERY.

    A database CHECK cannot express "used in discovery" -- the constraint is
    about a query, not a row -- so the rule lives here and in the SQL above,
    and `tests/phase3/test_discovery_sources.py` pins both halves.

    AN `AUTHORED` EDGE IS TRAVERSABLE WHILE ITS `review_status` IS STILL
    `PENDING`, and that is deliberate rather than an oversight. The spec
    gates exactly two derivations -- "CONSTRAINT: derivation IN
    ('IO_TABLE','EMPIRICAL') requires reviewed_by NOT NULL before the edge
    may be used in discovery" (phase file Task 3.4) -- because those two are
    generated in BULK by a machine and are hypotheses by construction. An
    AUTHORED edge was written by a person in the first place, so there is no
    second person for it to be waiting on; `review_status` on it records a
    later re-review, not its birth. Requiring approval for AUTHORED edges too
    would be a stricter rule than the spec's, and adopting one silently is
    how a spec stops describing the system. REJECTED still blocks every
    derivation, including AUTHORED.
    """
    if str(row["review_status"]) == "REJECTED":
        return False
    if str(row["derivation"]) in REVIEW_REQUIRED_DERIVATIONS:
        return bool(row["reviewed_by"])
    return True


def traverse(session, variable: str, *, as_of: date,
             max_depth: int = 3) -> tuple[GraphEdge, ...]:
    """Every usable edge reachable from `variable` within `max_depth` hops.

    Returns edges in discovery order (breadth first, then edge_id), each
    carrying the distance of the path that found it. Terminates on cycles.
    """
    seen_nodes = {variable}
    seen_edges: set[str] = set()
    out: list[GraphEdge] = []
    frontier: deque[tuple[str, int]] = deque([(variable, 0)])

    while frontier:
        node, depth = frontier.popleft()
        if depth >= max_depth:
            continue
        rows = session.execute(text(_SELECT), {
            "node": node, "as_of": as_of.isoformat()}).mappings().all()
        for row in rows:
            if not usable(row) or row["edge_id"] in seen_edges:
                continue
            seen_edges.add(str(row["edge_id"]))
            out.append(GraphEdge(
                edge_id=str(row["edge_id"]),
                from_node=str(row["from_node"]),
                to_node=str(row["to_node"]),
                exposure_tag=str(row["exposure_tag"]),
                relationship_type=str(row["relationship_type"]),
                derivation=str(row["derivation"]),
                confidence=float(row["confidence"]),
                io_total_coeff=(None if row["io_total_coeff"] is None
                                else float(row["io_total_coeff"])),
                authored_distance=int(row["distance"]),
                graph_distance=depth + 1))
            if row["to_node"] not in seen_nodes:
                seen_nodes.add(str(row["to_node"]))
                frontier.append((str(row["to_node"]), depth + 1))
    return tuple(out)


def reachable_tags(edges) -> dict[str, GraphEdge]:
    """The shallowest edge that reaches each exposure tag.

    A tag reachable by two paths takes the SHORTER one: the threshold a
    candidate must clear should reflect the closest route the shock has to
    it, not the most roundabout.
    """
    best: dict[str, GraphEdge] = {}
    for edge in edges:
        current = best.get(edge.exposure_tag)
        if current is None or edge.graph_distance < current.graph_distance:
            best[edge.exposure_tag] = edge
    return best
