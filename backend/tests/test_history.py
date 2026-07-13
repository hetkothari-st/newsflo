from datetime import timedelta

from sqlalchemy import event

from app.companies.history import bulk_past_mentions, get_past_mentions, mentions_before
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


def test_bulk_past_mentions_and_mentions_before_match_get_past_mentions(db_session):
    company = _make_company(db_session)
    now = utcnow()
    _make_alert(db_session, company, now - timedelta(days=3), title="oldest", direction="bearish")
    _make_alert(db_session, company, now - timedelta(days=1), title="newest prior", direction="bullish")
    current = _make_alert(db_session, company, now, title="current alert")

    single = get_past_mentions(db_session, company.id, before=current.created_at)
    index = bulk_past_mentions(db_session, [company.id])
    bulk = mentions_before(index, company.id, before=current.created_at)

    assert bulk == single


def test_bulk_past_mentions_gives_each_alert_its_own_cutoff(db_session):
    # Two alerts for the same company at different times -- each one's
    # "past mentions" must only include alerts strictly before ITS OWN
    # created_at, not a single global cutoff, since bulk_past_mentions
    # fetches one company's full history once and mentions_before slices it
    # per alert.
    company = _make_company(db_session)
    now = utcnow()
    first = _make_alert(db_session, company, now - timedelta(days=2), title="first")
    second = _make_alert(db_session, company, now - timedelta(days=1), title="second")
    third = _make_alert(db_session, company, now, title="third")

    index = bulk_past_mentions(db_session, [company.id])

    assert [m["article_title"] for m in mentions_before(index, company.id, before=first.created_at)] == []
    assert [m["article_title"] for m in mentions_before(index, company.id, before=second.created_at)] == ["first"]
    assert [m["article_title"] for m in mentions_before(index, company.id, before=third.created_at)] == [
        "second", "first",
    ]


def test_mentions_before_respects_limit(db_session):
    company = _make_company(db_session)
    now = utcnow()
    for i in range(5):
        _make_alert(db_session, company, now - timedelta(days=i + 1), title=f"story {i}")
    current = _make_alert(db_session, company, now, title="current")

    index = bulk_past_mentions(db_session, [company.id])
    mentions = mentions_before(index, company.id, before=current.created_at, limit=3)

    assert len(mentions) == 3


def test_bulk_past_mentions_returns_empty_dict_for_empty_input(db_session):
    assert bulk_past_mentions(db_session, []) == {}


def test_bulk_past_mentions_runs_one_query_regardless_of_company_count(db_session):
    company_a = _make_company(db_session, ticker="RELIANCE.NS", name="Reliance")
    company_b = _make_company(db_session, ticker="ONGC.NS", name="ONGC")
    company_c = _make_company(db_session, ticker="TCS.NS", name="TCS")
    now = utcnow()
    for i, company in enumerate((company_a, company_b, company_c)):
        _make_alert(db_session, company, now - timedelta(days=1, seconds=i), title=f"{company.ticker} prior")
        _make_alert(db_session, company, now - timedelta(seconds=i), title=f"{company.ticker} current")

    # Capture ids before starting the count: db_session.commit() expires all
    # ORM objects by default, so accessing .id on a fresh expired object is
    # itself a refresh SELECT -- doing that inside the measurement window
    # would count as noise unrelated to bulk_past_mentions's own query.
    company_ids = [company_a.id, company_b.id, company_c.id]

    query_count = 0

    def _count(*args, **kwargs):
        nonlocal query_count
        query_count += 1

    event.listen(db_session.get_bind(), "before_cursor_execute", _count)
    try:
        bulk_past_mentions(db_session, company_ids)
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", _count)

    assert query_count == 1
