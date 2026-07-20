"""One-off: fully re-analyze the N most recently created alerts using the
current sector-cascade pipeline (app.analysis.cascade), REPLACING each
alert's companies entirely -- including real indirect_l1/indirect_l2
cascade rows the fresh analysis finds that the original alert never had.

Unlike reanalyze_recent.py (which only refreshes rationale/key_points text
on companies already present in the alert and never adds/removes rows),
this script deletes the alert's existing AlertCompany rows and re-persists
a fresh set via app.pipeline._build_alert_company -- the same calibration/
confidence logic process_new_articles uses for a brand new article, reused
directly rather than duplicated, so this can't drift from the live
pipeline's behavior.

The Alert row itself (id, created_at, article_id) is left untouched --
only its companies are replaced -- so existing links/bookmarks to this
alert id keep working. Any existing AlertCompanyTranslation rows for the
deleted companies are deleted too (a FK requires it) -- they regenerate
on-demand the next time that alert is viewed in a non-English language.

Prints a before/after company list per alert, including which impact
levels appeared, so there's a console record of what changed.

Not part of the test suite and not imported by the app.

Usage (from the backend/ directory, against whichever DATABASE_URL is
active in the environment -- e.g. `railway run python reanalyze_cascade.py`
to run against production):
    .venv/Scripts/python reanalyze_cascade.py [N]
"""
import sys

from app.analysis.cascade import analyze_article
from app.analysis.claude_client import build_client
from app.companies.resolution import resolve_companies
from app.config import settings
from app.db import SessionLocal, init_db
from app.models import Alert, AlertCompanyTranslation
from app.pipeline import _build_alert_company, article_text


def main(limit: int) -> None:
    init_db()
    session = SessionLocal()
    client = build_client(settings.groq_api_keys, settings.anthropic_api_key or None)

    alerts = session.query(Alert).order_by(Alert.created_at.desc()).limit(limit).all()

    for alert in alerts:
        article = alert.article
        print(f"\n=== Alert {alert.id}: {article.title} ===")
        old_summary = [(c.company.ticker, c.impact_level) for c in alert.companies]
        print(f"  BEFORE: {old_summary}")

        try:
            result = analyze_article(client, article.title, article_text(article))
        except Exception as exc:
            print(f"  SKIPPED (analysis call failed: {exc})")
            continue

        resolved = resolve_companies(session, result.companies)

        old_company_ids = [ac.id for ac in alert.companies]
        if old_company_ids:
            session.query(AlertCompanyTranslation).filter(
                AlertCompanyTranslation.alert_company_id.in_(old_company_ids),
            ).delete(synchronize_session=False)
        for ac in list(alert.companies):
            session.delete(ac)
        session.flush()

        for entry in resolved:
            session.add(_build_alert_company(session, alert.id, article, result.category, entry))
        session.commit()

        session.refresh(alert)
        new_summary = [(c.company.ticker, c.impact_level, c.parent_company_id) for c in alert.companies]
        print(f"  AFTER:  {new_summary}")

    session.close()


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    main(limit)
