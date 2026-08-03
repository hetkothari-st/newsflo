"""Quality gates and cost measurement for the LLM cost-optimization work.

Every phase of that work has a gate that can only be answered against real
articles and a live provider key -- "is refinement as good off `facts` as it
was off the article body", "would this rule have thrown away a real story",
"is the cheap model equivalent on THIS call", "what does a run actually
cost". This script is those gates. It reads the articles already in the
database and calls the configured provider; it never invents fixtures,
because a gate that passes on synthetic input has answered nothing.

    python cost_optimization_report.py prefilter-shadow --limit 50
    python cost_optimization_report.py refinement-diff --limit 10
    python cost_optimization_report.py tier-diff --limit 15
    python cost_optimization_report.py cost --limit 30 --articles-per-day 50

`prefilter-shadow` needs no API key -- the rules are deterministic. The
other three make real calls and cost real money.
"""
import argparse
import sys
from collections import defaultdict

from app.analysis.claude_client import build_client
from app.analysis.usage_log import recent_usage, reset_usage
from app.config import (
    LLM_MODEL_PRICING_USD_PER_MTOK, LLM_TIERABLE_CALLS, LLM_TIER_CHEAP,
    LLM_TIER_REASONING, settings,
)
from app.db import SessionLocal
from app.models import Article


