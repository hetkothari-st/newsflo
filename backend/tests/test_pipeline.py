import pytest
from sqlalchemy import event

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
        category="oil_gas",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
            key_points=["Crude eases", "Refining margins widen"],
            confidence_score=85, time_horizon="Short-Term",
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)

    created = process_new_articles(db_session, claude_client=object())

    assert created == 1
    alert = db_session.query(Alert).one()
    assert alert.category == "oil_gas"

    alert_companies = db_session.query(AlertCompany).filter_by(alert_id=alert.id).all()
    assert len(alert_companies) == 1
    assert alert_companies[0].company_id == company.id
    # No calibration samples exist, so the alert falls back to the LLM's own estimate.
    assert alert_companies[0].confidence == "llm_estimate"
    assert alert_companies[0].magnitude_low == 2.0
    assert alert_companies[0].magnitude_high == 4.0
    assert pipeline_module.decode_key_points(alert_companies[0]) == ["Crude eases", "Refining margins widen"]
    # confidence_score is now computed by the deterministic Confidence
    # Engine (app.reasoning.confidence), not the mocked LLM's old value of
    # 85 -- exact formula behavior is covered by test_confidence.py.
    assert 0 <= alert_companies[0].confidence_score <= 100
    assert alert_companies[0].confidence_band in {"LOW", "MODERATE", "HIGH", "VERY_HIGH"}
    assert alert_companies[0].time_horizon == "Short-Term"

    # No holdings exist, so no email notifications were created (matcher no-op).
    assert db_session.query(EmailNotification).count() == 0

    refreshed_article = db_session.query(Article).filter_by(id=article.id).one()
    assert refreshed_article.status == "ANALYZED"


def test_process_new_articles_uses_full_content_over_summary_when_available(db_session, monkeypatch):
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    article = Article(
        source="test", url="https://example.com/a",
        title="US strikes Iran oil export sites", content="crude oil markets react",
        full_content="The full scraped article body, much richer than the summary.",
        full_content_fetch_attempted_at=pipeline_module.utcnow(),
    )
    db_session.add(article)
    db_session.commit()

    fake_output = AnalysisOutput(
        category="oil_gas",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
            key_points=["Crude eases"], confidence_score=85, time_horizon="Short-Term",
        )],
    )
    captured = {}
    def fake_analyze(client, title, content):
        captured["content"] = content
        return fake_output
    monkeypatch.setattr(pipeline_module, "analyze_article", fake_analyze)

    process_new_articles(db_session, claude_client=object())

    assert captured["content"] == "The full scraped article body, much richer than the summary."


def test_process_new_articles_passes_the_same_client_to_the_filter(db_session, monkeypatch):
    article = Article(
        source="test", url="https://example.com/a", title="t", content="c",
    )
    db_session.add(article)
    db_session.commit()

    sentinel_client = object()
    captured = {}
    def fake_filter(session, client, throttle_seconds=0):
        captured["client"] = client
    monkeypatch.setattr(pipeline_module, "filter_new_articles", fake_filter)

    process_new_articles(db_session, claude_client=sentinel_client)

    assert captured["client"] is sentinel_client


def test_process_new_articles_coerces_an_out_of_taxonomy_category_to_other(db_session, monkeypatch):
    # The tool schema constrains `category` to CATEGORIES, but that's a
    # request-time hint to the LLM, not a guarantee -- a provider that
    # doesn't strictly enforce JSON-schema enums could still return
    # something else (in the real incident this fix addresses, a full
    # sentence used as a "category", which broke the feed card's badge
    # layout). _persist_alert must coerce any such value to "other" rather
    # than persisting it verbatim.
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    article = Article(
        source="test", url="https://example.com/bad-category",
        title="US strikes Iran oil export sites", content="crude oil markets react",
    )
    db_session.add(article)
    db_session.commit()

    fake_output = AnalysisOutput(
        category="Indian IT sector rally driven by Tech Mahindra Q1 beat and HCL",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="x",
            time_horizon="Short-Term",
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)

    created = process_new_articles(db_session, claude_client=object())

    assert created == 1
    alert = db_session.query(Alert).one()
    assert alert.category == "other"
    refreshed_article = db_session.query(Article).filter_by(id=article.id).one()
    assert refreshed_article.category == "other"


