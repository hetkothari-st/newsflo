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


def test_duplicate_generations_collapse_to_latest_per_horizon(db_session):
    """refine_alert historically APPENDED timeline rows on every re-run
    (no delete-before-insert until 2026-08-12), so alerts carry stacked
    generations of near-identical entries. Read time keeps only the most
    recent row per horizon -- one entry per horizon, newest text wins."""
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    # First refinement run:
    db_session.add(TimelineEffect(alert_id=alert.id, horizon="TODAY", description="Old immediate take."))
    db_session.add(TimelineEffect(alert_id=alert.id, horizon="WEEKS", description="Old weeks take."))
    # Second run appended near-duplicates (the historical bug):
    db_session.add(TimelineEffect(alert_id=alert.id, horizon="TODAY", description="Fresh immediate take."))
    db_session.add(TimelineEffect(alert_id=alert.id, horizon="WEEKS", description="Fresh weeks take."))
    db_session.add(TimelineEffect(alert_id=alert.id, horizon="MONTHS", description="Months take."))
    db_session.commit()

    result = get_timeline_entries(db_session, alert)

    assert [e["horizon"] for e in result] == ["TODAY", "WEEKS", "MONTHS"]
    assert result[0]["description"] == "Fresh immediate take."
    assert result[1]["description"] == "Fresh weeks take."


def test_exact_duplicate_rows_render_once(db_session):
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    for _ in range(3):
        db_session.add(TimelineEffect(alert_id=alert.id, horizon="DAYS",
                                      description="Same text three times."))
    db_session.commit()

    result = get_timeline_entries(db_session, alert)

    assert result == [{"horizon": "DAYS", "description": "Same text three times."}]


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
