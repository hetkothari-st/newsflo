"""One-off: re-run analysis on the N most recently created alerts using the
CURRENT sector-cascade analysis pipeline (see app.analysis.cascade), updating
each matched company's
rationale/key_points in place (same Alert/AlertCompany row, same id,
same created_at) -- does not add or remove AlertCompany rows, only
refreshes the text for companies the fresh analysis still names. A
company from the original alert that the fresh analysis no longer names
is left completely unchanged (not deleted), and a company the fresh
analysis newly names that wasn't in the original alert is skipped
entirely (not inserted) -- this script only ever updates existing rows,
it never changes which companies an alert lists.

Prints the old and new rationale/key_points for every row it touches
before committing, so there is a console record of what changed.

Passes ``session=`` to analyze_article, same as the live pipeline, so the
fresh call is grounded against the real candidate list/ticker enum rather
than unconstrained. This script never calls resolve_companies (it only
updates rationale/key_points on AlertCompany rows already present), so it
has no anchor_sub_sectors map to build.

Not part of the test suite and not imported by the app.

Usage (from the backend/ directory, against whichever DATABASE_URL is
active in the environment -- e.g. `railway run python reanalyze_recent.py`
to run against production):
    .venv/Scripts/python reanalyze_recent.py [N] [--force]
"""
import json
import sys

from app.analysis.cascade import analyze_article
from app.analysis.claude_client import build_client
from app.companies.resolution import _find_direct_company
from app.config import settings
from app.db import SessionLocal, init_db
from app.models import Alert
from app.pipeline import article_text, clear_analysis_cache, get_cached_analysis, store_analysis_cache


def _reconcile_alert_companies(alert, fresh_by_company_id: dict) -> None:
    """Write the fresh rationale/key_points onto each matched AlertCompany
    row on `alert.companies` (caller commits).

    Blueprint §26 ("gated V4 rows cannot be mutated by legacy refinement" /
    "no legacy worker may mutate current gated output"): a row that
    already carries `gate_state` or `display_tier` is V4 gate output --
    this legacy re-analysis script must never overwrite it, so it is
    skipped with a loud console line instead. Behavior for every other row
    is byte-identical to before this guard.

    Extracted from main()'s alert loop (same shape unchanged) so it can be
    imported and unit-tested directly, without argparse/DB/LLM setup --
    this module has no import-time side effects (everything real happens
    under `if __name__ == "__main__":`), so a plain `import
    reanalyze_recent` in a test is safe.
    """
    for ac in alert.companies:
        match = fresh_by_company_id.get(ac.company_id)
        if match is None:
            print(f"  {ac.company.name} ({ac.company.ticker}): no match in fresh analysis, left unchanged")
            continue
        if ac.gate_state is not None or ac.display_tier is not None:
            print(f"  {ac.company.name} ({ac.company.ticker}): "
                  f"SKIPPED (gated row -- V4 output is immutable to legacy scripts)")
            continue

        old_key_points = json.loads(ac.key_points_json or "[]")
        print(f"  {ac.company.name} ({ac.company.ticker}):")
        print(f"    OLD rationale: {ac.rationale}")
        print(f"    OLD key_points: {old_key_points}")
        print(f"    NEW rationale: {match.rationale}")
        print(f"    NEW key_points: {match.key_points}")

        ac.rationale = match.rationale
        ac.key_points_json = json.dumps(match.key_points)


def main(limit: int, force: bool) -> None:
    init_db()
    session = SessionLocal()
    client = build_client(settings.groq_api_keys, settings.gemini_api_key or None)

    alerts = session.query(Alert).order_by(Alert.created_at.desc()).limit(limit).all()

    for alert in alerts:
        article = alert.article
        print(f"\n=== Alert {alert.id}: {article.title} ===")
        if force:
            clear_analysis_cache(session, article)
        result = get_cached_analysis(session, article)
        if result is not None:
            print("  (using cached analysis -- pass --force for a fresh LLM call)")
        else:
            try:
                result = analyze_article(client, article.title, article_text(article), session=session)
            except Exception as exc:
                print(f"  SKIPPED (analysis call failed: {exc})")
                continue
            store_analysis_cache(session, article, result)

        # Resolve each fresh mention to a real Company row the same way the
        # live pipeline does (ticker match, then unambiguous name match) so
        # a fresh mention lines up with an existing AlertCompany by
        # company_id, not by re-deriving ticker-string matching here.
        fresh_by_company_id = {}
        for mention in result.companies:
            company = _find_direct_company(session, mention)
            if company is not None:
                fresh_by_company_id[company.id] = mention

        _reconcile_alert_companies(alert, fresh_by_company_id)
        session.commit()

    session.close()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv
    limit = int(args[0]) if args else 3
    main(limit, force)
