import logging

from sqlalchemy.orm import Session

from app.alerting.email_client import send_email
from app.models import Alert, AlertCompany, EmailNotification, User, utcnow

logger = logging.getLogger(__name__)


def send_pending_notifications(
    session: Session, notifications: list[EmailNotification], email_fn=send_email
) -> int:
    """Send an email for each notification, marking it 'sent' or 'failed'.

    For each notification, look up the recipient User, the AlertCompany (company
    name/ticker/direction/magnitude/rationale) and its parent Alert's Article
    (headline), build the email, and call ``email_fn``. On True -> 'sent' +
    sent_at; on False or any exception -> 'failed' (never raised). One failed
    email must not block the others in the batch (same resilience pattern as
    Plan 2's outcome tracker). Commits after each notification. Returns the count
    marked 'sent'.
    """
    sent_count = 0
    for notification in notifications:
        alert_company = (
            session.query(AlertCompany).filter_by(id=notification.alert_company_id).one()
        )
        user = session.query(User).filter_by(id=notification.user_id).one()
        alert = session.query(Alert).filter_by(id=alert_company.alert_id).one()
        company = alert_company.company

        subject = f"NewsFlo Alert: {company.name} ({alert_company.direction})"
        body = (
            f"News: {alert.article.title}\n"
            f"Company: {company.name} ({company.ticker})\n"
            f"Direction: {alert_company.direction}\n"
            f"Estimated move: {alert_company.magnitude_low}% to {alert_company.magnitude_high}%\n"
            f"Why: {alert_company.rationale}\n"
        )

        try:
            ok = email_fn(to=user.email, subject=subject, body=body)
        except Exception:
            logger.exception("Email send raised for notification id=%s", notification.id)
            ok = False

        if ok:
            notification.status = "sent"
            notification.sent_at = utcnow()
            sent_count += 1
        else:
            notification.status = "failed"
        session.commit()

    return sent_count