def test_process_new_articles_uses_calibrated_magnitude_when_enough_samples(db_session, monkeypatch):
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    # 5 samples of [1, 2, 3, 4, 5] for (oil_gas, this company) -> mean = 3.0, pstdev = sqrt(2).
    for i, actual in enumerate([1.0, 2.0, 3.0, 4.0, 5.0]):
        db_session.add(CalibrationSample(
            alert_company_id=i + 1, category="oil_gas", company_id=company.id,
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
        category="oil_gas",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
            confidence_score=85, time_horizon="Short-Term",
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
        category="oil_gas",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
            confidence_score=85, time_horizon="Short-Term",
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
        category="oil_gas",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
            key_points=["Crude eases", "Refining margins widen"],
            confidence_score=85, time_horizon="Short-Term",
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
    assert alerts[0].category == alerts[1].category == "oil_gas"

    first_ac = db_session.query(AlertCompany).filter_by(alert_id=alerts[0].id).one()
    second_ac = db_session.query(AlertCompany).filter_by(alert_id=alerts[1].id).one()
    assert second_ac.company_id == first_ac.company_id
    assert second_ac.direction == first_ac.direction
    assert second_ac.rationale == first_ac.rationale
    assert second_ac.basis == first_ac.basis
    assert pipeline_module.decode_key_points(second_ac) == pipeline_module.decode_key_points(first_ac)
    assert pipeline_module.decode_key_points(first_ac) == ["Crude eases", "Refining margins widen"]

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
        category="oil_gas",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
            confidence_score=85, time_horizon="Short-Term",
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

    def fake_filter(session, client, throttle_seconds=0):
        # Mark the article as FILTERED so it's not analyzed
        for article in session.query(Article).filter_by(status="NEW").all():
            article.status = "FILTERED"
        session.commit()

    monkeypatch.setattr(pipeline_module, "filter_new_articles", fake_filter)
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: (_ for _ in ()).throw(AssertionError("should not be called")))

    created = process_new_articles(db_session, claude_client=object())

    assert created == 0
    refreshed = db_session.query(Article).filter_by(id=irrelevant.id).one()
    assert refreshed.status == "FILTERED"


def test_alert_broadcast_payload_includes_sector(db_session):
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    article = Article(source="test", url="https://example.com/broadcast-sector", title="Sector broadcast test")
    db_session.add(article)
    db_session.commit()

    alert = Alert(article_id=article.id, category="oil_gas", event_type="crude_oil")
    db_session.add(alert)
    db_session.commit()

    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin",
        basis="direct_mention", confidence="llm_estimate",
        confidence_contributors_json='["c"]',
        confidence_penalties_json='[]',
    ))
    db_session.commit()
    db_session.refresh(alert)

    payload = pipeline_module._alert_broadcast_payload(db_session, alert)

    assert payload["event_type"] == "crude_oil"
    assert payload["companies"][0]["sector"] == "oil_gas"
    assert payload["companies"][0]["confidence_contributors"] == ["c"]
    assert payload["companies"][0]["confidence_penalties"] == []


