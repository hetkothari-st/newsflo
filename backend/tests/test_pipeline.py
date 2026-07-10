import pytest

import app.pipeline as pipeline_module
from app.analysis.schemas import AnalysisOutput, CompanyMention
from app.models import (
    Alert,
    AlertCompany,
    Article,
    CalibrationSample,
    Company,
    EmailNotification,
    Holding,
    User,
)
from app.pipeline import process_new_articles


def test_process_new_articles_creates_alert_end_to_end(db_session, monkeypatch):
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    article = Article(
        source="test", url="https://example.com/a",
        title="US strikes Iran oil export sites", content="crude oil markets react",
    )
    db_session.add(article)
    db_session.commit()

    fake_output = AnalysisOutput(
        category="oil_energy",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)

    created = process_new_articles(db_session, claude_client=object())

    assert created == 1
    alert = db_session.query(Alert).one()
    assert alert.category == "oil_energy"

    alert_companies = db_session.query(AlertCompany).filter_by(alert_id=alert.id).all()
    assert len(alert_companies) == 1
    assert alert_companies[0].company_id == company.id
    # No calibration samples exist, so the alert falls back to the LLM's own estimate.
    assert alert_companies[0].confidence == "llm_estimate"
    assert alert_companies[0].magnitude_low == 2.0
    assert alert_companies[0].magnitude_high == 4.0

    # No holdings exist, so no email notifications were created (matcher no-op).
    assert db_session.query(EmailNotification).count() == 0

    refreshed_article = db_session.query(Article).filter_by(id=article.id).one()
    assert refreshed_article.status == "ANALYZED"


def test_process_new_articles_uses_calibrated_magnitude_when_enough_samples(db_session, monkeypatch):
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    # 5 samples of [1, 2, 3, 4, 5] for (oil_energy, this company) -> mean = 3.0, pstdev = sqrt(2).
    for i, actual in enumerate([1.0, 2.0, 3.0, 4.0, 5.0]):
        db_session.add(CalibrationSample(
            alert_company_id=i + 1, category="oil_energy", company_id=company.id,
            direction="bullish", magnitude_actual=actual, horizon_days=1,
        ))
    db_session.commit()

    article = Article(
        source="test", url="https://example.com/cal",
        title="US strikes Iran oil export sites", content="crude oil markets react",
    )
    db_session.add(article)
    db_session.commit()

    fake_output = AnalysisOutput(
        category="oil_energy",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)

    created = process_new_articles(db_session, claude_client=object())
    assert created == 1

    ac = db_session.query(AlertCompany).one()
    assert ac.confidence == "calibrated"
    # mean([1,2,3,4,5]) = 3.0, pstdev = sqrt(2) ~= 1.41421356
    assert ac.magnitude_low == pytest.approx(3.0 - 2 ** 0.5)
    assert ac.magnitude_high == pytest.approx(3.0 + 2 ** 0.5)


def test_process_new_articles_sends_email_notification_for_holder(db_session, monkeypatch):
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    user = User(email="holder@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    db_session.add(Holding(user_id=user.id, company_id=company.id, quantity=10.0))
    db_session.commit()

    article = Article(
        source="test", url="https://example.com/notify",
        title="US strikes Iran oil export sites", content="crude oil markets react",
    )
    db_session.add(article)
    db_session.commit()

    fake_output = AnalysisOutput(
        category="oil_energy",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)

    created = process_new_articles(db_session, claude_client=object())
    assert created == 1

    notifications = db_session.query(EmailNotification).all()
    assert len(notifications) == 1
    assert notifications[0].user_id == user.id
    # The default console email backend always succeeds, so the row is marked sent.
    assert notifications[0].status == "sent"


def test_process_new_articles_marks_analysis_failed_after_retries(db_session, monkeypatch):
    article = Article(source="test", url="https://example.com/b", title="RBI hikes repo rate", content="")
    db_session.add(article)
    db_session.commit()

    def boom(client, title, content):
        raise RuntimeError("api down")

    monkeypatch.setattr(pipeline_module, "analyze_article", boom)

    created = process_new_articles(db_session, claude_client=object())

    assert created == 0
    refreshed = db_session.query(Article).filter_by(id=article.id).one()
    assert refreshed.status == "ANALYSIS_FAILED"


def test_process_new_articles_reuses_analysis_for_republished_article(db_session, monkeypatch):
    # RSS sources frequently republish the identical wire story. The second
    # article (same title, different casing/whitespace, different URL --
    # exactly how a republish looks) must reuse the first's analysis
    # instead of spending a second LLM call, and must produce the SAME
    # AlertCompany data a second real call would have.
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    first = Article(
        source="source-a", url="https://example.com/first",
        title="US strikes Iran oil export sites", content="crude oil markets react",
    )
    second = Article(
        source="source-b", url="https://example.com/second",
        title="  US STRIKES   Iran oil export sites  ", content="crude oil markets react, wire copy",
    )
    db_session.add_all([first, second])
    db_session.commit()

    fake_output = AnalysisOutput(
        category="oil_energy",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
        )],
    )
    call_count = {"n": 0}

    def counting_analyze(client, title, content):
        call_count["n"] += 1
        return fake_output

    monkeypatch.setattr(pipeline_module, "analyze_article", counting_analyze)

    created = process_new_articles(db_session, claude_client=object())

    assert created == 2
    assert call_count["n"] == 1  # only the first article triggered a real LLM call

    alerts = db_session.query(Alert).order_by(Alert.id).all()
    assert len(alerts) == 2
    assert alerts[0].category == alerts[1].category == "oil_energy"

    first_ac = db_session.query(AlertCompany).filter_by(alert_id=alerts[0].id).one()
    second_ac = db_session.query(AlertCompany).filter_by(alert_id=alerts[1].id).one()
    assert second_ac.company_id == first_ac.company_id
    assert second_ac.direction == first_ac.direction
    assert second_ac.rationale == first_ac.rationale
    assert second_ac.basis == first_ac.basis

    refreshed_second = db_session.query(Article).filter_by(id=second.id).one()
    assert refreshed_second.status == "ANALYZED"


def test_process_new_articles_sets_image_url_from_og_image_fetch(db_session, monkeypatch):
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    article = Article(
        source="test", url="https://example.com/img",
        title="US strikes Iran oil export sites", content="crude oil markets react",
    )
    db_session.add(article)
    db_session.commit()

    fake_output = AnalysisOutput(
        category="oil_energy",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)
    monkeypatch.setattr(pipeline_module, "fetch_og_image", lambda url: "https://example.com/img.jpg")

    created = process_new_articles(db_session, claude_client=object())
    assert created == 1

    refreshed = db_session.query(Article).filter_by(id=article.id).one()
    assert refreshed.image_url == "https://example.com/img.jpg"


def test_process_new_articles_ignores_filtered_articles(db_session, monkeypatch):
    irrelevant = Article(source="test", url="https://example.com/c", title="Cat stuck in tree", content="")
    db_session.add(irrelevant)
    db_session.commit()

    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: (_ for _ in ()).throw(AssertionError("should not be called")))

    created = process_new_articles(db_session, claude_client=object())

    assert created == 0
    refreshed = db_session.query(Article).filter_by(id=irrelevant.id).one()
    assert refreshed.status == "FILTERED"
