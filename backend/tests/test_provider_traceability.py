"""Provider identity must survive StageRouter -> engine result -> Alert
persistence (provider-migration spec sections 9, 18, 16.19).

Three hops, three tests:
  1. StageRouter itself reports provider="claude"/quality="authoritative"
     when constructed with a Claude client (no network -- claude_client is
     injected, exactly like every other test in this repo).
  2. analyze_article_v3 (the engine) copies whatever router.provider/
     router.quality it was handed onto the returned ImpactGraphResult --
     duck-typed FakeRouter, same pattern as test_impact_graph.py, so this
     test isolates the engine's copy-through logic from StageRouter's own
     construction logic (already covered by test 1).
  3. app.pipeline persists ImpactGraphResult.analysis_provider/
     analysis_quality onto the Alert row -- same mocked-analysis harness
     test_pipeline.py's test_process_new_articles_creates_alert_end_to_end
     uses (monkeypatching pipeline_module.analyze_article_v3), extended
     here with an explicit provider="claude" fake result rather than
     relying on ImpactGraphResult's schema default.

A fourth pair of tests covers a genuine stamping gap found in review:
app.pipeline._analysis_model_for_provider (the decision-record audit
trail's best-effort model name, spec sec54) mapped "gemini"/"groq" to a
real model id but fell through to `return provider` for "claude" --
CompanyDecisionRecord/EvidenceRecord rows persisted model="claude" (the
literal provider string) instead of settings.claude_model. Fixed alongside
this test.

No real API call anywhere: every LLM boundary (StageRouter.claude_client,
analyze_article_v3, pipeline's claude_client) is a fake/mock.
"""
from app.analysis.impact_graph.budget import ArticleBudget
from app.analysis.impact_graph.engine import analyze_article_v3
from app.analysis.impact_graph.publication_gate import GateDecision
from app.analysis.impact_graph.router import StageRouter
from app.analysis.impact_graph.schemas import GraphCompany, ImpactGraphResult
from app.config import settings
from app.models import Alert, Article, Company, CompanyDecisionRecord
from app.pipeline import _analysis_model_for_provider


class _ClaudeOK:
    def generate(self, **kwargs):
        return {"ok": True}


def test_router_exposes_claude_identity():
    router = StageRouter(claude_api_key="k", claude_client=_ClaudeOK())
    assert router.provider == "claude"
    assert router.quality == "authoritative"


class _FakeRouter:
    """Duck-types StageRouter.call -- same pattern as test_impact_graph.py's
    FakeRouter, kept minimal here since this test only needs the
    extract_facts -> empty-shocks path to reach a terminal ImpactGraphResult
    and inspect what the engine stamped onto it."""

    def __init__(self, provider: str, quality: str):
        self.provider = provider
        self.quality = quality
        self.budget = ArticleBudget()

    def call(self, stage, **kwargs):
        if stage == "extract_facts":
            return {
                "event": "Strait of Hormuz closes", "event_status": "confirmed",
                "facts": "Hormuz closed; a fifth of global crude transits it.",
                "category": "oil_gas", "event_type": "geopolitics",
            }
        if stage == "initial_shocks":
            return {"shocks": [], "direct_nodes": []}
        # Everything else the broad-tier graph builder may probe with an
        # empty shock set (e.g. the anti-omission completeness_audit pass)
        # -- "nothing more to find" is the correct canned answer for every
        # one of them, mirroring test_impact_graph.py's FakeRouter defaults.
        if stage == "completeness_audit":
            return {"missing_branches": []}
        if stage == "ripple_discovery":
            return {"children": []}
        if stage == "map_companies":
            return {"companies": []}
        if stage == "verify_companies":
            return {"accept": [], "reject": []}
        if stage == "verify_edges":
            return {"verdicts": []}
        if stage == "rank_companies":
            return {"ranked": []}
        raise AssertionError(f"unexpected stage call: {stage}")


def test_engine_stamps_router_identity_onto_result(db_session):
    router = _FakeRouter(provider="claude", quality="authoritative")
    result = analyze_article_v3(
        router, "Hormuz closes", "body", session=db_session, article_id=1,
    )
    assert result.analysis_provider == "claude"
    assert result.analysis_quality == "authoritative"


def test_provider_survives_to_alert_columns(db_session, monkeypatch):
    """Reuses the mocked-analysis harness from test_pipeline.py's
    test_process_new_articles_creates_alert_end_to_end (monkeypatch
    pipeline_module.analyze_article_v3), with an explicit claude result
    rather than the ImpactGraphResult schema's stale "gemini" default."""
    import app.pipeline as pipeline_module
    from app.pipeline import process_new_articles

    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    article = Article(
        source="test", url="https://example.com/provider-traceability",
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
        analysis_provider="claude", analysis_quality="authoritative",
    )
    monkeypatch.setattr(
        pipeline_module, "analyze_article_v3",
        lambda router, title, content, session=None, article_id=None: fake_output,
    )

    created = process_new_articles(db_session, claude_client=object())
    assert created == 1

    alert = db_session.query(Alert).one()
    assert alert.analysis_provider == "claude"
    assert alert.analysis_quality == "authoritative"


def test_analysis_model_for_provider_maps_claude():
    assert _analysis_model_for_provider("claude") == settings.claude_model
    # Regression guard: the pre-existing branches must stay untouched by
    # the fix above.
    assert _analysis_model_for_provider("gemini") == settings.gemini_reasoning_model
    assert _analysis_model_for_provider("groq") == settings.groq_aux_model
    assert _analysis_model_for_provider("mystery") == "mystery"
    assert _analysis_model_for_provider(None) is None


def test_provider_model_survives_to_decision_record(db_session, monkeypatch):
    """The v4-strict publication gate is the only path that writes
    CompanyDecisionRecord rows (app.pipeline._persist_alert only does so
    for entries carrying gate_state -- see that function's else-branch).
    Exercises that path with an explicit "claude" result and asserts the
    persisted CompanyDecisionRecord.model is the real model id
    (settings.claude_model), not the literal provider string "claude" the
    pre-fix _analysis_model_for_provider fell through to."""
    import app.pipeline as pipeline_module
    from app.pipeline import process_new_articles

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
        analysis_provider="claude", analysis_quality="authoritative",
    )
    monkeypatch.setattr(
        pipeline_module, "analyze_article_v3",
        lambda router, title, content, session=None, article_id=None: fake_output,
    )

    article = Article(
        source="test", url="https://example.com/provider-model-decision-record",
        title="Oil refining margins jump", content="crude oil markets react",
    )
    db_session.add(article)
    db_session.commit()

    assert process_new_articles(db_session, claude_client=object()) == 1

    decision = db_session.query(CompanyDecisionRecord).filter_by(alert_id=article.alerts[0].id).one()
    assert decision.provider == "claude"
    assert decision.model == settings.claude_model
    assert decision.model != "claude"
