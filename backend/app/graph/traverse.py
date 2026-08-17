"""TASK 3.3 (the graph half) -- walking `mechanism_edge` from a shock
variable.

A breadth-first walk, so the FIRST time a node is reached is by its shortest
path and `graph_distance` is the shortest hop count -- which matters, because
the distance chooses the exposure threshold a candidate must clear.

ONE RULE THE WALK ENFORCES, and it is the difference between a causal graph
and a correlation dump:

    **An edge is walkable if and only if a named human approved it** --
    `review_status = 'APPROVED'` AND `reviewed_by IS NOT NULL`. Every
    derivation, no exceptions. A REJECTED edge is never walked again and is
    never deleted either (invariant 12) -- the reviewer's "no" is part of the
    record.

WHY `derivation` IS NOT READ HERE (defect D10, `docs/v5/defects/
DEFECTS-002-mechanism-edge-review-authority.md`). This walk used to exempt
`AUTHORED` rows: it gated `derivation IN ('IO_TABLE','EMPIRICAL')` on
`reviewed_by` and let everything else through. That made `derivation` --
a **self-declared provenance string written by whoever inserts the row** --
the authorisation boundary, so anything that could write the characters
`AUTHORED` could authorise its own edge. It was not hypothetical: this repo's
own fixture seeder defaulted to `derivation="AUTHORED"`, so "skip review" was
what you got by not thinking about it.

An AUTHORED row is not harder to write under the new rule. A person who
authors an edge sets `review_status='APPROVED'` and `reviewed_by='human:...'`
in the same INSERT -- one extra field, at the moment they are already typing
the row, converting a self-declared *category* into a recorded *signature*.
`edge_review.approve_edge` already writes exactly that pair, so the approval
path already produces the state this walk requires.

`derivation` survives as PROVENANCE ONLY: it says what kind of thing produced
the row (`IO_TABLE`, `EMPIRICAL`, `AUTHORED`, `MODEL_PROPOSED`) and is carried
onto `GraphEdge` for readers. It is an input to no decision, here or anywhere.

THE RULE IS IN THE SQL, not only in `usable()`. `_SELECT` filters on the same
two columns, so a caller that queries the table directly, or that forgets to
call `usable()`, cannot walk an unapproved edge by accident. `usable()` is
kept as the readable statement of the rule and as the second half of the pin
in `tests/phase3/test_discovery_sources.py`.

`distance` on the row is the AUTHOR'S hop length for that edge and is carried
through untouched; `graph_distance` on the result is a property of the PATH
and is computed here. They are two different numbers and are never merged.
"""
from collections import deque
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text

# The one state a row must be in to be walked. Named so the SQL in `_SELECT`
# and the predicate in `usable()` cannot drift apart silently.
APPROVED = "APPROVED"
REJECTED = "REJECTED"


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
  AND review_status = 'APPROVED'
  AND reviewed_by IS NOT NULL
  AND (effective_from IS NULL OR effective_from <= :as_of)
  AND (effective_to IS NULL OR effective_to >= :as_of)
ORDER BY edge_id ASC
"""


def usable(row) -> bool:
    """Whether this edge may be used in DISCOVERY.

    A database CHECK cannot express "used in discovery" -- the constraint is
    about a query, not a row -- so the rule lives in `_SELECT` above and is
    restated here, and `tests/phase3/test_discovery_sources.py` pins both
    halves.

    ONE RULE, EVERY DERIVATION: a row is walkable iff a named human approved
    it. `derivation` is NOT READ. It is self-declared provenance and cannot be
    an authorisation boundary -- see this module's header and defect D10.

    `REJECTED` is checked first and explicitly. It is already excluded by the
    `APPROVED` test, but a rejection is a decision a person took and this
    function says so rather than letting it fall out of an equality check.
    """
    if str(row["review_status"]) == REJECTED:
        return False
    return str(row["review_status"]) == APPROVED and bool(row["reviewed_by"])


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
