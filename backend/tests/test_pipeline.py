import json

import pytest
from sqlalchemy import event

import app.pipeline as pipeline_module
from app.analysis.impact_graph.schemas import GraphCompany, GraphEdge, ImpactGraphResult
from app.analysis.schemas import AnalysisOutput, CompanyMention
from app.models import (
    Alert,
    AlertCompany,
    Article,
    CalibrationSample,
    CascadeGap,
    Company,
    EmailNotification,
    Holding,
    ImpactEdge,
    User,
)
from app.pipeline import _persist_alert, decode_key_points, process_new_articles


def _article(session):
    article = Article(
        source="test", url="https://example.com/confidence-floor",
        title="Confidence floor test article", content="c",
    )
    session.add(article)
    session.commit()
    return article


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

    fake_output = ImpactGraphResult(
        category="oil_gas",
        companies=[GraphCompany(
            ticker="RELIANCE.NS", name="Reliance Industries", direction="bullish",
            impact_strength=0.6, confidence=0.7, materiality=0.6, causal_distance=1,
            time_horizon="Short-Term", mechanism="test mechanism", rationale="refiner margin up",
            key_points=["Crude eases", "Refining margins widen"], reasons=["r1"],
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article_v3", lambda router, title, content, session=None, article_id=None: fake_output)

    created = process_new_articles(db_session, claude_client=object())

    assert created == 1
    alert = db_session.query(Alert).one()
    assert alert.category == "oil_gas"

    alert_companies = db_session.query(AlertCompany).filter_by(alert_id=alert.id).all()
    assert len(alert_companies) == 1
    assert alert_companies[0].company_id == company.id
    # No calibration samples exist, so the alert falls back to the LLM's own estimate.
    assert alert_companies[0].confidence == "llm_estimate"
    # v3 derives the band from impact_strength: high = round(0.5 + 4.5*0.6, 1)
    # = 3.2, low = round(max(0.1, 3.2/3), 1) = 1.1.
    assert alert_companies[0].magnitude_low == 1.1
    assert alert_companies[0].magnitude_high == 3.2
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


def test_process_new_articles_reconciles_direction_to_measured_move(db_session, monkeypatch):
    from app.models import MarketMove, utcnow

    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    article = Article(
        source="test", url="https://example.com/a",
        title="US strikes Iran oil export sites", content="crude oil markets react",
    )
    db_session.add(article)
    db_session.commit()

    fake_output = ImpactGraphResult(
        category="oil_gas",
        companies=[GraphCompany(
            ticker="RELIANCE.NS", name="Reliance Industries", direction="bullish",
            impact_strength=0.6, confidence=0.7, materiality=0.6, causal_distance=1,
            time_horizon="Short-Term", mechanism="test mechanism", rationale="refiner margin up",
            key_points=["Crude eases", "Refining margins widen"], reasons=["r1"],
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article_v3", lambda router, title, content, session=None, article_id=None: fake_output)

    # The LLM guessed "bullish" before the market had reacted. The real,
    # measured move went the other way -- persisted direction must defer
    # to the measured fact, not the pre-measurement LLM guess.
    def fake_measure(session, company_obj, **kwargs):
        return MarketMove(
            company_id=company_obj.id, benchmark_ticker="^NSEI",
            measurement_status="ok", excess_move_pct=-3.1, measured_at=utcnow(),
        )

    monkeypatch.setattr(pipeline_module, "measure_company_move", fake_measure)

    created = process_new_articles(db_session, claude_client=object())

    assert created == 1
    alert_company = db_session.query(AlertCompany).one()
    assert alert_company.direction == "bearish"


def test_process_new_articles_keeps_llm_direction_when_unmeasured(db_session, monkeypatch):
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    article = Article(
        source="test", url="https://example.com/a",
        title="US strikes Iran oil export sites", content="crude oil markets react",
    )
    db_session.add(article)
    db_session.commit()

    fake_output = ImpactGraphResult(
        category="oil_gas",
        companies=[GraphCompany(
            ticker="RELIANCE.NS", name="Reliance Industries", direction="bullish",
            impact_strength=0.6, confidence=0.7, materiality=0.6, causal_distance=1,
            time_horizon="Short-Term", mechanism="test mechanism", rationale="refiner margin up",
            key_points=["Crude eases", "Refining margins widen"], reasons=["r1"],
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article_v3", lambda router, title, content, session=None, article_id=None: fake_output)
    # measure_company_move stays on conftest's autouse "no_data" stub.

    created = process_new_articles(db_session, claude_client=object())

    assert created == 1
    alert_company = db_session.query(AlertCompany).one()
    assert alert_company.direction == "bullish"


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

    fake_output = ImpactGraphResult(
        category="oil_gas",
        companies=[GraphCompany(
            ticker="RELIANCE.NS", name="Reliance Industries", direction="bullish",
            impact_strength=0.6, confidence=0.7, materiality=0.6, causal_distance=1,
            time_horizon="Short-Term", mechanism="test mechanism", rationale="refiner margin up",
            key_points=["Crude eases"], reasons=["r1"],
        )],
    )
    captured = {}
    def fake_analyze(router, title, content, session=None, article_id=None):
        captured["content"] = content
        return fake_output
    monkeypatch.setattr(pipeline_module, "analyze_article_v3", fake_analyze)

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

    fake_output = ImpactGraphResult(
        category="Indian IT sector rally driven by Tech Mahindra Q1 beat and HCL",
        companies=[GraphCompany(
            ticker="RELIANCE.NS", name="Reliance Industries", direction="bullish",
            impact_strength=0.3, confidence=0.5, materiality=0.3, causal_distance=1,
            time_horizon="Short-Term", mechanism="test mechanism", rationale="x",
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article_v3", lambda router, title, content, session=None, article_id=None: fake_output)

    created = process_new_articles(db_session, claude_client=object())

    assert created == 1
    alert = db_session.query(Alert).one()
    assert alert.category == "other"
    refreshed_article = db_session.query(Article).filter_by(id=article.id).one()
    assert refreshed_article.category == "other"


def test_process_new_articles_never_uses_calibrated_magnitude_despite_enough_samples(db_session, monkeypatch):
    """Realized-outcome CalibrationSample stats must never override the
    deterministic, impact_strength-derived magnitude -- see
    docs/superpowers/sdd/2026-08-13-newsflo-corrective-v4/task-3-brief.md.
    This is the exact scenario that USED to trigger a calibration blend
    (>=5 samples for the same category/company); it must now be a no-op."""
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    # 5 samples of [1, 2, 3, 4, 5] for (oil_gas, this company) -- would have
    # blended to mean=3.0, pstdev=sqrt(2) under the old, now-removed path.
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

    fake_output = ImpactGraphResult(
        category="oil_gas",
        companies=[GraphCompany(
            ticker="RELIANCE.NS", name="Reliance Industries", direction="bullish",
            impact_strength=0.6, confidence=0.7, materiality=0.6, causal_distance=1,
            time_horizon="Short-Term", mechanism="test mechanism", rationale="refiner margin up",
            reasons=["r1"],
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article_v3", lambda router, title, content, session=None, article_id=None: fake_output)

    created = process_new_articles(db_session, claude_client=object())
    assert created == 1

    ac = db_session.query(AlertCompany).one()
    assert ac.confidence == "llm_estimate"
    # Deterministic formula from impact_strength (see _v3_entries):
    # high = round(0.5 + 4.5*0.6, 1) = 3.2, low = round(max(0.1, 3.2/3), 1) = 1.1.
    # NOT the calibration blend's mean=3.0 +/- pstdev=sqrt(2).
    assert ac.magnitude_low == pytest.approx(1.1)
    assert ac.magnitude_high == pytest.approx(3.2)


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

    fake_output = ImpactGraphResult(
        category="oil_gas",
        companies=[GraphCompany(
            ticker="RELIANCE.NS", name="Reliance Industries", direction="bullish",
            impact_strength=0.6, confidence=0.7, materiality=0.6, causal_distance=1,
            time_horizon="Short-Term", mechanism="test mechanism", rationale="refiner margin up",
            reasons=["r1"],
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article_v3", lambda router, title, content, session=None, article_id=None: fake_output)

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

    def boom(router, title, content, session=None, article_id=None):
        raise RuntimeError("api down")

    monkeypatch.setattr(pipeline_module, "analyze_article_v3", boom)

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
    #
    # Corrective-v4 Task 12: reuse now requires the prior alert to be fully
    # gate-authoritative (see app.pipeline._dedup_reuse_policy_allows), so
    # this runs under strict mode with a mocked publication gate that
    # accepts the candidate -- a purely-legacy (ungated) prior alert no
    # longer qualifies for the reuse shortcut at all (see
    # test_sections_structural.py::test_dedup_reuse_cannot_bypass_gate).
    from app.analysis.impact_graph.publication_gate import GateDecision
    from app.config import settings

    monkeypatch.setattr(settings, "impact_engine_v4_strict", True)

    def fake_gate_candidates(session, result):
        return [
            ("ARTICLE_SUBJECT", "TIER1", [], GateDecision(
                final_state="DISPLAY_ELIGIBLE", display_tier="primary",
                gates_passed=["materiality"], rejection_reason=None,
                materiality_grade="HIGH", ticker=company.ticker, dedup_key=company.ticker,
            ))
            for company in result.companies
        ]
    monkeypatch.setattr(pipeline_module, "_gate_candidates", fake_gate_candidates)

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

    fake_output = ImpactGraphResult(
        category="oil_gas",
        companies=[GraphCompany(
            ticker="RELIANCE.NS", name="Reliance Industries", direction="bullish",
            impact_strength=0.6, confidence=0.7, materiality=0.6, causal_distance=1,
            time_horizon="Short-Term", mechanism="test mechanism", rationale="refiner margin up",
            key_points=["Crude eases", "Refining margins widen"], reasons=["r1"],
        )],
    )
    call_count = {"n": 0}

    def counting_analyze(router, title, content, session=None, article_id=None):
        call_count["n"] += 1
        return fake_output

    monkeypatch.setattr(pipeline_module, "analyze_article_v3", counting_analyze)

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

    fake_output = ImpactGraphResult(
        category="oil_gas",
        companies=[GraphCompany(
            ticker="RELIANCE.NS", name="Reliance Industries", direction="bullish",
            impact_strength=0.6, confidence=0.7, materiality=0.6, causal_distance=1,
            time_horizon="Short-Term", mechanism="test mechanism", rationale="refiner margin up",
            reasons=["r1"],
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article_v3", lambda router, title, content, session=None, article_id=None: fake_output)
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
    monkeypatch.setattr(pipeline_module, "analyze_article_v3", lambda router, title, content, session=None, article_id=None: (_ for _ in ()).throw(AssertionError("should not be called")))

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


@pytest.mark.skip(reason="legacy cascade fan-out path unwired by impact-graph v3 (2026-08-11)")
def test_sector_inference_fan_out_copies_confidence_and_horizon_to_every_row(db_session, monkeypatch):
    # A sector-wide fan-out mention now requires an anchor to return any
    # rows at all (resolve_companies no longer falls back to the whole
    # sector -- see app.companies.resolution's "no anchor -> no rows"
    # comment). ANCHOR.NS's own direct mention is what establishes the
    # "refining_marketing" anchor for the "oil_gas" fan-out below; A.NS and
    # B.NS share that sub_sector so they're what the fan-out actually
    # reaches. This keeps testing the original point of this test --
    # confidence_score/time_horizon get copied onto every fanned-out row --
    # without relying on the removed whole-sector fallback.
    db_session.add(Company(
        ticker="ANCHOR.NS", name="Anchor Oil Ltd.", sector="oil_gas", index_tier="NIFTY50",
        sub_sector="refining_marketing", market_cap=1.0,
    ))
    for ticker, tier in [("A.NS", "NIFTY50"), ("B.NS", "NIFTYNEXT50")]:
        db_session.add(Company(
            ticker=ticker, name=ticker, sector="oil_gas", index_tier=tier, market_cap=1.0,
            sub_sector="refining_marketing",
        ))
    db_session.commit()

    article = Article(source="test", url="https://example.com/b", title="Oil sector news", content="x")
    db_session.add(article)
    db_session.commit()

    fake_output = AnalysisOutput(
        category="oil_gas",
        companies=[
            CompanyMention(
                name="Anchor Oil Ltd.", ticker="ANCHOR.NS", is_direct=True, sector="oil_gas",
                direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="direct exposure",
                key_points=[], confidence_score=55, time_horizon="Medium-Term", impact_level="direct",
            ),
            CompanyMention(
                name="oil sector", ticker=None, is_direct=False, sector="oil_gas",
                direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="sector-wide tailwind",
                key_points=[], confidence_score=55, time_horizon="Medium-Term",
            ),
        ],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article_v3", lambda router, title, content, session=None, article_id=None: fake_output)

    process_new_articles(db_session, claude_client=object())

    alert = db_session.query(Alert).one()
    rows = db_session.query(AlertCompany).filter_by(alert_id=alert.id).all()
    # ANCHOR.NS (direct_mention) + A.NS/B.NS (sector_inference fan-out).
    assert len(rows) == 3
    fanout_tickers = {r.company.ticker for r in rows if r.basis == "sector_inference"}
    assert fanout_tickers == {"A.NS", "B.NS"}
    # Same reasoning as above -- the Confidence Engine, not the LLM,
    # produces confidence_score now.
    assert all(0 <= r.confidence_score <= 100 for r in rows)
    assert all(r.time_horizon == "Medium-Term" for r in rows)


@pytest.mark.skip(reason="legacy cascade fan-out path unwired by impact-graph v3 (2026-08-11)")
def test_process_new_articles_anchors_fan_out_to_the_named_companys_sub_sector(db_session, monkeypatch):
    # Models the reported production bug directly: a crude-oil story's fmcg
    # fan-out pulled in Eternal (food delivery, fmcg/retail) alongside HUL
    # (fmcg/personal_care) with no article-specific reason for Eternal at
    # all. process_new_articles must build the anchor_sub_sectors map from
    # the model's own direct mention (HUL, personal_care) and pass it
    # through to resolve_companies, so the sector-wide fan-out mention for
    # "fmcg" only reaches Dabur (also personal_care) and never Eternal
    # (retail) -- this is the one thing that actually excludes Eternal; if
    # app.pipeline's anchor-map construction were silently wrong (empty, or
    # keyed on the wrong field), fan-out would revert to whole-sector and
    # Eternal would come straight back with every other test still green.
    hul = Company(
        ticker="HINDUNILVR.NS", name="Hindustan Unilever Ltd.", sector="fmcg",
        sub_sector="personal_care", index_tier="NIFTY50", market_cap=1.0,
    )
    dabur = Company(
        ticker="DABUR.NS", name="Dabur India Ltd.", sector="fmcg",
        sub_sector="personal_care", index_tier="NIFTYNEXT50", market_cap=1.0,
    )
    eternal = Company(
        ticker="ETERNAL.NS", name="Eternal Ltd.", sector="fmcg",
        sub_sector="retail", index_tier="NIFTY50", market_cap=1.0,
    )
    db_session.add_all([hul, dabur, eternal])
    db_session.commit()

    article = Article(source="test", url="https://example.com/anchor-fanout", title="Crude oil spikes", content="x")
    db_session.add(article)
    db_session.commit()

    fake_output = AnalysisOutput(
        category="oil_gas", event_type="crude_oil",
        companies=[
            CompanyMention(
                name="Hindustan Unilever", ticker="HINDUNILVR.NS", is_direct=True, sector="fmcg",
                direction="bearish", magnitude_low=-2.0, magnitude_high=-1.0,
                rationale="Palm oil and packaging costs rise with crude.",
                key_points=[], confidence_score=60, time_horizon="Medium-Term",
                impact_level="direct",
            ),
            CompanyMention(
                name="fmcg sector", ticker=None, is_direct=False, sector="fmcg",
                direction="bearish", magnitude_low=1.0, magnitude_high=2.0,
                rationale="Sector-wide input cost exposure.",
                key_points=[], confidence_score=50, time_horizon="Medium-Term",
            ),
        ],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article_v3", lambda router, title, content, session=None, article_id=None: fake_output)

    process_new_articles(db_session, claude_client=object())

    alert = db_session.query(Alert).one()
    rows = db_session.query(AlertCompany).filter_by(alert_id=alert.id).all()
    resolved_tickers = {r.company.ticker for r in rows}

    assert resolved_tickers == {"HINDUNILVR.NS", "DABUR.NS"}
    assert "ETERNAL.NS" not in resolved_tickers


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

    fake_output = ImpactGraphResult(
        category="oil_gas", event_type="crude_oil",
        companies=[GraphCompany(
            ticker="RELIANCE.NS", name="Reliance Industries", direction="bullish",
            impact_strength=0.6, confidence=0.7, materiality=0.6, causal_distance=1,
            time_horizon="Short-Term", mechanism="test mechanism", rationale="refiner margin up",
            reasons=["Refining margins widen on crude spike."],
            evidence_refs=["RULE_CRUDE_OIL_UP"],
            assumptions=["Crude stays elevated."],
            unknowns=["Duration of the spike."],
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article_v3", lambda router, title, content, session=None, article_id=None: fake_output)

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
    # GraphCompany has no alternative_hypothesis field -- the v3 adapter
    # always persists None for it.
    assert ac.alternative_hypothesis is None
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

    fake_output = ImpactGraphResult(
        category="oil_gas", event_type="crude_oil",
        companies=[GraphCompany(
            ticker="RELIANCE.NS", name="Reliance Industries", direction="bullish",
            impact_strength=0.6, confidence=0.7, materiality=0.6, causal_distance=1,
            time_horizon="Short-Term", mechanism="test mechanism", rationale="refiner margin up",
            reasons=["Refining margins widen."], evidence_refs=["RULE_CRUDE_OIL_UP"],
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article_v3", lambda router, title, content, session=None, article_id=None: fake_output)

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

    fake_output = ImpactGraphResult(
        category="oil_gas", event_type="crude_oil",
        companies=[GraphCompany(
            ticker="RELIANCE.NS", name="Reliance Industries", direction="bullish",
            impact_strength=0.6, confidence=0.7, materiality=0.6, causal_distance=1,
            time_horizon="Short-Term", mechanism="test mechanism", rationale="refiner margin up",
            reasons=["Refining margins widen."],
            # A matched rule (plus the fully-cited claim) keeps this row's
            # confidence_score comfortably above CONFIDENCE_FLOOR -- the
            # price contradiction stubbed in below no longer affects
            # confidence_score at all (see
            # docs/superpowers/sdd/2026-08-13-newsflo-corrective-v4/
            # task-3-brief.md), so this is just an ordinary well-evidenced
            # row that happens to also carry a contradiction_note.
            evidence_refs=["RULE_CRUDE_OIL_UP"],
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article_v3", lambda router, title, content, session=None, article_id=None: fake_output)
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

    fake_output = ImpactGraphResult(
        category="oil_gas",
        companies=[GraphCompany(
            ticker="RELIANCE.NS", name="Reliance Industries", direction="bullish",
            impact_strength=0.6, confidence=0.7, materiality=0.6, causal_distance=1,
            time_horizon="Short-Term", mechanism="test mechanism", rationale="x",
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article_v3", lambda router, title, content, session=None, article_id=None: fake_output)
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

    fake_output = ImpactGraphResult(
        category="it", event_type="other",
        companies=[
            # Both companies carry a matched rule + fully-cited claim so their
            # baseline confidence_score clears CONFIDENCE_FLOOR even after
            # the indirect entry's 0.7x causal-distance discount below --
            # this test is about the discount being applied and being
            # strictly smaller than the direct entry's score, not about
            # the floor, so both rows must actually survive to be compared.
            GraphCompany(
                ticker="NVDA.NS", name="Nvidia", direction="bearish",
                impact_strength=0.6, confidence=0.7, materiality=0.6, causal_distance=1,
                time_horizon="Short-Term", mechanism="test mechanism",
                rationale="export ban hits Nvidia directly",
                reasons=["Export ban restricts chip shipments."], evidence_refs=["RULE_EXPORT_RESTRICTION"],
            ),
            GraphCompany(
                ticker="TSM.NS", name="TSMC", direction="bearish",
                impact_strength=0.4, confidence=0.6, materiality=0.4, causal_distance=2,
                time_horizon="Medium-Term", parent_type="company", parent_id="NVDA.NS",
                mechanism="test mechanism",
                rationale="TSMC fabs Nvidia's chips; lower Nvidia orders reduce TSMC's foundry revenue.",
                reasons=["Lower Nvidia orders reduce TSMC's foundry revenue."], evidence_refs=["RULE_EXPORT_RESTRICTION"],
            ),
        ],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article_v3", lambda router, title, content, session=None, article_id=None: fake_output)
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
    """Corrective-v4 Task 12: the dedup-reuse shortcut now only fires for a
    prior alert whose companies are ALL gate-authoritative (see
    app.pipeline._dedup_reuse_policy_allows), so this exercises the reuse
    path with strict mode on and a mocked publication gate that accepts
    both candidates -- a purely-legacy (ungated) prior alert no longer
    qualifies for reuse at all (see test_sections_structural.py::
    test_dedup_reuse_cannot_bypass_gate for that case). Also asserts the
    v4/gate fields (display_tier, gate_state) survive the copy, not just
    impact_level/parent_company_id."""
    from app.analysis.impact_graph.publication_gate import GateDecision
    from app.config import settings

    monkeypatch.setattr(settings, "impact_engine_v4_strict", True)

    def fake_gate_candidates(session, result):
        return [
            ("ARTICLE_SUBJECT", "TIER1", [], GateDecision(
                final_state="DISPLAY_ELIGIBLE", display_tier="primary",
                gates_passed=["materiality"], rejection_reason=None,
                materiality_grade="HIGH", ticker=company.ticker, dedup_key=company.ticker,
            ))
            for company in result.companies
        ]
    monkeypatch.setattr(pipeline_module, "_gate_candidates", fake_gate_candidates)

    direct = Company(ticker="NVDA.NS", name="Nvidia", sector="it", index_tier="NIFTY50", market_cap=1.0)
    supplier = Company(ticker="TSM.NS", name="TSMC", sector="it", index_tier="NIFTY50", market_cap=1.0)
    db_session.add_all([direct, supplier])
    db_session.commit()

    older_article = Article(source="test", url="https://example.com/indirect-a", title="Chip export ban announced")
    db_session.add(older_article)
    db_session.commit()

    fake_output = ImpactGraphResult(
        category="it",
        # analysis_quality defaults to "authoritative" -- required by the
        # reuse policy alongside the gate_state/analysis_version checks.
        companies=[
            # Matched rule + fully-cited claim on both, same reasoning as
            # test_process_new_articles_persists_indirect_impact_chain_with_decayed_confidence
            # above: keeps the indirect row's confidence_score above
            # CONFIDENCE_FLOOR after its 0.7x discount, so it survives to be
            # reused on the second (dedup) pass this test exercises.
            GraphCompany(
                ticker="NVDA.NS", name="Nvidia", direction="bearish",
                impact_strength=0.6, confidence=0.7, materiality=0.6, causal_distance=1,
                time_horizon="Short-Term", mechanism="test mechanism", rationale="export ban",
                reasons=["Export ban restricts chip shipments."], evidence_refs=["RULE_EXPORT_RESTRICTION"],
            ),
            GraphCompany(
                ticker="TSM.NS", name="TSMC", direction="bearish",
                impact_strength=0.4, confidence=0.6, materiality=0.4, causal_distance=2,
                time_horizon="Medium-Term", parent_type="company", parent_id="NVDA.NS",
                mechanism="test mechanism", rationale="fabs Nvidia chips",
                reasons=["Lower Nvidia orders reduce TSMC's foundry revenue."], evidence_refs=["RULE_EXPORT_RESTRICTION"],
            ),
        ],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article_v3", lambda router, title, content, session=None, article_id=None: fake_output)
    monkeypatch.setattr(pipeline_module, "get_or_fetch_financial_snapshot", lambda session, ticker: None)
    assert process_new_articles(db_session, claude_client=object()) == 1

    # Same normalized title -> dedup-reuse path, no second analyze_article call.
    newer_article = Article(source="test", url="https://example.com/indirect-b", title="Chip export ban announced")
    db_session.add(newer_article)
    db_session.commit()
    monkeypatch.setattr(pipeline_module, "analyze_article_v3", lambda router, title, content, session=None, article_id=None: (_ for _ in ()).throw(AssertionError("should not be called")))
    assert process_new_articles(db_session, claude_client=object()) == 1

    reused_indirect = (
        db_session.query(AlertCompany)
        .filter_by(company_id=supplier.id, alert_id=newer_article.alerts[0].id)
        .one()
    )
    assert reused_indirect.impact_level == "indirect_l1"
    assert reused_indirect.parent_company_id == direct.id
    # V4/gate fields carried through the copy verbatim, not dropped.
    assert reused_indirect.display_tier == "primary"
    assert reused_indirect.gate_state == "DISPLAY_ELIGIBLE"


def test_process_new_articles_reuse_copies_gate_audit_trail_honestly(db_session, monkeypatch):
    """Corrective-v4 Task 12 review round 2 (I2+I3): a reused alert's gate
    audit trail must be a COPY of the prior alert's real decision, not a
    freshly-fabricated CompanyDecisionRecord invented from the copied
    AlertCompany fields -- that would document a gate walk that never ran
    against this alert. Also pins that analysis_quality/analysis_provider
    carry through (transitively: a THIRD republish reuses off the SECOND
    alert, so its own quality mark must be honest, not NULL)."""
    from app.analysis.impact_graph.publication_gate import GateDecision
    from app.config import settings
    from app.models import CompanyDecisionRecord, EvidenceRecord

    monkeypatch.setattr(settings, "impact_engine_v4_strict", True)

    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    def fake_gate_candidates(session, result):
        return [
            ("ARTICLE_SUBJECT", "SUBJECT", [{
                "source_type": "article", "source_name": "article",
                "fact_text": "named subject of the article",
                "evidence_class": "ARTICLE_COMPANY_MENTION", "evidence_tier": "SUBJECT",
                "supports_claim": True,
            }], GateDecision(
                final_state="DISPLAY_ELIGIBLE", display_tier="primary",
                gates_passed=["materiality", "evidence"], rejection_reason=None,
                materiality_grade="HIGH", ticker=c.ticker, dedup_key=c.ticker,
            ))
            for c in result.companies
        ]
    monkeypatch.setattr(pipeline_module, "_gate_candidates", fake_gate_candidates)

    fake_output = ImpactGraphResult(
        category="oil_gas",
        companies=[GraphCompany(
            ticker="RELIANCE.NS", name="Reliance Industries", direction="bullish",
            impact_strength=0.6, confidence=0.7, materiality=0.6, causal_distance=1,
            time_horizon="Short-Term", mechanism="test mechanism", rationale="refiner margin up",
            reasons=["r1"],
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article_v3", lambda router, title, content, session=None, article_id=None: fake_output)
    monkeypatch.setattr(pipeline_module, "get_or_fetch_financial_snapshot", lambda session, ticker: None)

    first = Article(source="a", url="https://example.com/audit-first", title="Oil refining margins jump")
    db_session.add(first)
    db_session.commit()
    assert process_new_articles(db_session, claude_client=object()) == 1
    first_alert = first.alerts[0]
    assert first_alert.analysis_quality == "authoritative"  # ImpactGraphResult default

    original_decisions = (
        db_session.query(CompanyDecisionRecord).filter_by(alert_id=first_alert.id)
        .order_by(CompanyDecisionRecord.id).all()
    )
    original_evidence = (
        db_session.query(EvidenceRecord).filter_by(alert_id=first_alert.id)
        .order_by(EvidenceRecord.id).all()
    )
    assert len(original_decisions) == 1
    assert len(original_evidence) == 1

    # Second (republished) article -- same title, dedup-reuse path. No
    # second LLM call, so the gate never actually ran against this alert;
    # its audit trail must be a COPY, not a fresh synthesis.
    second = Article(source="b", url="https://example.com/audit-second", title="Oil refining margins jump")
    db_session.add(second)
    db_session.commit()
    monkeypatch.setattr(pipeline_module, "analyze_article_v3", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")))
    assert process_new_articles(db_session, claude_client=object()) == 1
    second_alert = second.alerts[0]

    assert second_alert.analysis_quality == "authoritative"
    assert second_alert.analysis_provider == first_alert.analysis_provider

    copied_decisions = (
        db_session.query(CompanyDecisionRecord).filter_by(alert_id=second_alert.id)
        .order_by(CompanyDecisionRecord.id).all()
    )
    copied_evidence = (
        db_session.query(EvidenceRecord).filter_by(alert_id=second_alert.id)
        .order_by(EvidenceRecord.id).all()
    )
    assert len(copied_decisions) == 1
    assert len(copied_evidence) == 1
    # New rows (different ids), same content.
    assert copied_evidence[0].id != original_evidence[0].id
    assert copied_evidence[0].fact_text == original_evidence[0].fact_text
    assert copied_evidence[0].evidence_class == original_evidence[0].evidence_class
    assert copied_evidence[0].evidence_tier == original_evidence[0].evidence_tier

    orig_d, copy_d = original_decisions[0], copied_decisions[0]
    assert copy_d.id != orig_d.id
    assert copy_d.alert_id != orig_d.alert_id
    assert copy_d.final_state == orig_d.final_state
    assert copy_d.display_tier == orig_d.display_tier
    assert copy_d.rejection_reason == orig_d.rejection_reason
    assert copy_d.gates_passed_json == orig_d.gates_passed_json
    assert copy_d.evidence_class == orig_d.evidence_class
    assert copy_d.materiality_grade == orig_d.materiality_grade
    # analysis_version PRESERVED from the original gate run, not
    # regenerated -- the record describes the gate contract that actually
    # produced it.
    assert copy_d.analysis_version == orig_d.analysis_version

    # candidate_json's evidence_ids are REMAPPED to the copied evidence
    # row, never left pointing at another alert's evidence.
    orig_candidate = json.loads(orig_d.candidate_json)
    copy_candidate = json.loads(copy_d.candidate_json)
    assert orig_candidate["evidence_ids"] == [original_evidence[0].id]
    assert copy_candidate["evidence_ids"] == [copied_evidence[0].id]
    # Every other candidate_json field is unchanged content.
    for key in ("economic_effect", "causal_distance", "materiality", "confidence_f", "mechanism", "rationale"):
        assert copy_candidate[key] == orig_candidate[key]

    # Chain: a THIRD republish reuses off the SECOND (reused) alert -- its
    # own analysis_version/gate_state/analysis_quality must be complete
    # enough to satisfy _dedup_reuse_policy_allows for the next hop too.
    third = Article(source="c", url="https://example.com/audit-third", title="Oil refining margins jump")
    db_session.add(third)
    db_session.commit()
    assert process_new_articles(db_session, claude_client=object()) == 1
    third_alert = third.alerts[0]
    third_decisions = db_session.query(CompanyDecisionRecord).filter_by(alert_id=third_alert.id).all()
    assert len(third_decisions) == 1
    assert third_decisions[0].analysis_version == orig_d.analysis_version


def test_process_new_articles_cache_hit_skips_llm_call_and_throttle_sleep(db_session, monkeypatch):
    """A single article whose content hash is already cached must never
    reach analyze_article or the retry loop's throttle sleep. This is a
    single-article test specifically so _find_reusable_alert (the
    unrelated, title-based dedup path in the same file) has no second
    same-titled article to match against -- it cannot be the explanation
    for any pass here, only the content-hash cache can be."""
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    # status="CATEGORIZED" (not the default "NEW") so filter_new_articles's
    # per-NEW-article loop -- which has its own unrelated throttle_seconds
    # sleep -- never touches this article. The only sleep call that could
    # occur is the one inside process_new_articles' own analyze/retry loop,
    # which a genuine cache hit must skip entirely.
    article = Article(
        source="test", url="https://example.com/cachehit", title="Crude oil spikes",
        content="Oil prices jump 5%.", status="CATEGORIZED",
    )
    db_session.add(article)
    db_session.commit()

    cached_output = ImpactGraphResult(category="oil_gas", companies=[GraphCompany(
        ticker="RELIANCE.NS", name="Reliance Industries", direction="bullish",
        impact_strength=0.6, confidence=0.7, materiality=0.6, causal_distance=1,
        time_horizon="Short-Term", mechanism="test mechanism", rationale="refiner margin up",
        key_points=["Crude eases"],
    )])
    pipeline_module.store_v3_cache(db_session, article, cached_output)
    db_session.commit()

    def fail_if_called(router, title, content, session=None, article_id=None):
        raise AssertionError("analyze_article_v3 must not be called on a cache hit")
    monkeypatch.setattr(pipeline_module, "analyze_article_v3", fail_if_called)

    sleep_calls = {"n": 0}
    monkeypatch.setattr(pipeline_module.time, "sleep", lambda s: sleep_calls.__setitem__("n", sleep_calls["n"] + 1))

    created = process_new_articles(db_session, claude_client=object(), throttle_seconds=5)

    assert created == 1
    assert sleep_calls["n"] == 0
    alert = db_session.query(Alert).one()
    assert alert.category == "oil_gas"
    assert len(alert.companies) == 1
    assert alert.companies[0].company_id == company.id
    assert alert.companies[0].direction == "bullish"
    refreshed_article = db_session.query(Article).filter_by(id=article.id).one()
    assert refreshed_article.status == "ANALYZED"


def test_process_new_articles_analysis_cache_deterministic(db_session, monkeypatch):
    """Same content -> the LLM is called at most once; a second, DIFFERENT
    article with byte-identical (title, content) reuses the cached output
    instead of calling analyze_article again, even if analyze_article would
    have returned something different on a second call.

    _find_reusable_alert (the unrelated, title-based dedup path) is
    explicitly neutralized here so this test can only pass via the
    content-hash cache, never via title dedup -- the two articles
    deliberately share a title (as a real republished-wire-story pair
    would), which would otherwise let dedup silently explain a pass here
    even with a completely broken cache.
    """
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    monkeypatch.setattr(pipeline_module, "_find_reusable_alert", lambda session, article: None)

    article1 = Article(source="test", url="https://example.com/a1", title="Crude oil spikes", content="Oil prices jump 5%.")
    article2 = Article(source="test", url="https://example.com/a2", title="Crude oil spikes", content="Oil prices jump 5%.")
    db_session.add_all([article1, article2])
    db_session.commit()

    call_count = {"n": 0}
    outputs = [
        ImpactGraphResult(category="oil_gas", companies=[GraphCompany(
            ticker="RELIANCE.NS", name="Reliance Industries", direction="bullish",
            impact_strength=0.6, confidence=0.7, materiality=0.6, causal_distance=1,
            time_horizon="Short-Term", mechanism="test mechanism", rationale="refiner margin up",
            key_points=["Crude eases"],
        )]),
        ImpactGraphResult(category="other", companies=[]),  # DIFFERENT output -- must never be reached
    ]

    def fake_analyze(router, title, content, session=None, article_id=None):
        result = outputs[call_count["n"]]
        call_count["n"] += 1
        return result

    monkeypatch.setattr(pipeline_module, "analyze_article_v3", fake_analyze)

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


def test_persist_alert_writes_cascade_gap_rows(db_session):
    article = Article(source="test", url="https://example.com/gap", title="t", content="c")
    db_session.add(article)
    db_session.commit()

    alert = pipeline_module._persist_alert(
        db_session, article, category="oil_gas", entries=[], event_type="crude_oil",
        gaps=[{"sector": "banking", "impact_level": "indirect_l1", "parent_ticker": None, "attempts": 2, "last_error": "boom"}],
    )

    gap_rows = db_session.query(CascadeGap).filter_by(alert_id=alert.id).all()
    assert len(gap_rows) == 1
    assert gap_rows[0].sector == "banking"
    assert gap_rows[0].impact_level == "indirect_l1"
    assert gap_rows[0].attempts == 2
    assert gap_rows[0].last_error == "boom"


def test_persist_alert_with_no_gaps_writes_no_gap_rows(db_session):
    article = Article(source="test", url="https://example.com/nogap", title="t", content="c")
    db_session.add(article)
    db_session.commit()

    alert = pipeline_module._persist_alert(db_session, article, category="oil_gas", entries=[], event_type="crude_oil")

    assert db_session.query(CascadeGap).filter_by(alert_id=alert.id).count() == 0


def test_persist_alert_writes_impact_edge_rows_resolving_company_tickers(db_session):
    company_a = Company(ticker="HDFCBANK.NS", name="HDFC Bank", sector="banking", index_tier="NIFTY50", market_cap=1.0)
    company_b = Company(ticker="MARUTI.NS", name="Maruti Suzuki", sector="auto", index_tier="NIFTY50", market_cap=1.0)
    db_session.add_all([company_a, company_b])
    db_session.commit()

    article = Article(source="test", url="https://example.com/edge1", title="t", content="c")
    db_session.add(article)
    db_session.commit()

    edges = [
        {
            "from": {"kind": "mechanism", "label": "Repo Rate ↓"},
            "to": {"kind": "sector", "label": "banking"},
            "relation": "credit_cost", "direction": "bullish", "note": "n1", "source": "rulebook_verified",
        },
        {
            "from": {"kind": "sector", "label": "banking"},
            "to": {"kind": "company", "label": "HDFCBANK.NS"},
            "relation": "demand", "direction": "bullish", "note": "n2", "source": "llm_only",
        },
        {
            "from": {"kind": "company", "label": "HDFCBANK.NS"},
            "to": {"kind": "company", "label": "MARUTI.NS"},
            "relation": "credit_cost", "direction": "bullish", "note": "n3", "source": "llm_only",
        },
        {
            # A ticker that doesn't resolve to any real Company -- must
            # still persist (with a null company_id), never dropped and
            # never crash.
            "from": {"kind": "company", "label": "NOTAREALTICKER.NS"},
            "to": {"kind": "sector", "label": "auto"},
            "relation": "competitor", "direction": "bearish", "note": "n4", "source": "llm_only",
        },
    ]

    alert = pipeline_module._persist_alert(
        db_session, article, category="banking", entries=[], event_type="repo_rate_change", edges=edges,
    )

    rows = db_session.query(ImpactEdge).filter_by(alert_id=alert.id).order_by(ImpactEdge.id).all()
    assert len(rows) == 4

    assert rows[0].from_node_kind == "mechanism"
    assert rows[0].from_company_id is None
    assert rows[0].to_node_kind == "sector"
    assert rows[0].to_company_id is None

    assert rows[1].from_node_kind == "sector"
    assert rows[1].to_node_kind == "company"
    assert rows[1].to_company_id == company_a.id

    assert rows[2].from_company_id == company_a.id
    assert rows[2].to_company_id == company_b.id
    assert rows[2].relation == "credit_cost"
    assert rows[2].source == "llm_only"

    assert rows[3].from_node_kind == "company"
    assert rows[3].from_label == "NOTAREALTICKER.NS"
    assert rows[3].from_company_id is None  # unresolved ticker -- kept, not dropped, no crash


def test_persist_alert_with_no_edges_writes_no_edge_rows(db_session):
    article = Article(source="test", url="https://example.com/edge2", title="t", content="c")
    db_session.add(article)
    db_session.commit()

    alert = pipeline_module._persist_alert(db_session, article, category="oil_gas", entries=[], event_type="crude_oil")

    assert db_session.query(ImpactEdge).filter_by(alert_id=alert.id).count() == 0


def test_process_new_articles_persists_edges_from_analysis(db_session, monkeypatch):
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    article = Article(source="test", url="https://example.com/edge3", title="t", content="c")
    db_session.add(article)
    db_session.commit()

    fake_output = ImpactGraphResult(
        category="oil_gas",
        companies=[GraphCompany(
            ticker="RELIANCE.NS", name="Reliance Industries", direction="bullish",
            impact_strength=0.6, confidence=0.7, materiality=0.6, causal_distance=1,
            time_horizon="Short-Term", mechanism="test mechanism", rationale="r",
            key_points=["k"],
        )],
        edges=[GraphEdge(
            parent_type="sector", parent_id="oil_gas", child_type="company", child_id="RELIANCE.NS",
            direction="bullish", mechanism="n", causal_distance=1,
            impact_strength=0.5, confidence=0.7, materiality=0.5,
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article_v3", lambda router, title, content, session=None, article_id=None: fake_output)

    process_new_articles(db_session, claude_client=object())

    alert = db_session.query(Alert).one()
    # 1 graph edge from result.edges + 1 attachment edge the pipeline appends
    # per company (parent node -> selected company).
    assert db_session.query(ImpactEdge).filter_by(alert_id=alert.id).count() == 2


from app.pipeline import CONFIDENCE_FLOOR


def test_entries_below_the_confidence_floor_are_not_persisted(db_session, monkeypatch):
    # compute_confidence is deterministic; force a below-floor score rather
    # than trying to construct inputs that happen to produce one.
    import app.pipeline as pipeline_module
    from app.reasoning.confidence import ConfidenceResult

    monkeypatch.setattr(
        pipeline_module, "compute_confidence",
        lambda **kwargs: ConfidenceResult(score=CONFIDENCE_FLOOR - 1, band="LOW"),
    )

    article = _article(db_session)
    company = Company(ticker="X.NS", name="X Ltd.", sector="other", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()

    alert = _persist_alert(db_session, article, "other", [{
        "company_id": company.id, "direction": "bullish",
        "magnitude_low": 1.0, "magnitude_high": 2.0, "rationale": "r",
        "key_points": [], "basis": "direct_mention", "time_horizon": "Short-Term",
        "impact_level": "direct",
    }])

    assert alert.companies == []


def test_entries_at_the_confidence_floor_are_persisted(db_session, monkeypatch):
    import app.pipeline as pipeline_module
    from app.reasoning.confidence import ConfidenceResult

    monkeypatch.setattr(
        pipeline_module, "compute_confidence",
        lambda **kwargs: ConfidenceResult(score=CONFIDENCE_FLOOR, band="MODERATE"),
    )

    article = _article(db_session)
    company = Company(ticker="X.NS", name="X Ltd.", sector="other", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()

    alert = _persist_alert(db_session, article, "other", [{
        "company_id": company.id, "direction": "bullish",
        "magnitude_low": 1.0, "magnitude_high": 2.0, "rationale": "r",
        "key_points": [], "basis": "direct_mention", "time_horizon": "Short-Term",
        "impact_level": "direct",
    }])

    assert len(alert.companies) == 1


def test_indirect_l2_row_clearing_the_floor_pre_multiplier_is_persisted_with_multiplied_score(db_session, monkeypatch):
    # Regression test for the CONFIDENCE_FLOOR / LEVEL_CONFIDENCE_MULTIPLIER
    # compounding bug: with calibration contributing 0.0 for nearly every
    # row, a typical pre-multiplier score (~69) survives the floor on its
    # own, but 69 * 0.45 (indirect_l2's multiplier) = 31 < CONFIDENCE_FLOOR
    # (40) -- so comparing the floor against the POST-multiplier value meant
    # no indirect_l2 row could ever be persisted, for any article. The floor
    # must be checked against the raw, pre-multiplier compute_confidence()
    # score; the persisted confidence_score must still carry the multiplier.
    import app.pipeline as pipeline_module
    from app.reasoning.confidence import ConfidenceResult

    # Exactly at the floor pre-multiplier -- passes the check.
    monkeypatch.setattr(
        pipeline_module, "compute_confidence",
        lambda **kwargs: ConfidenceResult(score=CONFIDENCE_FLOOR, band="MODERATE"),
    )

    article = _article(db_session)
    company = Company(ticker="X.NS", name="X Ltd.", sector="other", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()

    alert = _persist_alert(db_session, article, "other", [{
        "company_id": company.id, "direction": "bullish",
        "magnitude_low": 1.0, "magnitude_high": 2.0, "rationale": "r",
        "key_points": [], "basis": "direct_mention", "time_horizon": "Short-Term",
        "impact_level": "indirect_l2",
    }])

    assert len(alert.companies) == 1
    # Persisted value still carries the 0.45x indirect_l2 discount --
    # strictly below the floor, proving the floor gate itself used the
    # pre-multiplier score, not this one.
    expected_score = round(CONFIDENCE_FLOOR * pipeline_module.LEVEL_CONFIDENCE_MULTIPLIER["indirect_l2"])
    assert alert.companies[0].confidence_score == expected_score
    assert expected_score < CONFIDENCE_FLOOR


def test_indirect_l2_row_genuinely_failing_the_floor_pre_multiplier_is_dropped(db_session, monkeypatch):
    import app.pipeline as pipeline_module
    from app.reasoning.confidence import ConfidenceResult

    # Below the floor even before any multiplier is applied -- must still
    # be dropped, same as a direct row with the same raw score.
    monkeypatch.setattr(
        pipeline_module, "compute_confidence",
        lambda **kwargs: ConfidenceResult(score=CONFIDENCE_FLOOR - 1, band="LOW"),
    )

    article = _article(db_session)
    company = Company(ticker="X.NS", name="X Ltd.", sector="other", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()

    alert = _persist_alert(db_session, article, "other", [{
        "company_id": company.id, "direction": "bullish",
        "magnitude_low": 1.0, "magnitude_high": 2.0, "rationale": "r",
        "key_points": [], "basis": "direct_mention", "time_horizon": "Short-Term",
        "impact_level": "indirect_l2",
    }])

    assert alert.companies == []


def _stub_measurement(monkeypatch, excess_move_pct):
    """Monkeypatch app.pipeline.measure_company_move to return an "ok"
    MarketMove with the given excess_move_pct, for any company passed in.
    Mirrors the inline fake_measure pattern used by
    test_process_new_articles_reconciles_direction_to_measured_move above
    and by test_market_move_wiring.py."""
    from app.models import MarketMove, utcnow

    def fake_measure(session, company_obj, **kwargs):
        return MarketMove(
            company_id=company_obj.id, benchmark_ticker="^NSEI",
            measurement_status="ok", excess_move_pct=excess_move_pct, measured_at=utcnow(),
        )

    monkeypatch.setattr(pipeline_module, "measure_company_move", fake_measure)


def test_a_flipped_direction_clears_the_stale_rationale(db_session, monkeypatch):
    # The LLM called bullish; the measured move came back negative. The
    # rationale argues the bullish case and must not survive under a bearish
    # badge.
    article = _article(db_session)
    company = Company(ticker="X.NS", name="X Ltd.", sector="other", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()

    _stub_measurement(monkeypatch, excess_move_pct=-3.1)

    alert = _persist_alert(db_session, article, "other", [{
        "company_id": company.id, "direction": "bullish",
        "magnitude_low": 1.0, "magnitude_high": 2.0,
        "rationale": "This is clearly good news for the company.",
        "key_points": ["good news"], "basis": "direct_mention",
        "time_horizon": "Short-Term", "impact_level": "direct",
    }])

    ac = alert.companies[0]
    assert ac.direction == "bearish"
    assert ac.rationale is None
    assert decode_key_points(ac) == []


def test_a_confirmed_direction_keeps_its_rationale(db_session, monkeypatch):
    article = _article(db_session)
    company = Company(ticker="X.NS", name="X Ltd.", sector="other", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()

    _stub_measurement(monkeypatch, excess_move_pct=2.4)

    alert = _persist_alert(db_session, article, "other", [{
        "company_id": company.id, "direction": "bullish",
        "magnitude_low": 1.0, "magnitude_high": 2.0,
        "rationale": "This is clearly good news for the company.",
        "key_points": ["good news"], "basis": "direct_mention",
        "time_horizon": "Short-Term", "impact_level": "direct",
    }])

    assert alert.companies[0].rationale == "This is clearly good news for the company."


def test_market_moves_are_stamped_with_the_alert_category(db_session, monkeypatch):
    """Subsystem D reads market_moves.category, never a live join to
    alerts -- an alert recategorized later must not re-shuffle which range
    pool its historical measurements belong to."""
    from app.models import MarketMove

    article = _article(db_session)
    company = Company(ticker="X.NS", name="X Ltd.", sector="other", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()

    _stub_measurement(monkeypatch, excess_move_pct=2.4)

    alert = _persist_alert(db_session, article, "other", [{
        "company_id": company.id, "direction": "bullish",
        "magnitude_low": 1.0, "magnitude_high": 2.0,
        "rationale": "This is clearly good news for the company.",
        "key_points": ["good news"], "basis": "direct_mention",
        "time_horizon": "Short-Term", "impact_level": "direct",
    }])

    moves = db_session.query(MarketMove).all()
    assert moves, "persist path should have measured at least one company"
    assert all(m.category == alert.category for m in moves)


def test_a_company_with_every_optional_field_omitted_still_persists(db_session):
    """End-to-end guard on the schema change that made evidence_refs, risks,
    assumptions, unknowns and alternative_hypothesis OPTIONAL (see
    app.analysis.cascade._COMPANY_ITEM_REQUIRED -- dropped so the company
    prompt fits gpt-oss-20b's token ceiling).

    The dangerous path is not a crash, it is a silent DELETE: an empty
    evidence list used to zero both evidence-derived confidence components,
    putting the raw score under CONFIDENCE_FLOOR so _persist_alert dropped
    the row. Applied to every company of every alert, that is the same
    zero-companies outage the prompt work exists to fix. No monkeypatching
    here -- the real scorer must produce a keepable score.
    """
    article = _article(db_session)
    company = Company(ticker="OPT.NS", name="Optional Ltd.", sector="other", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()

    alert = _persist_alert(db_session, article, "other", [{
        "company_id": company.id, "direction": "bullish",
        "magnitude_low": 1.0, "magnitude_high": 2.0,
        "rationale": "Cheaper input costs lift its margin.",
        "key_points": ["It buys the thing that just got cheaper, so it keeps more of each sale."],
        "reasons": ["Input cost falls", "Pricing held", "Volume steady"],
        "basis": "direct_mention", "time_horizon": "Short-Term", "impact_level": "direct",
        # evidence_refs / risks / assumptions / unknowns /
        # alternative_hypothesis deliberately ABSENT, exactly as a model that
        # declines the now-optional fields would leave them.
    }])

    assert len(alert.companies) == 1
    persisted = alert.companies[0]
    assert persisted.company_id == company.id
    # Absent optional fields round-trip as empty, never as None-shaped JSON
    # the API serializers would choke on.
    import json as _json
    assert _json.loads(persisted.evidence_refs_json) == []
    assert _json.loads(persisted.risks_json) == []
    assert _json.loads(persisted.unknowns_json) == []
    assert _json.loads(persisted.assumptions_json) == []
    assert _json.loads(persisted.rulebook_ids_json) == []
    assert persisted.alternative_hypothesis is None