def test_alert_broadcast_payload_uses_one_query_for_past_mentions_across_all_companies(db_session):
    companies = [
        Company(ticker=f"CO{i}.NS", name=f"Company {i}", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
        for i in range(4)
    ]
    db_session.add_all(companies)
    db_session.commit()

    article = Article(source="test", url="https://example.com/broadcast-query-count", title="Query count test")
    db_session.add(article)
    db_session.commit()

    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.commit()

    for company in companies:
        db_session.add(AlertCompany(
            alert_id=alert.id, company_id=company.id, direction="bullish",
            magnitude_low=2.0, magnitude_high=4.0, rationale="x",
            basis="direct_mention", confidence="llm_estimate",
        ))
    db_session.commit()
    db_session.refresh(alert)

    past_mentions_queries = 0

    def _count(conn, cursor, statement, params, context, executemany):
        nonlocal past_mentions_queries
        if "alert_companies" in statement and "alerts" in statement and "articles" in statement:
            past_mentions_queries += 1

    event.listen(db_session.get_bind(), "before_cursor_execute", _count)
    try:
        payload = pipeline_module._alert_broadcast_payload(db_session, alert)
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", _count)

    assert len(payload["companies"]) == 4
    # One bulk query for all 4 companies' past-mentions history, not one
    # query per company (the get_past_mentions-per-company pattern this
    # replaces).
    assert past_mentions_queries == 1


def test_sector_inference_fan_out_copies_confidence_and_horizon_to_every_row(db_session, monkeypatch):
    for ticker, tier in [("A.NS", "NIFTY50"), ("B.NS", "NIFTYNEXT50")]:
        db_session.add(Company(ticker=ticker, name=ticker, sector="oil_gas", index_tier=tier, market_cap=1.0))
    db_session.commit()

    article = Article(source="test", url="https://example.com/b", title="Oil sector news", content="x")
    db_session.add(article)
    db_session.commit()

    fake_output = AnalysisOutput(
        category="oil_gas",
        companies=[CompanyMention(
            name="oil sector", ticker=None, is_direct=False, sector="oil_gas",
            direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="sector-wide tailwind",
            key_points=[], confidence_score=55, time_horizon="Medium-Term",
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)

    process_new_articles(db_session, claude_client=object())

    alert = db_session.query(Alert).one()
    rows = db_session.query(AlertCompany).filter_by(alert_id=alert.id).all()
    assert len(rows) == 2
    # Same reasoning as above -- the Confidence Engine, not the LLM,
    # produces confidence_score now.
    assert all(0 <= r.confidence_score <= 100 for r in rows)
    assert all(r.time_horizon == "Medium-Term" for r in rows)


def test_process_new_articles_persists_evidence_discipline_fields(db_session, monkeypatch):
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    article = Article(
        source="test", url="https://example.com/evidence",
        title="Oil prices spike", content="crude oil markets react",
    )
    db_session.add(article)
    db_session.commit()

    fake_output = AnalysisOutput(
        category="oil_gas", event_type="crude_oil",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
            time_horizon="Short-Term",
            reasons=["Refining margins widen on crude spike."],
            evidence_refs=["RULE_CRUDE_OIL_UP"],
            risks=["Margin reversal if crude falls back."],
            assumptions=["Crude stays elevated."],
            unknowns=["Duration of the spike."],
            alternative_hypothesis="Already priced in.",
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)

    created = process_new_articles(db_session, claude_client=object())
    assert created == 1

    alert = db_session.query(Alert).one()
    assert alert.event_type == "crude_oil"
    assert alert.prompt_version is not None
    assert alert.knowledge_version is not None

    ac = db_session.query(AlertCompany).one()
    assert pipeline_module._decode_json_list(ac.reasons_json) == ["Refining margins widen on crude spike."]
    assert pipeline_module._decode_json_list(ac.evidence_refs_json) == ["RULE_CRUDE_OIL_UP"]
    assert pipeline_module._decode_json_list(ac.rulebook_ids_json) == ["RULE_CRUDE_OIL_UP"]
    assert ac.alternative_hypothesis == "Already priced in."
    assert ac.confidence_band in {"LOW", "MODERATE", "HIGH", "VERY_HIGH"}
    assert pipeline_module._decode_json_list(ac.confidence_contributors_json) != [] or pipeline_module._decode_json_list(ac.confidence_penalties_json) != []


def test_process_new_articles_reuse_path_carries_evidence_fields(db_session, monkeypatch):
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    first = Article(source="source-a", url="https://example.com/reuse-first", title="Oil prices spike", content="x")
    second = Article(source="source-b", url="https://example.com/reuse-second", title="  OIL PRICES   spike  ", content="x, wire copy")
    db_session.add_all([first, second])
    db_session.commit()

    fake_output = AnalysisOutput(
        category="oil_gas", event_type="crude_oil",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
            time_horizon="Short-Term",
            reasons=["Refining margins widen."], evidence_refs=["RULE_CRUDE_OIL_UP"],
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)

    created = process_new_articles(db_session, claude_client=object())
    assert created == 2

    alerts = db_session.query(Alert).order_by(Alert.id).all()
    assert alerts[0].event_type == alerts[1].event_type == "crude_oil"

    acs = db_session.query(AlertCompany).order_by(AlertCompany.id).all()
    assert pipeline_module._decode_json_list(acs[0].reasons_json) == pipeline_module._decode_json_list(acs[1].reasons_json)


def test_process_new_articles_persists_financial_snapshot_and_contradiction(db_session, monkeypatch):
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    article = Article(
        source="test", url="https://example.com/financial-context",
        title="Oil prices spike", content="crude oil markets react",
    )
    db_session.add(article)
    db_session.commit()

    fake_output = AnalysisOutput(
        category="oil_gas", event_type="crude_oil",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
            time_horizon="Short-Term", reasons=["Refining margins widen."], evidence_refs=[],
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)
    monkeypatch.setattr(
        pipeline_module, "get_or_fetch_financial_snapshot",
        lambda session, ticker: {"price": 2500.0, "return_1m": -12.0, "return_3m": -20.0},
    )

    created = process_new_articles(db_session, claude_client=object())
    assert created == 1

    ac = db_session.query(AlertCompany).one()
    assert ac.price_at_analysis == 2500.0
    assert ac.return_1m == -12.0
    assert ac.return_3m == -20.0
    # Bullish call + -12% over a month (past the 5% threshold) -> a real contradiction.
    assert ac.contradiction_note is not None
    assert "bullish" in ac.contradiction_note.lower()
    assert ac.confidence_band in {"LOW", "MODERATE", "HIGH", "VERY_HIGH"}


def test_process_new_articles_no_contradiction_when_snapshot_unavailable(db_session, monkeypatch):
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()
    article = Article(
        source="test", url="https://example.com/financial-context-none",
        title="Oil prices spike", content="crude oil markets react",
    )
    db_session.add(article)
    db_session.commit()

    fake_output = AnalysisOutput(
        category="oil_gas",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="x",
            time_horizon="Short-Term",
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)
    monkeypatch.setattr(pipeline_module, "get_or_fetch_financial_snapshot", lambda session, ticker: None)

    created = process_new_articles(db_session, claude_client=object())
    assert created == 1

    ac = db_session.query(AlertCompany).one()
    assert ac.price_at_analysis is None
    assert ac.return_1m is None
    assert ac.contradiction_note is None


def test_process_new_articles_persists_indirect_impact_chain_with_decayed_confidence(db_session, monkeypatch):
    direct = Company(ticker="NVDA.NS", name="Nvidia", sector="it", index_tier="NIFTY50", market_cap=1.0)
    supplier = Company(ticker="TSM.NS", name="TSMC", sector="it", index_tier="NIFTY50", market_cap=1.0)
    db_session.add_all([direct, supplier])
    db_session.commit()

    article = Article(
        source="test", url="https://example.com/indirect-impact",
        title="Chip export ban", content="US restricts advanced chip exports",
    )
    db_session.add(article)
    db_session.commit()

    fake_output = AnalysisOutput(
        category="it", event_type="other",
        companies=[
            CompanyMention(
                name="Nvidia", ticker="NVDA.NS", is_direct=True, sector=None,
                direction="bearish", magnitude_low=2.0, magnitude_high=4.0, rationale="export ban hits Nvidia directly",
                time_horizon="Short-Term", impact_level="direct",
            ),
            CompanyMention(
                name="TSMC", ticker="TSM.NS", is_direct=True, sector=None,
                direction="bearish", magnitude_low=1.0, magnitude_high=2.0,
                rationale="TSMC fabs Nvidia's chips; lower Nvidia orders reduce TSMC's foundry revenue.",
                time_horizon="Medium-Term", impact_level="indirect_l1", parent_ticker="NVDA.NS",
            ),
        ],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)
    monkeypatch.setattr(pipeline_module, "get_or_fetch_financial_snapshot", lambda session, ticker: None)

    created = process_new_articles(db_session, claude_client=object())
    assert created == 1

    direct_ac = db_session.query(AlertCompany).filter_by(company_id=direct.id).one()
    indirect_ac = db_session.query(AlertCompany).filter_by(company_id=supplier.id).one()

    assert direct_ac.impact_level == "direct"
    assert direct_ac.parent_company_id is None
    assert indirect_ac.impact_level == "indirect_l1"
    assert indirect_ac.parent_company_id == direct.id
    # Same underlying evidence/calibration signal, but the indirect entry's
    # confidence must be strictly discounted relative to the direct one.
    assert indirect_ac.confidence_score < direct_ac.confidence_score


def test_process_new_articles_reuse_path_carries_impact_level_and_parent(db_session, monkeypatch):
    direct = Company(ticker="NVDA.NS", name="Nvidia", sector="it", index_tier="NIFTY50", market_cap=1.0)
    supplier = Company(ticker="TSM.NS", name="TSMC", sector="it", index_tier="NIFTY50", market_cap=1.0)
    db_session.add_all([direct, supplier])
    db_session.commit()

    older_article = Article(source="test", url="https://example.com/indirect-a", title="Chip export ban announced")
    db_session.add(older_article)
    db_session.commit()

    fake_output = AnalysisOutput(
        category="it",
        companies=[
            CompanyMention(
                name="Nvidia", ticker="NVDA.NS", is_direct=True, sector=None,
                direction="bearish", magnitude_low=2.0, magnitude_high=4.0, rationale="export ban",
                time_horizon="Short-Term", impact_level="direct",
            ),
            CompanyMention(
                name="TSMC", ticker="TSM.NS", is_direct=True, sector=None,
                direction="bearish", magnitude_low=1.0, magnitude_high=2.0, rationale="fabs Nvidia chips",
                time_horizon="Medium-Term", impact_level="indirect_l1", parent_ticker="NVDA.NS",
            ),
        ],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)
    monkeypatch.setattr(pipeline_module, "get_or_fetch_financial_snapshot", lambda session, ticker: None)
    assert process_new_articles(db_session, claude_client=object()) == 1

    # Same normalized title -> dedup-reuse path, no second analyze_article call.
    newer_article = Article(source="test", url="https://example.com/indirect-b", title="Chip export ban announced")
    db_session.add(newer_article)
    db_session.commit()
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: (_ for _ in ()).throw(AssertionError("should not be called")))
    assert process_new_articles(db_session, claude_client=object()) == 1

    reused_indirect = (
        db_session.query(AlertCompany)
        .filter_by(company_id=supplier.id, alert_id=newer_article.alerts[0].id)
        .one()
    )
    assert reused_indirect.impact_level == "indirect_l1"
    assert reused_indirect.parent_company_id == direct.id


def test_process_new_articles_analysis_cache_deterministic(db_session, monkeypatch):
    """Same content -> the LLM is called at most once; a second article
    with byte-identical (title, content) reuses the cached output instead
    of calling analyze_article again, even if analyze_article would have
    returned something different on a second call."""
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    article1 = Article(source="test", url="https://example.com/a1", title="Crude oil spikes", content="Oil prices jump 5%.")
    article2 = Article(source="test", url="https://example.com/a2", title="Crude oil spikes", content="Oil prices jump 5%.")
    db_session.add_all([article1, article2])
    db_session.commit()

    call_count = {"n": 0}
    outputs = [
        AnalysisOutput(category="oil_gas", companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
            key_points=["Crude eases"], time_horizon="Short-Term",
        )]),
        AnalysisOutput(category="other", companies=[]),  # DIFFERENT output -- must never be reached
    ]

    def fake_analyze(client, title, content):
        result = outputs[call_count["n"]]
        call_count["n"] += 1
        return result

    monkeypatch.setattr(pipeline_module, "analyze_article", fake_analyze)

    created = process_new_articles(db_session, claude_client=object())

    assert created == 2
    assert call_count["n"] == 1  # second article hit the cache, never called analyze_article again

    alerts = db_session.query(Alert).order_by(Alert.id).all()
    assert alerts[0].category == "oil_gas"
    assert alerts[1].category == "oil_gas"  # cached output, NOT the second scripted "other" output
    assert len(alerts[0].companies) == 1
    assert len(alerts[1].companies) == 1


