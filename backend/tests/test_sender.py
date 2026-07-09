from app.alerting.sender import send_pending_notifications
from app.models import Alert, AlertCompany, Article, Company, EmailNotification, User


def _seed_notification(session):
    company = Company(ticker="RELIANCE.NS", name="Reliance", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    article = Article(source="test", url="https://example.com/s", title="Oil news headline", content="")
    user = User(email="send@example.com", hashed_password="x")
    session.add_all([company, article, user])
    session.commit()
    alert = Alert(article_id=article.id, category="oil_energy")
    session.add(alert)
    session.commit()
    ac = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin", basis="direct_mention",
    )
    session.add(ac)
    session.commit()
    notification = EmailNotification(user_id=user.id, alert_company_id=ac.id, status="pending")
    session.add(notification)
    session.commit()
    return notification


def test_send_marks_sent_with_console_backend(db_session):
    notification = _seed_notification(db_session)

    sent = send_pending_notifications(db_session, [notification])  # default console email_fn

    assert sent == 1
    refreshed = db_session.query(EmailNotification).filter_by(id=notification.id).one()
    assert refreshed.status == "sent"
    assert refreshed.sent_at is not None


def test_send_passes_expected_subject_and_recipient(db_session):
    notification = _seed_notification(db_session)
    captured = {}

    def fake_email(to, subject, body):
        captured["to"] = to
        captured["subject"] = subject
        captured["body"] = body
        return True

    sent = send_pending_notifications(db_session, [notification], email_fn=fake_email)

    assert sent == 1
    assert captured["to"] == "send@example.com"
    assert "Reliance" in captured["subject"]
    assert "bullish" in captured["subject"]
    assert "Oil news headline" in captured["body"]


def test_send_marks_failed_on_false_without_raising(db_session):
    notification = _seed_notification(db_session)

    sent = send_pending_notifications(db_session, [notification], email_fn=lambda to, subject, body: False)

    assert sent == 0
    refreshed = db_session.query(EmailNotification).filter_by(id=notification.id).one()
    assert refreshed.status == "failed"
    assert refreshed.sent_at is None


def test_send_marks_failed_on_exception_and_continues_batch(db_session):
    n1 = _seed_notification(db_session)
    # A second notification for a different user on the same alert_company.
    user2 = User(email="send2@example.com", hashed_password="x")
    db_session.add(user2)
    db_session.commit()
    n2 = EmailNotification(user_id=user2.id, alert_company_id=n1.alert_company_id, status="pending")
    db_session.add(n2)
    db_session.commit()

    def flaky(to, subject, body):
        if to == "send@example.com":
            raise RuntimeError("smtp down")
        return True

    sent = send_pending_notifications(db_session, [n1, n2], email_fn=flaky)

    assert sent == 1
    r1 = db_session.query(EmailNotification).filter_by(id=n1.id).one()
    r2 = db_session.query(EmailNotification).filter_by(id=n2.id).one()
    assert r1.status == "failed"  # the raising one is marked failed, not fatal
    assert r2.status == "sent"    # the batch continued
