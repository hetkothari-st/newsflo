from sqlalchemy.orm import Session

from app.analysis.claude_client import analyze_article
from app.companies.resolution import resolve_companies
from app.filtering.heuristic import filter_new_articles
from app.models import Alert, AlertCompany, Article


def process_new_articles(session: Session, claude_client) -> int:
    filter_new_articles(session)

    alerts_created = 0
    pending = session.query(Article).filter_by(status="CATEGORIZED").all()

    for article in pending:
        analysis = None
        for _ in range(2):  # try once, retry once
            try:
                analysis = analyze_article(claude_client, article.title, article.content)
                break
            except Exception:
                continue

        if analysis is None:
            article.status = "ANALYSIS_FAILED"
            session.commit()
            continue

        resolved = resolve_companies(session, analysis.companies)

        alert = Alert(article_id=article.id, category=analysis.category)
        session.add(alert)
        session.flush()

        for entry in resolved:
            session.add(AlertCompany(alert_id=alert.id, **entry))

        article.status = "ANALYZED"
        article.category = analysis.category
        session.commit()
        alerts_created += 1

    return alerts_created
