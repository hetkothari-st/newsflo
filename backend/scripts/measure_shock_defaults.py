#!/usr/bin/env python
"""Offline audit: how often do the V4 engine's SILENT shock defaults fire?

`app.analysis.impact_graph.engine` parses model shocks with::

    impact_strength=shock.get("impact_strength", 0.5)
    confidence=shock.get("confidence", 0.0)
    materiality=shock.get("materiality", 0.5)

`impact_strength` and `materiality` are NOT in ``SCHEMA_SHOCKS``' required
list, so a response that omits them silently becomes 0.5 -- and a stored 0.5
is thereafter indistinguishable from a deliberate 0.5 claim. `confidence` IS
required, so it is measured here only as a schema-enforcement control.

Because the default fires at RESPONSE-PARSE time, the only honest source is
the RAW stored model response (``llm_stage_cache.result_json``). This script
re-derives field PRESENCE directly from that raw JSON -- it never re-runs the
engine and never calls a model.

THE HONESTY RULE THIS SCRIPT ENFORCES
    An alert whose raw response is NOT recoverable is UNMEASURABLE, not
    "no default fired". Post-parsed stores (``analysis_cache``,
    ``impact_edges``, ``alert_companies``) already have the default baked in:
    a 0.5 there is ambiguous by construction. Unmeasurable alerts are counted
    and reported separately and NEVER enter a percentage denominator.

Safety rails (all enforced at runtime, the script aborts rather than degrade):
  * the DB is opened ``mode=ro`` through a ``file:`` URI, a write is attempted
    and REQUIRED to fail, and the -wal/-shm sidecars are checked before and
    after so a read cannot have journalled;
  * an AST self-scan refuses to run if this file ever grows an import of a
    model provider / HTTP client / the LLM router.

Usage::

    python scripts/measure_shock_defaults.py                  # backend/newsflo.db
    python scripts/measure_shock_defaults.py --db path/to.db --limit 200
    python scripts/measure_shock_defaults.py --out report.md --json out.json
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import pathlib
import sqlite3
import sys

# --- 0. safety: this tool must never be able to call a model --------------

#: Root module names this script may NEVER import. The engine's own router is
#: on the list: importing it is the one plausible way an "offline" audit tool
#: acquires a live provider client by accident.
FORBIDDEN_IMPORT_ROOTS = frozenset({
    "anthropic", "openai", "google", "groq", "cohere", "mistralai", "ollama",
    "httpx", "requests", "aiohttp", "urllib3", "urllib",
})
FORBIDDEN_IMPORT_PREFIXES = (
    "app.analysis.impact_graph.router",
    "app.analysis.claude_client",
    "app.analysis.impact_graph.gemini_json",
)

#: Shock fields the engine reads with a silent numeric default, and the value
#: each one silently becomes. Kept as data so the report can name the number.
DEFAULTED_FIELDS = {"impact_strength": 0.5, "materiality": 0.5, "confidence": 0.0}
#: Schema-required subset -- a fire here means structured output was not
#: enforced, which is a different (worse) bug than the unrequired fields.
SCHEMA_REQUIRED_FIELDS = frozenset({"confidence"})

#: Stages whose raw response carries a top-level `shocks` array.
SHOCK_STAGES = ("initial_shocks", "narrow_graph")


def assert_no_provider_imports(path: pathlib.Path) -> None:
    """AST self-scan: refuse to run if this file imports anything that could
    reach a model or the network."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders: list[str] = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module]
        for name in names:
            root = name.split(".")[0]
            if root in FORBIDDEN_IMPORT_ROOTS or name.startswith(FORBIDDEN_IMPORT_PREFIXES):
                offenders.append(name)
    if offenders:
        sys.exit(f"REFUSING TO RUN: offline audit imports {sorted(set(offenders))}")


# --- 1. safety: strictly read-only DB access ------------------------------

