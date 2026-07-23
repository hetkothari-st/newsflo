from app.market.timeline_entries import get_timeline_entries
from app.models import Alert, Article, TimelineEffect


def _article(db_session):
    article = Article(source="test", url="https://example.com/timeline", title="t", content="c")
    db_session.add(article)
    db_session.commit()
    return article


def test_returns_entries_in_horizon_order_regardless_of_insertion_order(db_session):
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(TimelineEffect(alert_id=alert.id, horizon="QUARTERS", description="Long-term effect."))
    db_session.add(TimelineEffect(alert_id=alert.id, horizon="TODAY", description="Immediate effect."))
    db_session.add(TimelineEffect(alert_id=alert.id, horizon="WEEKS", description="Weeks-long effect."))
    db_session.commit()

    result = get_timeline_entries(db_session, alert)

    assert [e["horizon"] for e in result] == ["TODAY", "WEEKS", "QUARTERS"]
    assert result[0]["description"] == "Immediate effect."


def test_returns_empty_list_when_no_timeline_effects_exist(db_session):
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.commit()

    assert get_timeline_entries(db_session, alert) == []


def test_only_returns_entries_for_this_alert(db_session):
    article1 = _article(db_session)
    alert1 = Alert(article_id=article1.id, category="oil_gas")
    db_session.add(alert1)
    db_session.flush()
    db_session.add(TimelineEffect(alert_id=alert1.id, horizon="TODAY", description="Alert 1 effect."))

    article2 = Article(source="test", url="https://example.com/timeline2", title="t2", content="c2")
    db_session.add(article2)
    db_session.commit()
    alert2 = Alert(article_id=article2.id, category="oil_gas")
    db_session.add(alert2)
    db_session.flush()
    db_session.add(TimelineEffect(alert_id=alert2.id, horizon="TODAY", description="Alert 2 effect."))
    db_session.commit()

    result = get_timeline_entries(db_session, alert1)

    assert len(result) == 1
    assert result[0]["description"] == "Alert 1 effect."
