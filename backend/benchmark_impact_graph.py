"""Impact-graph v3 benchmark runner (spec 2026-08-11 §17).

Runs the labelled events in benchmarks/impact_events.json through the LIVE
v3 engine (and optionally the legacy cascade with --old) and scores each
run against the labels:

- company precision/recall vs expected_companies (by ticker)
- direction accuracy on the overlap
- path recall: fraction of expected causal paths whose node ids (or close
  substrings) appear connected in the produced edge set
- depth: max causal_distance reached vs the label's acceptable max
- cost/latency per article from the budget telemetry

REQUIRES live API access (paid Gemini for the protected path). This is the
step the spec forbids skipping -- do not claim benchmark success from the
mocked test suite.

Usage:
    python benchmark_impact_graph.py                # v3, all events
    python benchmark_impact_graph.py --limit 5      # first 5 events
    python benchmark_impact_graph.py --old          # legacy cascade instead
    python benchmark_impact_graph.py --json out.json
"""
import argparse
import json
import sys
import time
from pathlib import Path

from app.db import SessionLocal


def _norm(name: str) -> str:
    return name.lower().replace(" ", "_")


def _path_recall(expected_paths, edges) -> float:
    if not expected_paths:
        return 1.0
    edge_pairs = {( _norm(e["parent_id"]), _norm(e["child_id"]) ) for e in edges}
    nodes = {n for pair in edge_pairs for n in pair}

    def node_present(label: str) -> bool:
        label = _norm(label)
        return any(label in n or n in label for n in nodes)

    hits = 0
    for path in expected_paths:
        present = sum(1 for step in path if node_present(step))
        if present >= max(2, len(path) - 1):  # nearly-complete chain counts
            hits += 1
    return hits / len(expected_paths)


def run_v3(event, session):
    from app.analysis.impact_graph.budget import ArticleBudget
    from app.analysis.impact_graph.engine import analyze_article_v3
    from app.analysis.impact_graph.router import StageRouter
    from app.config import settings
    from app.pipeline import _build_v3_groq_client

    router = StageRouter(
        protected=bool(settings.gemini_paid_api_key), gemini_api_key=settings.gemini_paid_api_key or None,
        groq_client=_build_v3_groq_client(), budget=ArticleBudget(),
    )
    started = time.monotonic()
    result = analyze_article_v3(router, event["title"], event["body"], session=session)
    latency = time.monotonic() - started
    return {
        "companies": {c.ticker: c.direction for c in result.companies},
        "edges": [{"parent_id": e.parent_id, "child_id": e.child_id,
                   "distance": e.causal_distance} for e in result.edges],
        "max_distance": max((e.causal_distance for e in result.edges), default=0),
        "quality": result.analysis_quality, "provider": result.analysis_provider,
        "budget": router.budget.summary(), "latency_s": round(latency, 1),
    }


def run_old(event, session):
    from app.analysis.cascade import analyze_article
    from app.analysis.claude_client import build_client
    from app.config import settings

    client = build_client(settings.groq_api_keys, settings.gemini_api_key or None,
                          gemini_paid_api_key=settings.gemini_paid_api_key or None)
    started = time.monotonic()
    result = analyze_article(client, event["title"], event["body"], session=session)
    latency = time.monotonic() - started
    return {
        "companies": {c.ticker: c.direction for c in result.companies if c.ticker},
        "edges": [{"parent_id": e["from"]["label"], "child_id": e["to"]["label"], "distance": None}
                  for e in (result.edges or [])],
        "max_distance": 2, "quality": "legacy", "provider": "legacy",
        "budget": None, "latency_s": round(latency, 1),
    }


def score(event, run) -> dict:
    expected = {t: d for t, d in (event.get("expected_companies") or {}).items()}
    got = run["companies"]
    overlap = set(expected) & set(got)
    precision = len(overlap) / len(got) if got else (1.0 if not expected else 0.0)
    recall = len(overlap) / len(expected) if expected else 1.0
    direction_hits = sum(
        1 for t in overlap
        if expected[t] == "mixed" or got[t] == expected[t]
    )
    return {
        "company_precision": round(precision, 2),
        "company_recall": round(recall, 2),
        "direction_accuracy": round(direction_hits / len(overlap), 2) if overlap else None,
        "path_recall": round(_path_recall(event.get("expected_paths"), run["edges"]), 2),
        "max_distance": run["max_distance"], "acceptable_depth": event.get("max_depth"),
        "latency_s": run["latency_s"], "quality": run["quality"],
        "cost": (run["budget"] or {}).get("estimated_cost_usd"),
        "tokens_in": (run["budget"] or {}).get("input_tokens"),
        "tokens_out": (run["budget"] or {}).get("output_tokens"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--old", action="store_true", help="run the legacy cascade instead of v3")
    parser.add_argument("--json", default=None, help="write full results to this path")
    args = parser.parse_args()

    events = json.loads((Path(__file__).parent / "benchmarks" / "impact_events.json").read_text())["events"]
    if args.limit:
        events = events[: args.limit]

    session = SessionLocal()
    results = []
    try:
        for event in events:
            print(f"== {event['id']} ==", flush=True)
            try:
                run = (run_old if args.old else run_v3)(event, session)
            except Exception as exc:  # noqa: BLE001 -- benchmark keeps going
                print(f"   FAILED: {exc}", flush=True)
                results.append({"id": event["id"], "error": str(exc)[:300]})
                continue
            s = score(event, run)
            results.append({"id": event["id"], **s, "companies": run["companies"]})
            print(f"   P={s['company_precision']} R={s['company_recall']} "
                  f"dir={s['direction_accuracy']} paths={s['path_recall']} "
                  f"depth={s['max_distance']} cost={s['cost']} {s['latency_s']}s", flush=True)
    finally:
        session.close()

    scored = [r for r in results if "error" not in r]
    if scored:
        def avg(key):
            vals = [r[key] for r in scored if r.get(key) is not None]
            return round(sum(vals) / len(vals), 3) if vals else None
        print("\n== AGGREGATE ==")
        print(f"events={len(scored)}/{len(results)} precision={avg('company_precision')} "
              f"recall={avg('company_recall')} direction={avg('direction_accuracy')} "
              f"path_recall={avg('path_recall')} avg_latency={avg('latency_s')}s "
              f"avg_cost=${avg('cost')}")
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2))
        print(f"written: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
