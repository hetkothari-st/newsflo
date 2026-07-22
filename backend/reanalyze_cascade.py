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
pipeline's behavior. Existing ImpactEdge/CascadeGap rows for the alert are
also deleted and replaced with the fresh analysis's edges/gaps, using the
same app.pipeline._resolve_edge_endpoint_company_id ticker-resolution
helper _persist_alert itself uses -- without this, the graph API (GET
/api/alerts/{id}) would keep serving edges from before this run.

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
    .venv/Scripts/python reanalyze_cascade.py [N] [--force]
"""
import sys

from app.analysis.cascade import analyze_article
from app.analysis.claude_client import build_client
from app.companies.resolution import resolve_companies
from app.config import settings
from app.db import SessionLocal, init_db
from app.models import Alert, AlertCompanyTranslation, CascadeGap, Company, ImpactEdge
from app.pipeline import (
    _build_alert_company, _resolve_edge_endpoint_company_id, article_text,
    clear_analysis_cache, get_cached_analysis, store_analysis_cache,
)


def main(limit: int, force: bool) -> None:
    init_db()
    session = SessionLocal()
    client = build_client(settings.groq_api_keys, settings.anthropic_api_key or None)

    alerts = session.query(Alert).order_by(Alert.created_at.desc()).limit(limit).all()

    for alert in alerts:
        article = alert.article
        print(f"\n=== Alert {alert.id}: {article.title} ===")
        old_summary = [(c.company.ticker, c.impact_level) for c in alert.companies]
        print(f"  BEFORE: {old_summary}")

        if force:
            clear_analysis_cache(session, article)
        result = get_cached_analysis(session, article)
        if result is not None:
            print("  (using cached analysis -- pass --force for a fresh LLM call)")
        else:
            try:
                result = analyze_article(client, article.title, article_text(article))
            except Exception as exc:
                print(f"  SKIPPED (analysis call failed: {exc})")
                continue
            store_analysis_cache(session, article, result)

        resolved = resolve_companies(session, result.companies)

        old_company_ids = [ac.id for ac in alert.companies]
        if old_company_ids:
            session.query(AlertCompanyTranslation).filter(
                AlertCompanyTranslation.alert_company_id.in_(old_company_ids),
            ).delete(synchronize_session=False)
        for ac in list(alert.companies):
            session.delete(ac)
        # Edges/gaps from a prior real analysis (Phase 3) must also be
        # replaced, not left stale -- they'd otherwise reference companies
        # this alert no longer has, showing a graph that doesn't match the
        # fresh companies[] list.
        session.query(ImpactEdge).filter_by(alert_id=alert.id).delete(synchronize_session=False)
        session.query(CascadeGap).filter_by(alert_id=alert.id).delete(synchronize_session=False)
        session.flush()

        for entry in resolved:
            session.add(_build_alert_company(session, alert.id, article, result.category, entry))
        for edge in result.edges:
            from_company_id = _resolve_edge_endpoint_company_id(session, edge["from"]["kind"], edge["from"]["label"])
            to_company_id = _resolve_edge_endpoint_company_id(session, edge["to"]["kind"], edge["to"]["label"])
            from_label = edge["from"]["label"]
            # Same ground-truth-sector fix as app.pipeline._persist_alert --
            # see its comment. Duplicated here because this script persists
            # edges independently rather than calling _persist_alert.
            if edge["from"]["kind"] == "sector" and edge["to"]["kind"] == "company" and to_company_id is not None:
                company = session.get(Company, to_company_id)
                if company is not None and company.sector:
                    from_label = company.sector
            session.add(ImpactEdge(
                alert_id=alert.id,
                from_company_id=from_company_id,
                from_node_kind=edge["from"]["kind"], from_label=from_label,
                to_company_id=to_company_id,
                to_node_kind=edge["to"]["kind"], to_label=edge["to"]["label"],
                relation=edge["relation"], direction=edge["direction"], note=edge["note"], source=edge["source"],
            ))
        for gap in result.gaps:
            session.add(CascadeGap(
                alert_id=alert.id, sector=gap["sector"], impact_level=gap["impact_level"],
                parent_ticker=gap.get("parent_ticker"), attempts=gap["attempts"], last_error=gap.get("last_error"),
            ))
        session.commit()

        session.refresh(alert)
        new_summary = [(c.company.ticker, c.impact_level, c.parent_company_id) for c in alert.companies]
        print(f"  AFTER:  {new_summary}")

    session.close()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--force"]
    force = "--force" in sys.argv
    limit = int(args[0]) if args else 5
    main(limit, force)
