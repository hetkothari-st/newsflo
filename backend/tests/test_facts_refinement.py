"""Phase 1 of the cost-optimization plan: refinement reasons from the
cascade's already-distilled `facts` string instead of re-reading (and
re-paying for) the raw article on all four of its calls.

These tests pin the two properties that make that safe: the facts really
do reach the refinement prompts (so the two layers share one evidence
base), and an alert with NO stored facts still refines off the article
text exactly as before (so nothing persisted pre-change loses its
refinement).
"""
import json
from types import SimpleNamespace

import app.pipeline as pipeline_module
from app.analysis.cascade import analyze_article
from app.analysis.refinement import refine_alert
from app.analysis.schemas import AnalysisOutput, CompanyMention
from app.models import Alert, AlertCompany, Article, Company, MarketMove, utcnow


class _RecordingClient:
    """Captures every prompt sent, and answers each tool call with a
    minimal valid payload so refine_alert runs end to end."""

    _ANSWERS = {
        "record_event_summary": {
            "summary_short": "Crude jumps after a supply outage",
            "summary_long": "A supply outage pushed crude prices up. Refiners face costlier input.",
            "is_unconfirmed": False,
        },
        "record_impact_whys": {"whys": [{"ticker": "RELIANCE.NS", "why": "Higher crude lifts this refiner's realisations."}]},
        "record_ripple_layers": {"layers": [
            {"title": "Winners — refiners", "relationship": "DIRECT", "note": "These gain on wider margins.",
             "tickers": ["RELIANCE.NS"]},
        ]},
        "record_timeline_effects": {"effects": [{"horizon": "TODAY", "description": "Energy names move first."}]},
    }

    def __init__(self):
        self.prompts = []

    class _Completions:
        def __init__(self, outer):
            self._outer = outer

        def create(self, **kwargs):
            self._outer.prompts.append("\n".join(m["content"] for m in kwargs["messages"]))
            name = kwargs["tool_choice"]["function"]["name"]
            tool_call = SimpleNamespace(function=SimpleNamespace(
                name=name, arguments=json.dumps(self._outer._ANSWERS[name]),
            ))
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[tool_call]))])

    @property
    def chat(self):
        return SimpleNamespace(completions=self._Completions(self))

    @property
    def user_prompts(self) -> str:
        return "\n".join(self.prompts)


FACTS = "An unplanned outage at a major producing field removed barrels from the market."
BODY = "UNIQUEBODYMARKER the full wire copy nobody downstream should have to re-read."


def _seed(db_session, facts):
    company = Company(ticker="RELIANCE.NS", name="Reliance", sector="oil_gas", index_tier="NIFTY50")
    article = Article(source="test", url="https://example.com/a", title="Oil jumps on outage", content=BODY)
    db_session.add_all([company, article])
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_gas", facts=facts)
    db_session.add(alert)
    db_session.flush()
    alert_company = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish", magnitude_low=1.0,
        magnitude_high=3.0, rationale="refiner", basis="direct_mention",
    )
    move = MarketMove(
        company_id=company.id, alert_id=alert.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=2.5, measurement_status="ok", measured_at=utcnow(),
    )
    db_session.add_all([alert_company, move])
    db_session.commit()
    return alert, article, alert_company, move


def test_refine_alert_sends_facts_and_never_the_raw_article(db_session):
    alert, article, alert_company, move = _seed(db_session, FACTS)
    client = _RecordingClient()

    refine_alert(client, db_session, alert, article, [alert_company], [move])

    assert FACTS in client.user_prompts
    # The point of the change: the article body is not re-sent on any call.
    assert BODY not in client.user_prompts
    # All four generators ran and their output landed.
    assert alert.summary_short == "Crude jumps after a supply outage"
    assert alert_company.why == "Higher crude lifts this refiner's realisations."
    assert client.prompts and all("Facts:" in p for p in client.prompts)


def test_refine_alert_falls_back_to_article_text_when_no_facts_stored(db_session):
    """An alert persisted before Alert.facts existed (or reused from one)
    must still refine -- off the article, exactly as it did before."""
    alert, article, alert_company, move = _seed(db_session, None)
    client = _RecordingClient()

    refine_alert(client, db_session, alert, article, [alert_company], [move])

    assert BODY in client.user_prompts
    assert alert.summary_long.startswith("A supply outage")


