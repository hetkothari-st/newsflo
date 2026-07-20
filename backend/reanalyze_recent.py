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

Not part of the test suite and not imported by the app.

Usage (from the backend/ directory, against whichever DATABASE_URL is
active in the environment -- e.g. `railway run python reanalyze_recent.py`
to run against production):
    .venv/Scripts/python reanalyze_recent.py [N]
"""
import json
import sys

from app.analysis.cascade import analyze_article
from app.analysis.claude_client import build_client
from app.companies.resolution import _find_direct_company
from app.config import settings
from app.db import SessionLocal, init_db
from app.models import Alert
from app.pipeline import article_text


def main(limit: int) -> None:
    init_db()
    session = SessionLocal()
    client = build_client(settings.groq_api_keys, settings.anthropic_api_key or None)

    alerts = session.query(Alert).order_by(Alert.created_at.desc()).limit(limit).all()

    for alert in alerts:
        article = alert.article
        print(f"\n=== Alert {alert.id}: {article.title} ===")
        try:
            result = analyze_article(client, article.title, article_text(article))
        except Exception as exc:
            print(f"  SKIPPED (analysis call failed: {exc})")
            continue

        # Resolve each fresh mention to a real Company row the same way the
        # live pipeline does (ticker match, then unambiguous name match) so
        # a fresh mention lines up with an existing AlertCompany by
        # company_id, not by re-deriving ticker-string matching here.
        fresh_by_company_id = {}
        for mention in result.companies:
            company = _find_direct_company(session, mention)
            if company is not None:
                fresh_by_company_id[company.id] = mention

        for ac in alert.companies:
            match = fresh_by_company_id.get(ac.company_id)
            if match is None:
                print(f"  {ac.company.name} ({ac.company.ticker}): no match in fresh analysis, left unchanged")
                continue

            old_key_points = json.loads(ac.key_points_json or "[]")
            print(f"  {ac.company.name} ({ac.company.ticker}):")
            print(f"    OLD rationale: {ac.rationale}")
            print(f"    OLD key_points: {old_key_points}")
            print(f"    NEW rationale: {match.rationale}")
            print(f"    NEW key_points: {match.key_points}")

            ac.rationale = match.rationale
            ac.key_points_json = json.dumps(match.key_points)

        session.commit()

    session.close()


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    main(limit)