def open_readonly(db_path: pathlib.Path) -> tuple[sqlite3.Connection, dict]:
    """Open `db_path` read-only and PROVE it. Returns (conn, sidecar state).

    Aborts on: missing file, an open that does not honour mode=ro, or a
    connection that accepts a write.
    """
    if not db_path.is_file():
        sys.exit(f"REFUSING TO RUN: no such database file: {db_path}")
    # pathlib gives file:///C:/... -- sqlite wants file:/C:/... on Windows.
    uri = db_path.resolve().as_uri().replace("file:///", "file:/") + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.OperationalError as exc:
        sys.exit(f"REFUSING TO RUN: cannot open read-only ({uri}): {exc}")
    try:
        conn.execute("CREATE TABLE _shock_default_probe (x INTEGER)")
    except sqlite3.OperationalError:
        pass  # expected: "attempt to write a readonly database"
    else:
        conn.close()
        sys.exit("REFUSING TO RUN: connection accepted a write -- not read-only")
    conn.row_factory = sqlite3.Row
    return conn, _sidecar_state(db_path)


def _sidecar_state(db_path: pathlib.Path) -> dict:
    state = {}
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = db_path.with_name(db_path.name + suffix)
        state[suffix] = sidecar.stat().st_mtime_ns if sidecar.exists() else None
    return state


def assert_no_writes(db_path: pathlib.Path, before: dict) -> None:
    after = _sidecar_state(db_path)
    if after != before:
        changed = [k for k in after if after[k] != before[k]]
        sys.exit(f"ABORT: journal sidecars changed during a read-only run: {changed}")


# --- 2. raw-response recovery ---------------------------------------------

def unwrap_envelope(result_json: str) -> dict | None:
    """`llm_stage_cache.result_json` is either the raw provider dict or the
    Task-15 envelope {"__cache_envelope": 1, "quality", "result"}."""
    try:
        stored = json.loads(result_json)
    except (TypeError, ValueError):
        return None
    if not isinstance(stored, dict):
        return None
    if stored.get("__cache_envelope") == 1:
        result = stored.get("result")
        return result if isinstance(result, dict) else None
    return stored


def recover_raw_shocks(conn: sqlite3.Connection) -> dict[int, list[dict]]:
    """article_id -> [{stage, shock}] for every recoverable raw shock.

    Keyed by ARTICLE, because that is what `llm_stage_cache` stores; the
    alert-level attribution in `load_alerts` inherits that limitation.
    """
    if not _table_exists(conn, "llm_stage_cache"):
        return {}
    placeholders = ",".join("?" * len(SHOCK_STAGES))
    rows = conn.execute(
        f"SELECT article_id, stage, result_json FROM llm_stage_cache "  # noqa: S608
        f"WHERE stage IN ({placeholders})", SHOCK_STAGES).fetchall()
    by_article: dict[int, list[dict]] = {}
    for row in rows:
        if row["article_id"] is None:
            continue
        result = unwrap_envelope(row["result_json"])
        if result is None:
            continue
        for shock in result.get("shocks") or []:
            if isinstance(shock, dict):
                by_article.setdefault(row["article_id"], []).append(
                    {"stage": row["stage"], "shock": shock})
    return by_article


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


# --- 3. shock -> node id (mirrors the engine's own construction) ----------

def node_ids_for_shock(shock: dict, stage: str) -> set[str]:
    """The `GraphEdge.child_id` the engine would build from this shock.

    Both call sites read `shock_id or label`, but only `_build_graph`
    (initial_shocks) normalizes: ``.strip().lower().replace(" ", "_")``.
    Both spellings are returned so a join stays robust to which path ran.
    """
    base = str(shock.get("shock_id") or shock.get("label") or "shock")
    normalized = base.strip().lower().replace(" ", "_")
    return {base, normalized} if stage == "initial_shocks" else {base, normalized}


# --- 4. serving predicate --------------------------------------------------

def load_serving_helpers():
    """`is_gated` / `is_displayable_tier` from the repo's own gate module.

    `app.analysis.impact_graph.publication_gate` imports only `app.config` at
    module scope (its docstring pins that: "No DB, no LLM"), so this stays
    inside the zero-network contract. Falls back to a literal reimplementation
    only if the import fails, and says so in the report.
    """
    try:
        # sys.path[0] is scripts/ when run as a file -- `app` lives one up.
        backend_root = str(pathlib.Path(__file__).resolve().parents[1])
        if backend_root not in sys.path:
            sys.path.insert(0, backend_root)
        from app.analysis.impact_graph.publication_gate import (  # noqa: PLC0415
            TIER_PRIMARY, is_displayable_tier,
        )
        return is_displayable_tier, TIER_PRIMARY, "app.analysis.impact_graph.publication_gate"
    except Exception:  # noqa: BLE001 -- an audit tool must still produce numbers
        displayable = {"primary", "secondary_ripple", "macro_context",
                       "secondary", "secondary_deep_dive"}
        return (lambda v: (v or "") in displayable), "primary", "FALLBACK literal tier set"


