from sqlalchemy.orm import Session

from app.models import Alert, EmailNotification, Holding


def match_alert_to_holdings(session: Session, alert: Alert) -> list[EmailNotification]:
    """For each company in ``alert``, find every user holding that company and
    queue a pending EmailNotification for the ``(user, alert_company)`` pair,
    unless one already exists. Returns only the newly created notifications.

    The pre-check query is a second layer of idempotency on top of the DB unique
    constraint (mirrors the outcome tracker in Plan 2), so re-running the matcher
    for the same alert never double-notifies the same user for the same
    alert-company match.
    """
    created: list[EmailNotification] = []
    for alert_company in alert.companies:
        holdings = (
            session.query(Holding)
            .filter(Holding.company_id == alert_company.company_id)
            .all()
        )
        for holding in holdings:
            existing = (
                session.query(EmailNotification)
                .filter_by(user_id=holding.user_id, alert_company_id=alert_company.id)
                .one_or_none()
            )
            if existing is not None:
                continue
            notification = EmailNotification(
                user_id=holding.user_id,
                alert_company_id=alert_company.id,
                status="pending",
            )
            session.add(notification)
            session.commit()
            created.append(notification)
    return created