def _rule(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def _articles(session, limit: int, statuses=("ANALYZED", "CATEGORIZED", "FILTERED", "NEW")):
    return (
        session.query(Article)
        .filter(Article.status.in_(statuses))
        .order_by(Article.fetched_at.desc())
        .limit(limit)
        .all()
    )


def _require_articles(articles, limit: int) -> None:
    if len(articles) < limit:
        print(
            f"WARNING: asked for {limit} articles, database has {len(articles)}. "
            "A gate run on fewer articles than the plan calls for is not a passed gate."
        )
    if not articles:
        sys.exit("No articles in the database -- run the ingestion pipeline first.")


def _client():
    if not (settings.gemini_api_key or settings.groq_api_keys):
        sys.exit(
            "No provider key configured (GEMINI_API_KEY / GROQ_API_KEY). This gate makes "
            "real LLM calls; there is nothing to measure without one."
        )
    return build_client(settings.groq_api_keys, settings.gemini_api_key or None)


# --- phase 3 gate: what the pre-filter rules would throw away ---

def prefilter_shadow(args) -> None:
    """Print every article the rules WOULD short-circuit, with the reason.
    Read them. The gate passes only if none of them is real market news --
    and that judgement is a human's, not this script's."""
    from app.filtering.prefilter import REJECT, prefilter_verdict
    from app.pipeline import article_text

    session = SessionLocal()
    try:
        articles = _articles(session, args.scan)
        _require_articles(articles, args.scan)
        rejects = []
        for article in articles:
            verdict, reason = prefilter_verdict(article.title, article_text(article))
            if verdict == REJECT:
                rejects.append((article, reason))

        _rule(f"PRE-FILTER SHADOW REVIEW -- {len(rejects)} rejects out of {len(articles)} articles scanned")
        for index, (article, reason) in enumerate(rejects[:args.limit], start=1):
            print(f"\n[{index}] {article.title}")
            print(f"    source : {article.source}")
            print(f"    reason : {reason}")
            print(f"    body   : {article_text(article)[:240]}")
        share = 100.0 * len(rejects) / len(articles) if articles else 0.0
        print(
            f"\nThe rules would skip {len(rejects)}/{len(articles)} relevance calls ({share:.1f}%). "
            "Review every reject above before setting RELEVANCE_PREFILTER_MODE=enforce."
        )
    finally:
        session.close()


# --- phase 1 gate: refinement off `facts` vs off the article body ---

def refinement_diff(args) -> None:
    """For each article: extract facts once, then generate the event
    summary and timeline BOTH ways -- from the distilled facts and from the
    raw body -- and print them together. The gate passes only if the facts
    version is as informative as the body version on every article."""
    from app.analysis.cascade import _extract_facts
    from app.analysis.refinement import generate_event_summary, generate_timeline_effects
    from app.pipeline import article_text

    client = _client()
    session = SessionLocal()
    try:
        articles = _articles(session, args.limit)
        _require_articles(articles, args.limit)
        for index, article in enumerate(articles, start=1):
            body = article_text(article)
            facts = _extract_facts(client, article.title, body).facts
            _rule(f"[{index}/{len(articles)}] {article.title}")
            print(f"\n--- facts (stage 1 distillation, {len(facts)} chars vs {len(body)} chars of body) ---")
            print(facts)
            for label, source in (("NEW (from facts)", facts), ("OLD (from article body)", body)):
                summary = generate_event_summary(client, article.title, source)
                timeline = generate_timeline_effects(client, article.title, source)
                print(f"\n--- {label} ---")
                print(f"  summary_short: {(summary or {}).get('summary_short')}")
                print(f"  summary_long : {(summary or {}).get('summary_long')}")
                print(f"  unconfirmed  : {(summary or {}).get('is_unconfirmed')}")
                for effect in timeline:
                    print(f"  {effect['horizon']:<9}: {effect['description']}")
        print(
            "\nGATE: the facts version must be equal or better on every article. If any of them "
            "lost a detail the body version had, fix _extract_facts to capture it -- do not accept "
            "the loss."
        )
    finally:
        session.close()


# --- phase 4 gate: strong model vs cheap model, per call ---

def tier_diff(args) -> None:
    """Run each downgrade-eligible call on both tiers over the same
    articles and print the two outputs. A call may move to the cheap tier
    only if its cheap output is equivalent on EVERY article -- one missed
    company, one weaker why, one malformed tool call, and it stays put."""
    from app.analysis.cascade import _extract_facts, _generate_edges, _identify_sectors
    from app.analysis.refinement import generate_event_summary, generate_timeline_effects
    from app.filtering.relevance import classify_relevance
    from app.pipeline import article_text

    client = _client()
    session = SessionLocal()
    calls = args.calls or sorted(LLM_TIERABLE_CALLS)
    unknown = set(calls) - LLM_TIERABLE_CALLS
    if unknown:
        sys.exit(f"Not downgrade-eligible (or protected): {sorted(unknown)}")

    def run(call_name, tier, article, facts):
        """Each runner forces `tier` for the duration of one call by
        listing (or not listing) the call in LLM_CHEAP_TIER_CALLS, which is
        the same switch production uses -- no separate code path."""
        original = settings.llm_cheap_tier_calls
        settings.llm_cheap_tier_calls = call_name if tier == LLM_TIER_CHEAP else ""
        try:
            if call_name == "classify_relevance":
                return classify_relevance(client, article.title, article_text(article))
            if call_name == "identify_sectors":
                return [(s.sector, s.direction, s.mechanism) for s in _identify_sectors(client, facts, None)]
            if call_name == "generate_edges":
                return _generate_edges(client, facts, None, [])
            if call_name == "event_summary":
                return generate_event_summary(client, article.title, facts)
            if call_name == "timeline_effects":
                return generate_timeline_effects(client, article.title, facts)
            return f"(no runner wired for {call_name} -- diff it by hand before moving it)"
        except Exception as exc:  # a crash IS a result: it fails the gate
            return f"RAISED {type(exc).__name__}: {exc}"
        finally:
            settings.llm_cheap_tier_calls = original

    try:
        articles = _articles(session, args.limit)
        _require_articles(articles, args.limit)
        for call_name in calls:
            _rule(f"CALL: {call_name} -- strong vs cheap over {len(articles)} articles")
            for index, article in enumerate(articles, start=1):
                facts = _extract_facts(client, article.title, article_text(article)).facts
                print(f"\n[{index}] {article.title}")
                print(f"  STRONG: {run(call_name, LLM_TIER_REASONING, article, facts)}")
                print(f"  CHEAP : {run(call_name, LLM_TIER_CHEAP, article, facts)}")
        print(
            "\nGATE: move a call to LLM_CHEAP_TIER_CALLS only if its CHEAP output is equivalent on "
            "every article above. extract_facts and identify_companies are not on this list and "
            "cannot be moved."
        )
    finally:
        session.close()


# --- phase 6: what a run actually costs ---

def cost(args) -> None:
    """Run N articles through the real pipeline with token accounting on,
    then report per-call token totals and a monthly projection."""
    from app.pipeline import process_new_articles

    settings.llm_usage_db_logging = True
    client = _client()
    session = SessionLocal()
    try:
        articles = _articles(session, args.limit, statuses=("CATEGORIZED",))
        _require_articles(articles, args.limit)
        reset_usage()
        created = process_new_articles(session, client)
        usage = recent_usage()
    finally:
        session.close()

    _rule(f"COST REPORT -- {len(articles)} articles, {created} alerts, {len(usage)} LLM calls")
    by_call = defaultdict(lambda: {"calls": 0, "input": 0, "output": 0, "cached": 0, "models": set()})
    for entry in usage:
        row = by_call[entry.call_name or "(unnamed)"]
        row["calls"] += 1
        row["input"] += entry.input_tokens or 0
        row["output"] += entry.output_tokens or 0
        row["cached"] += entry.cache_read_tokens or 0
        row["models"].add(entry.model)

    header = f"{'call':<22}{'calls':>7}{'input':>12}{'cached':>10}{'output':>10}"
    print(f"\n{header}\n{'-' * len(header)}")
    for call_name, row in sorted(by_call.items(), key=lambda kv: -kv[1]["input"]):
        print(f"{call_name:<22}{row['calls']:>7}{row['input']:>12}{row['cached']:>10}{row['output']:>10}")

    per_article = {
        "calls": len(usage) / len(articles),
        "input": sum(e.input_tokens or 0 for e in usage) / len(articles),
        "output": sum(e.output_tokens or 0 for e in usage) / len(articles),
        "cached": sum(e.cache_read_tokens or 0 for e in usage) / len(articles),
    }
    print(
        f"\nPer article: {per_article['calls']:.1f} calls, {per_article['input']:.0f} input tokens "
        f"({per_article['cached']:.0f} of them cache reads), {per_article['output']:.0f} output tokens"
    )

    if not LLM_MODEL_PRICING_USD_PER_MTOK:
        print(
            "\nNo prices configured, so tokens above are the whole report. Fill "
            "LLM_MODEL_PRICING_USD_PER_MTOK in app/config.py from the provider's current "
            "pricing page and re-run for a dollar figure -- a number from a stale hardcoded "
            "table would be worse than none."
        )
        return

    monthly = 0.0
    unpriced = set()
    for entry in usage:
        prices = LLM_MODEL_PRICING_USD_PER_MTOK.get(entry.model)
        if prices is None:
            unpriced.add(entry.model)
            continue
        cached = entry.cache_read_tokens or 0
        fresh = max((entry.input_tokens or 0) - cached, 0)
        monthly += (
            fresh * prices.get("input", 0.0)
            + cached * prices.get("cache_read", prices.get("input", 0.0))
            + (entry.output_tokens or 0) * prices.get("output", 0.0)
        ) / 1_000_000

    monthly = monthly / len(articles) * args.articles_per_day * 30
    print(f"\nProjected cost at {args.articles_per_day} articles/day: ${monthly:.2f}/month")
    if unpriced:
        print(f"NOT INCLUDED (no price configured): {sorted(unpriced)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    shadow = sub.add_parser("prefilter-shadow", help="phase 3 gate: review what the rules would reject")
    shadow.add_argument("--limit", type=int, default=50, help="how many rejects to print")
    shadow.add_argument("--scan", type=int, default=1000, help="how many articles to scan")
    shadow.set_defaults(func=prefilter_shadow)

    refine = sub.add_parser("refinement-diff", help="phase 1 gate: refinement from facts vs from the article body")
    refine.add_argument("--limit", type=int, default=10)
    refine.set_defaults(func=refinement_diff)

    tier = sub.add_parser("tier-diff", help="phase 4 gate: strong vs cheap model, per eligible call")
    tier.add_argument("--limit", type=int, default=15)
    tier.add_argument("--calls", nargs="*", help=f"defaults to all of {sorted(LLM_TIERABLE_CALLS)}")
    tier.set_defaults(func=tier_diff)

    cost_parser = sub.add_parser("cost", help="phase 6: real token counts and a monthly projection")
    cost_parser.add_argument("--limit", type=int, default=30)
    cost_parser.add_argument("--articles-per-day", type=int, default=50)
    cost_parser.set_defaults(func=cost)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