# --- 5. the study ----------------------------------------------------------

def run(conn: sqlite3.Connection, limit: int) -> dict:
    is_displayable_tier, tier_primary, predicate_source = load_serving_helpers()
    ac_columns = _columns(conn, "alert_companies")
    has_v4_columns = {"display_tier", "gate_state", "causal_parent_id", "materiality"} <= ac_columns

    alerts = conn.execute(
        "SELECT id, article_id FROM alerts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    alert_ids = [row["id"] for row in alerts]
    raw_by_article = recover_raw_shocks(conn)

    measurable, unmeasurable = [], []
    for row in alerts:
        (measurable if raw_by_article.get(row["article_id"]) else unmeasurable).append(dict(row))

    # --- (a)/(b)/bonus: field-presence over raw shocks --------------------
    shocks_seen = 0
    absent = {field: 0 for field in DEFAULTED_FIELDS}
    per_alert_defaults: dict[int, dict] = {}
    for alert in measurable:
        entries = raw_by_article[alert["article_id"]]
        defaulted_nodes: set[str] = set()
        alert_total = 0
        for entry in entries:
            shock, stage = entry["shock"], entry["stage"]
            shocks_seen += 1
            alert_total += 1
            missing = [f for f in DEFAULTED_FIELDS if f not in shock]
            for field in missing:
                absent[field] += 1
            if missing:
                defaulted_nodes |= node_ids_for_shock(shock, stage)
        per_alert_defaults[alert["id"]] = {"nodes": defaulted_nodes, "shocks": alert_total}

    # --- (c): served companies whose chain contains a defaulted shock -----
    served_strict, served_deep, affected_strict, affected_deep = [], [], set(), set()
    join_notes: list[str] = []
    if has_v4_columns:
        for alert in measurable:
            rows = conn.execute(
                "SELECT id, company_id, display_tier, gate_state, causal_parent_type, "
                "causal_parent_id, causal_distance, materiality FROM alert_companies "
                "WHERE alert_id = ?", (alert["id"],)).fetchall()
            if not rows:
                continue
            gated = any(r["gate_state"] is not None or r["display_tier"] is not None for r in rows)
            if gated:
                strict = [r for r in rows if r["display_tier"] == tier_primary]
                deep = [r for r in rows if is_displayable_tier(r["display_tier"])]
            else:
                # Legacy (ungated) alert: compute_ripple_layers' 3-tier path
                # "always renders every company regardless of this flag".
                strict = deep = list(rows)
            served_strict.extend(strict)
            served_deep.extend(deep)

            reachable = reachable_from_nodes(conn, alert["id"], per_alert_defaults[alert["id"]]["nodes"])
            for bucket, target in ((strict, affected_strict), (deep, affected_deep)):
                for r in bucket:
                    if _row_is_affected(r, reachable, per_alert_defaults[alert["id"]]):
                        target.add(r["id"])
    else:
        join_notes.append("alert_companies lacks the v4 causal columns -- no shock->company "
                          "join was possible on this DB.")
    unjoinable = sum(1 for r in served_deep if r["causal_parent_id"] is None)
    if unjoinable:
        join_notes.append(
            f"{unjoinable} of {len(served_deep)} served rows carry a NULL causal_parent_id "
            "(legacy persistence) and can never be joined to a shock -- they are counted as "
            "NOT affected, so the affected rate is a LOWER BOUND.")
    if not any(d["nodes"] for d in per_alert_defaults.values()):
        join_notes.append(
            "No shock defaulted on this DB, so the shock->company join was never exercised "
            "against a positive case here: a 0% affected rate reflects zero defaults, NOT a "
            "join proven to find them.")

    # --- (d): final materiality distribution, both groups -----------------
    def _materialities(rows, ids, inside: bool):
        return [r["materiality"] for r in rows
                if (r["id"] in ids) is inside and r["materiality"] is not None]

    distribution = {}
    for label, rows, ids in (("feed_primary_only", served_strict, affected_strict),
                             ("detail_displayable", served_deep, affected_deep)):
        distribution[label] = {
            "with_defaulted_shock": summarize(_materialities(rows, ids, True)),
            "without_defaulted_shock": summarize(_materialities(rows, ids, False)),
            "null_materiality_rows": sum(1 for r in rows if r["materiality"] is None),
        }

    return {
        "limit": limit,
        "alerts_examined": len(alert_ids),
        "alert_id_range": [min(alert_ids), max(alert_ids)] if alert_ids else None,
        "measurable_alerts": len(measurable),
        "unmeasurable_alerts": len(unmeasurable),
        "measurable_alert_ids": [a["id"] for a in measurable],
        "shocks_examined": shocks_seen,
        "absent_counts": absent,
        "absent_pct": {f: (100.0 * n / shocks_seen if shocks_seen else None)
                       for f, n in absent.items()},
        "served_counts": {"feed_primary_only": len(served_strict),
                          "detail_displayable": len(served_deep)},
        "affected_counts": {"feed_primary_only": len(affected_strict),
                            "detail_displayable": len(affected_deep)},
        "affected_pct": {
            "feed_primary_only": (100.0 * len(affected_strict) / len(served_strict)
                                  if served_strict else None),
            "detail_displayable": (100.0 * len(affected_deep) / len(served_deep)
                                   if served_deep else None),
        },
        "materiality_distribution": distribution,
        "serving_predicate_source": predicate_source,
        "has_v4_columns": has_v4_columns,
        "join_notes": join_notes,
        "raw_shock_stage_rows": {stage: n for stage, n in conn.execute(
            "SELECT stage, COUNT(*) FROM llm_stage_cache GROUP BY stage"
        ).fetchall()} if _table_exists(conn, "llm_stage_cache") else {},
    }


def _row_is_affected(row, reachable: set, alert_defaults: dict) -> bool:
    """A served company counts as affected when a defaulted shock node is an
    ancestor of it. Two admissible signals, both stated in the report:

      DIRECT     the row's own `causal_parent_id` IS a defaulted shock node
                 (distance-1 companies hang straight off the shock);
      TRANSITIVE the row's parent node is reachable from a defaulted shock
                 through this alert's `impact_edges`.
    """
    if not alert_defaults["nodes"]:
        return False
    parent = row["causal_parent_id"]
    if parent is None:
        return False
    return parent in alert_defaults["nodes"] or parent in reachable


def reachable_from_nodes(conn: sqlite3.Connection, alert_id: int, seeds: set[str]) -> set[str]:
    """Transitive closure over this alert's `impact_edges` label graph.

    LIMITATION (stated in the report): `impact_edges` stores human labels
    (`from_label`/`to_label`), not the engine's `node_id`s, so this walk is a
    label-equality approximation of the real graph. Where the two disagree the
    walk UNDER-counts; it can never invent a link that no edge row asserts.
    """
    if not seeds or not _table_exists(conn, "impact_edges"):
        return set()
    edges = conn.execute(
        "SELECT from_label, to_label FROM impact_edges WHERE alert_id = ?", (alert_id,)).fetchall()
    adjacency: dict[str, set[str]] = {}
    for edge in edges:
        for key in {edge["from_label"], str(edge["from_label"]).strip().lower().replace(" ", "_")}:
            adjacency.setdefault(key, set()).add(edge["to_label"])
            adjacency[key].add(str(edge["to_label"]).strip().lower().replace(" ", "_"))
    reachable: set[str] = set()
    frontier = list(seeds)
    while frontier:
        current = frontier.pop()
        for child in adjacency.get(current, ()):
            if child not in reachable:
                reachable.add(child)
                frontier.append(child)
    return reachable


def summarize(values: list[float]) -> dict:
    values = sorted(v for v in values if v is not None)
    if not values:
        return {"n": 0, "min": None, "p25": None, "median": None, "p75": None, "max": None,
                "exactly_0.5": 0, "histogram": {}}

    def _pct(fraction: float) -> float:
        return values[min(len(values) - 1, int(round(fraction * (len(values) - 1))))]

    histogram: dict[str, int] = {}
    for value in values:
        bucket = min(9, int(value * 10))
        histogram[f"{bucket / 10:.1f}-{(bucket + 1) / 10:.1f}"] = histogram.get(
            f"{bucket / 10:.1f}-{(bucket + 1) / 10:.1f}", 0) + 1
    return {
        "n": len(values), "min": values[0], "p25": _pct(0.25), "median": _pct(0.5),
        "p75": _pct(0.75), "max": values[-1],
        "exactly_0.5": sum(1 for v in values if v == 0.5),
        "histogram": dict(sorted(histogram.items())),
    }


# --- 6. reporting ----------------------------------------------------------

def _pct_str(value) -> str:
    return "n/a (no measurable denominator)" if value is None else f"{value:.1f}%"


def render_markdown(stats: dict, db_path: pathlib.Path) -> str:
    lines = [
        "# V4 silent shock-default study",
        "",
        f"- database (read-only): `{db_path}`",
        f"- alerts examined: {stats['alerts_examined']} "
        f"(ORDER BY id DESC LIMIT {stats['limit']}, id range {stats['alert_id_range']})",
        f"- **measurable** alerts (raw response recoverable): {stats['measurable_alerts']}",
        f"- **unmeasurable** alerts (post-parsed only / nothing stored): "
        f"{stats['unmeasurable_alerts']}",
        f"- raw shocks examined: {stats['shocks_examined']}",
        f"- serving predicate source: {stats['serving_predicate_source']}",
        "",
        "## Headline",
        "",
        "| field | schema-required | silent default | absent | of shocks | rate |",
        "|---|---|---|---|---|---|",
    ]
    for field, default in DEFAULTED_FIELDS.items():
        lines.append(
            f"| `{field}` | {'yes' if field in SCHEMA_REQUIRED_FIELDS else '**no**'} | "
            f"{default} | {stats['absent_counts'][field]} | {stats['shocks_examined']} | "
            f"{_pct_str(stats['absent_pct'][field])} |")
    lines += [
        "",
        "## Served companies with >=1 defaulted shock in their chain",
        "",
        "| serving view | served | affected | rate |",
        "|---|---|---|---|",
    ]
    for view in ("feed_primary_only", "detail_displayable"):
        lines.append(f"| {view} | {stats['served_counts'][view]} | "
                     f"{stats['affected_counts'][view]} | {_pct_str(stats['affected_pct'][view])} |")
    lines += ["", "## Final stored materiality distribution", ""]
    for view, groups in stats["materiality_distribution"].items():
        lines += [f"### {view}", "",
                  "| group | n | min | p25 | median | p75 | max | exactly 0.5 |", "|---|---|---|---|---|---|---|---|"]
        for group in ("with_defaulted_shock", "without_defaulted_shock"):
            s = groups[group]
            lines.append(
                f"| {group} | {s['n']} | {s['min']} | {s['p25']} | {s['median']} | "
                f"{s['p75']} | {s['max']} | {s['exactly_0.5']} |")
        lines.append("")
        for group in ("with_defaulted_shock", "without_defaulted_shock"):
            histogram = groups[group]["histogram"]
            lines.append(f"histogram ({group}): "
                         + (", ".join(f"{k}: {v}" for k, v in histogram.items()) or "(empty)"))
        lines += [f"", f"rows with NULL materiality: {groups['null_materiality_rows']}", ""]
    if stats["join_notes"]:
        lines += ["## Join notes", ""] + [f"- {n}" for n in stats["join_notes"]] + [""]
    lines += ["## Raw stage-cache coverage", "",
              f"`llm_stage_cache` rows by stage: {stats['raw_shock_stage_rows'] or '(none)'}", ""]
    return "\n".join(lines)


def main() -> None:
    assert_no_provider_imports(pathlib.Path(__file__).resolve())
    os.environ.setdefault("ENABLE_SCHEDULER", "false")

    default_db = pathlib.Path(__file__).resolve().parents[1] / "newsflo.db"
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=pathlib.Path, default=default_db)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--out", type=pathlib.Path, help="write the markdown report here")
    parser.add_argument("--json", type=pathlib.Path, help="write the raw stats JSON here")
    args = parser.parse_args()

    conn, sidecars = open_readonly(args.db)
    try:
        stats = run(conn, args.limit)
    finally:
        conn.close()
    assert_no_writes(args.db, sidecars)

    report = render_markdown(stats, args.db)
    print(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(stats, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
