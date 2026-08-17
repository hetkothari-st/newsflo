"""§G.5 MECHANISM-FAMILY CLOSURE CHECK — run as a script, not yet a test.

READ ONLY. Opens backend/newsflo.db with mode=ro and reads three config
files. Writes nothing.

The four closure assertions a mechanism family must satisfy. Each is a
different layer of the gap §G names, and each individually passes today for
some rows while the combination is broken:

  A1  every modelled shock variable is the from_node of >=1 mechanism_edge
      -> a variable with no edge is silently reported `unmodelled` and the
         event produces no MECHANISM candidates at all.
  A2  every mechanism_edge's from_node IS a modelled shock variable
      -> the reverse. An edge hanging off an unmodelled node is a row that
         looks live and is unreachable. authored_edges.blockers() refuses
         this; a direct INSERT does not.
  A3  every valid_exposure_tag leaf is the exposure_tag of >=1 edge
      -> a tag no mechanism reaches can hold ledger rows that discovery can
         never surface.
  A4  every edge's mechanism has a section_taxonomy label AFTER
      normalize_node_id
      -> an unlabelled mechanism renders "UNCLASSIFIED MECHANISM (<uuid>)"
         in a user-facing section header AND fragments into a singleton
         section, because the id is part of the section key. This is D6.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "backend"))

from app.analysis.impact_graph.normalize import normalize_node_id  # noqa: E402
from app.discovery.config import load_discovery_config             # noqa: E402
from app.output.section_config import load_section_taxonomy        # noqa: E402

DB = REPO / "backend" / "newsflo.db"


def main() -> int:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    q = con.execute

    modelled = tuple(load_discovery_config().modelled_shock_variables)
    taxonomy = load_section_taxonomy()
    labels = set(taxonomy.labels)

    edges = [dict(r) for r in q(
        "SELECT edge_id, from_node, to_node, exposure_tag, derivation, "
        "review_status, reviewed_by FROM mechanism_edge ORDER BY edge_id")]
    tags = [r[0] for r in q(
        "SELECT exposure_tag FROM valid_exposure_tag ORDER BY 1")]

    print(f"live config : {len(modelled)} modelled shock variables, "
          f"{len(tags)} valid exposure tags, {len(labels)} section labels")
    print(f"live db     : {len(edges)} mechanism_edge rows "
          f"({sum(1 for e in edges if e['review_status'] == 'REJECTED')} rejected, "
          f"{sum(1 for e in edges if not e['reviewed_by'])} unreviewed)")

    from_nodes = {e["from_node"] for e in edges}
    edge_tags = {e["exposure_tag"] for e in edges if e["exposure_tag"]}
    failures = 0

    # --- A1 -----------------------------------------------------------------
    a1 = [v for v in modelled if v not in from_nodes]
    print(f"\n[A1] modelled shock variables with NO mechanism_edge: "
          f"{len(a1)} / {len(modelled)}")
    for v in a1:
        print(f"       ORPHAN VARIABLE  {v}")
    failures += len(a1)

    # --- A2 -----------------------------------------------------------------
    a2 = sorted({e["from_node"] for e in edges
                 if e["from_node"] not in set(modelled)})
    print(f"\n[A2] mechanism_edge from_nodes that are NOT modelled variables: "
          f"{len(a2)}")
    for v in a2:
        owners = [e["edge_id"] for e in edges if e["from_node"] == v]
        print(f"       UNREACHABLE FROM_NODE  {v}   edges={owners}")
    failures += len(a2)

    # --- A3 -----------------------------------------------------------------
    a3 = [t for t in tags if t not in edge_tags]
    print(f"\n[A3] valid exposure tags NO mechanism edge reaches: "
          f"{len(a3)} / {len(tags)}")
    for t in a3:
        print(f"       ORPHAN TAG  {t}")
    failures += len(a3)

    # --- A4 -----------------------------------------------------------------
    a4 = []
    for e in edges:
        persisted = normalize_node_id(str(e["edge_id"]))
        if persisted not in labels and str(e["edge_id"]) not in labels:
            a4.append((e["edge_id"], persisted))
    print(f"\n[A4] mechanism edges with NO section label (post-normalize): "
          f"{len(a4)} / {len(edges)}")
    for edge_id, persisted in a4:
        print(f"       UNLABELLED  {edge_id}")
        print(f"                   would render: "
              f"{taxonomy.mechanism_label(persisted)}")
    failures += len(a4)

    # --- the registry dialect check, for reference --------------------------
    # Every knowledge.MECHANISMS key must have a label AFTER normalize. This
    # is the V4 half and it is already pinned by tests/phase6; reported here
    # so the two vocabularies' coverage is visible side by side.
    try:
        from app.analysis.impact_graph.knowledge import MECHANISMS
        missing = sorted(k for k in MECHANISMS
                         if normalize_node_id(k) not in labels)
        print(f"\n[ref] V4 knowledge.MECHANISMS without a label post-normalize: "
              f"{len(missing)} / {len(MECHANISMS)}")
        for k in missing:
            print(f"       {k} -> {normalize_node_id(k)}")
    except Exception as exc:
        print(f"\n[ref] could not read knowledge.MECHANISMS: {exc!r}")

    print(f"\n{'=' * 70}\nTOTAL CLOSURE FAILURES: {failures}\n{'=' * 70}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