def test_get_cached_analysis_returns_none_on_miss(db_session):
    article = Article(source="test", url="https://example.com/miss", title="t", content="c")
    db_session.add(article)
    db_session.commit()

    assert pipeline_module.get_cached_analysis(db_session, article) is None


def test_store_then_get_cached_analysis_round_trips(db_session):
    article = Article(source="test", url="https://example.com/rt", title="t", content="c")
    db_session.add(article)
    db_session.commit()

    output = AnalysisOutput(category="oil_gas", companies=[])
    pipeline_module.store_analysis_cache(db_session, article, output)
    db_session.commit()

    cached = pipeline_module.get_cached_analysis(db_session, article)
    assert cached is not None
    assert cached.category == "oil_gas"


def test_clear_analysis_cache_removes_the_row(db_session):
    article = Article(source="test", url="https://example.com/clr", title="t", content="c")
    db_session.add(article)
    db_session.commit()

    pipeline_module.store_analysis_cache(db_session, article, AnalysisOutput(category="oil_gas", companies=[]))
    db_session.commit()
    assert pipeline_module.get_cached_analysis(db_session, article) is not None

    pipeline_module.clear_analysis_cache(db_session, article)
    db_session.commit()
    assert pipeline_module.get_cached_analysis(db_session, article) is None
