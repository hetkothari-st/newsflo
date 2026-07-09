from sqlalchemy.orm import Session

from app.alerting.matcher import match_alert_to_holdings
from app.alerting.sender import send_pending_notifications
from app.analysis.claude_client import analyze_article
from app.calibration.blender import get_calibrated_magnitude
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
            calibrated = get_calibrated_magnitude(
                session, category=analysis.category, company_id=entry["company_id"],
            )
            if calibrated is not None:
                low, high = calibrated
                entry["magnitude_low"] = low
                entry["magnitude_high"] = high
                entry["confidence"] = "calibrated"
            else:
                entry["confidence"] = "llm_estimate"
            session.add(AlertCompany(alert_id=alert.id, **entry))

        article.status = "ANALYZED"
        article.category = analysis.category
        session.commit()
        alerts_created += 1

        # Plan 3: fan out email alerts to any users holding an affected company.
        # With no matching holdings this is a no-op — the matcher returns [] and
        # the sender processes an empty list — so existing tests are unaffected.
        new_notifications = match_alert_to_holdings(session, alert)
        send_pending_notifications(session, new_notifications)

    return alerts_created
