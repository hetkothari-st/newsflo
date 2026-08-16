"""Candidate `mechanism_edge` rows from pruned input-output coefficients.

Every row this produces has `derivation='IO_TABLE'` and `reviewed_by=None`,
which means the graph walk will not touch it (`app/graph/traverse.py`). It is
a PROPOSAL sitting in a queue, and it becomes an edge when a person says what
the mechanism is and signs for it.

WHAT AN IO TABLE CAN AND CANNOT PROPOSE (A2.4). It models cost structure, so
it proposes INPUT_COST edges (B buys from A: A's price is B's cost) and
DEMAND edges (A sells to B: B's volume is A's demand). It proposes NOTHING
about revenue realization, FX, interest rates or regulation, and this module
must not pretend otherwise -- `IO_RELATIONSHIP_TYPES` is the closed set, and
a test pins it. Those ~60-100 edges stay hand-authored forever.
"""
from typing import Iterable, Mapping

# The only relationship types an input-output table can support (A2.4).
IO_RELATIONSHIP_TYPES = ("INPUT_COST", "DEMAND")

# An IO edge is a single industry-to-industry hop. Path length is computed by
# the walk (`GraphEdge.graph_distance`); this is the AUTHORED hop length, and
# for a direct inter-industry requirement it is one hop by construction.
IO_EDGE_DISTANCE = 1


def edge_id_for(source_industry: str, target_industry: str, table_year: int,
                relationship_type: str) -> str:
    """Content-addressed, so re-running the bootstrap over the same published
    table re-derives the same ids instead of duplicating the queue."""
    return (f"io:{table_year}:{relationship_type.lower()}:"
            f"{source_industry}->{target_industry}")


def candidate_edges(rows: Iterable[Mapping], mapping: Mapping, *,
                    table_year: int, source_url: str,
                    relationship_type: str = "INPUT_COST") -> tuple[dict, ...]:
    """Pruned coefficient rows to candidate edges.

    A row whose source or target industry is not in the hand-authored mapping
    produces NO edge. That is the honest outcome: an unmapped IOTT code is a
    code nobody has decided the meaning of, and guessing the nearest listed
    industry is precisely the invention this pipeline exists to avoid.
    """
    if relationship_type not in IO_RELATIONSHIP_TYPES:
        raise ValueError(
            f"{relationship_type!r} cannot be derived from an input-output "
            f"table; the closed set is {IO_RELATIONSHIP_TYPES} (addendum A2.4)")

    out: list[dict] = []
    for row in rows:
        source = str(row["source_industry"])
        target = str(row["target_industry"])
        if source not in mapping or target not in mapping:
            continue
        # The edge runs from the SOURCE industry (whose price moves) to the
        # TARGET industry (which buys it), and carries the TARGET's exposure
        # tag -- the tag names what the target is exposed to.
        out.append({
            "edge_id": edge_id_for(source, target, table_year, relationship_type),
            "from_node": mapping[source].sector_id,
            "to_node": mapping[target].sector_id,
            "exposure_tag": mapping[target].exposure_tag,
            "relationship_type": relationship_type,
            "distance": IO_EDGE_DISTANCE,
            "io_total_coeff": float(row["total_coeff"]),
            "derivation": "IO_TABLE",
            # THE POINT. Unreviewed, and therefore unusable in discovery
            # until a human authors the mechanism (A2.4, A3.2).
            "reviewed_by": None,
            "review_status": "PENDING",
            "confidence": float(row["total_coeff"]),
            "source_url": source_url,
            "table_year": int(table_year),
        })
    return tuple(out)