def test_refine_alert_prefers_full_content_over_content_in_fallback(db_session):
    alert, article, alert_company, move = _seed(db_session, None)
    article.full_content = "FULLTEXTMARKER extended body"
    db_session.commit()
    client = _RecordingClient()

    refine_alert(client, db_session, alert, article, [alert_company], [move])

    assert "FULLTEXTMARKER" in client.user_prompts


def test_analyze_article_carries_facts_out_of_the_cascade():
    """The cascade already distils the article once; analyze_article now
    hands that distillation to its caller instead of dropping it."""
    answers = {
        "record_facts": {"facts": FACTS, "category": "oil_gas", "event_type": "crude_oil"},
        "record_sectors": {"sectors": []},
    }

    def create(**kwargs):
        name = kwargs["tool_choice"]["function"]["name"]
        tool_call = SimpleNamespace(function=SimpleNamespace(name=name, arguments=json.dumps(answers[name])))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[tool_call]))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    result = analyze_article(client, "Oil jumps on outage", BODY)
    assert result.facts == FACTS


def test_persist_alert_stores_facts_for_the_refinement_layer(db_session):
    article = Article(source="test", url="https://example.com/b", title="Oil jumps", content=BODY)
    db_session.add(article)
    db_session.commit()

    alert = pipeline_module._persist_alert(
        db_session, article, category="oil_gas", entries=[], event_type="crude_oil", facts=FACTS,
    )
    assert alert.facts == FACTS


def test_reused_alert_carries_its_facts_to_the_new_alert(db_session, monkeypatch):
    """The dedup-reuse path skips analyze_article entirely, so the only
    facts available are the reused alert's -- without carrying them over,
    every republished story would silently refine off the raw article.

    Corrective-v4 Task 12: reuse now requires the prior alert to be fully
    gate-authoritative (see app.pipeline._dedup_reuse_policy_allows), so
    this seeds a gated AlertCompany plus a matching CompanyDecisionRecord
    audit row -- a bare gate-less alert (this test's old fixture) no
    longer qualifies for the reuse shortcut at all."""
    from app.models import CompanyDecisionRecord
    from app.pipeline import analysis_version

    company = Company(ticker="RELIANCE.NS", name="Reliance", sector="oil_gas", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()

    first = Article(
        source="test", url="https://example.com/1", title="Oil jumps on outage",
        content=BODY, status="ANALYZED", fetched_at=utcnow(),
    )
    db_session.add(first)
    db_session.commit()
    first_alert = Alert(article_id=first.id, category="oil_gas", event_type="crude_oil",
                        facts=FACTS, analysis_quality="authoritative")
    db_session.add(first_alert)
    db_session.commit()
    db_session.add(AlertCompany(
        alert_id=first_alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=3.0, rationale="refiner", basis="direct_mention",
        display_tier="primary", gate_state="DISPLAY_ELIGIBLE",
    ))
    db_session.add(CompanyDecisionRecord(
        alert_id=first_alert.id, company_id=company.id, ticker=company.ticker,
        final_state="DISPLAY_ELIGIBLE", display_tier="primary",
        analysis_version=analysis_version(),
    ))
    db_session.commit()

    duplicate = Article(
        source="other", url="https://example.com/2", title="Oil jumps on outage",
        content=BODY, status="CATEGORIZED", fetched_at=utcnow(),
    )
    db_session.add(duplicate)
    db_session.commit()

    monkeypatch.setattr(pipeline_module, "filter_new_articles", lambda *a, **k: None)
    pipeline_module.process_new_articles(db_session, object())

    reused = db_session.query(Alert).filter_by(article_id=duplicate.id).one()
    assert reused.facts == FACTS


def test_analysis_cache_row_written_before_facts_existed_still_loads():
    """AnalysisOutput.facts must stay optional -- an AnalysisCache row
    persisted before this shipped has no `facts` key at all."""
    legacy = json.dumps({"category": "oil_gas", "companies": []})
    assert AnalysisOutput.model_validate_json(legacy).facts is None


def test_company_mention_unchanged_by_facts_addition():
    mention = CompanyMention(
        name="Reliance", ticker="RELIANCE.NS", is_direct=True, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", time_horizon="Short-Term",
    )
    assert AnalysisOutput(category="oil_gas", companies=[mention], facts=FACTS).facts == FACTS
