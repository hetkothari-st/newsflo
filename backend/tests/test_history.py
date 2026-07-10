from datetime import timedelta

from app.companies.history import get_past_mentions
from app.models import Alert, AlertCompany, Article, Company, utcnow


def _make_company(session, ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas"):
    company = Company(ticker=ticker, name=name, sector=sector, index_tier="NIFTY50", market_cap=1.0)
    session.add(company)
    session.commit()
    return company


def _make_alert(session, company, created_at, title="headline", direction="bullish", category="oil_energy"):
    article = Article(source="test", url=f"https://example.com/{created_at.isoformat()}", title=title, status="ANALYZED")
    session.add(article)
    session.commit()
    alert = Alert(article_id=article.id, category=category, created_at=created_at)
    session.add(alert)
    session.commit()
    session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction=direction,
        magnitude_low=1.0, magnitude_high=2.0, rationale="x", basis="direct_mention",
    ))
    session.commit()
    return alert


def test_get_past_mentions_returns_prior_alerts_for_same_company_newest_first(db_session):
    company = _make_company(db_session)
    now = utcnow()
    _make_alert(db_session, company, now - timedelta(days=3), title="oldest", direction="bearish")
    _make_alert(db_session, company, now - timedelta(days=1), title="newest prior", direction="bullish")
    current = _make_alert(db_session, company, now, title="current alert")

    mentions = get_past_mentions(db_session, company.id, before=current.created_at)

    assert [m["article_title"] for m in mentions] == ["newest prior", "oldest"]
    assert mentions[0]["direction"] == "bullish"


def test_get_past_mentions_excludes_alerts_at_or_after_the_boundary(db_session):
    company = _make_company(db_session)
    now = utcnow()
    current = _make_alert(db_session, company, now, title="current alert")
    _make_alert(db_session, company, now + timedelta(minutes=1), title="later alert")

    mentions = get_past_mentions(db_session, company.id, before=current.created_at)

    assert mentions == []


def test_get_past_mentions_excludes_other_companies(db_session):
    company_a = _make_company(db_session, ticker="RELIANCE.NS", name="Reliance")
    company_b = _make_company(db_session, ticker="ONGC.NS", name="ONGC")
    now = utcnow()
    _make_alert(db_session, company_b, now - timedelta(days=1), title="ONGC news")
    current = _make_alert(db_session, company_a, now, title="Reliance news")

    mentions = get_past_mentions(db_session, company_a.id, before=current.created_at)

    assert mentions == []


def test_get_past_mentions_respects_limit(db_session):
    company = _make_company(db_session)
    now = utcnow()
    for i in range(5):
        _make_alert(db_session, company, now - timedelta(days=i + 1), title=f"story {i}")
    current = _make_alert(db_session, company, now, title="current")

    mentions = get_past_mentions(db_session, company.id, before=current.created_at, limit=3)

    assert len(mentions) == 3
