from sqlalchemy.orm import Session

from app.alerting.matcher import match_alert_to_holdings
from app.alerting.sender import send_pending_notifications
from app.analysis.claude_client import analyze_article
from app.calibration.blender import get_calibrated_magnitude
from app.companies.market import infer_market
from app.companies.resolution import resolve_companies
from app.filtering.heuristic import filter_new_articles
from app.models import Alert, AlertCompany, Article
from app.ws.manager import manager


def _alert_broadcast_payload(alert: Alert) -> dict:
    """Shape one live-push payload identical to a single GET /api/alerts entry,
    MINUS the per-viewer ``in_my_holdings`` flag.

    Known simplification: the pipeline has no viewer context at broadcast time,
    so live-pushed companies carry no holdings-match. The frontend defaults
    live-pushed companies to ``in_my_holdings: false`` and the next full
    ``GET /api/alerts`` refresh reconciles them — correct-eventually, and
    simpler than threading per-user state through the broadcast.
    """
    return {
        "id": alert.id,
        "category": alert.category,
        "created_at": alert.created_at.isoformat(),
        "article": {
            "id": alert.article.id,
            "title": alert.article.title,
            "url": alert.article.url,
        },
        "companies": [{
            "company_id": ac.company_id,
            "ticker": ac.company.ticker,
            "name": ac.company.name,
            "index_tier": ac.company.index_tier,
            "direction": ac.direction,
            "magnitude_low": ac.magnitude_low,
            "magnitude_high": ac.magnitude_high,
            "rationale": ac.rationale,
            "basis": ac.basis,
            "confidence": ac.confidence,
            "market": infer_market(ac.company.ticker),
        } for ac in alert.companies],
    }


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
        # With no matching holdings this is a no-op.
        new_notifications = match_alert_to_holdings(session, alert)
        send_pending_notifications(session, new_notifications)

        # Plan 4: push the new alert to every connected dashboard over WebSocket.
        # Safe no-op if the app hasn't started (no captured loop) or nobody is
        # connected — this never crashes headless pipeline runs or tests.
        manager.broadcast_sync(_alert_broadcast_payload(alert))

    return alerts_created
