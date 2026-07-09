from app.alerting.matcher import match_alert_to_holdings
from app.models import Alert, AlertCompany, Article, Company, EmailNotification, Holding, User


def _seed_alert_with_company(session):
    company = Company(ticker="RELIANCE.NS", name="Reliance", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    article = Article(source="test", url="https://example.com/m", title="Oil news", content="")
    session.add_all([company, article])
    session.commit()
    alert = Alert(article_id=article.id, category="oil_energy")
    session.add(alert)
    session.commit()
    ac = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="x", basis="direct_mention",
    )
    session.add(ac)
    session.commit()
    return alert, company, ac


def test_matcher_creates_notification_for_holder(db_session):
    alert, company, ac = _seed_alert_with_company(db_session)
    user = User(email="u@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    db_session.add(Holding(user_id=user.id, company_id=company.id, quantity=5.0))
    db_session.commit()

    created = match_alert_to_holdings(db_session, alert)

    assert len(created) == 1
    assert created[0].user_id == user.id
    assert created[0].alert_company_id == ac.id
    assert created[0].status == "pending"


def test_matcher_ignores_non_holders(db_session):
    alert, company, ac = _seed_alert_with_company(db_session)
    other = Company(ticker="TCS.NS", name="TCS", sector="it", index_tier="NIFTY50", market_cap=1.0)
    user = User(email="u@example.com", hashed_password="x")
    db_session.add_all([other, user])
    db_session.commit()
    db_session.add(Holding(user_id=user.id, company_id=other.id, quantity=5.0))
    db_session.commit()

    created = match_alert_to_holdings(db_session, alert)

    assert created == []
    assert db_session.query(EmailNotification).count() == 0


def test_matcher_is_idempotent(db_session):
    alert, company, ac = _seed_alert_with_company(db_session)
    user = User(email="u@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    db_session.add(Holding(user_id=user.id, company_id=company.id, quantity=5.0))
    db_session.commit()

    first = match_alert_to_holdings(db_session, alert)
    second = match_alert_to_holdings(db_session, alert)

    assert len(first) == 1
    assert second == []  # only newly created rows are returned; the pre-existing one is not
    assert db_session.query(EmailNotification).count() == 1
