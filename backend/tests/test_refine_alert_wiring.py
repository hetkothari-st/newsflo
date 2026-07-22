from app.analysis.schemas import AnalysisOutput, CompanyMention
from app.models import Alert, AlertCompany, Article, Company, MarketMove, TimelineEffect
from app.pipeline import process_new_articles
import app.pipeline as pipeline_module


def _company(ticker="RELIANCE.NS", sector="oil_gas"):
    return Company(ticker=ticker, name=f"Company {ticker}", sector=sector, index_tier="NIFTY50", market_cap=1.0)


def _article(db_session, title="Oil prices surge on supply disruption"):
    article = Article(source="test", url=f"https://example.com/{title}", title=title, content="crude oil markets react")
    db_session.add(article)
    db_session.commit()
    return article


def _fake_analysis(ticker="RELIANCE.NS"):
    return AnalysisOutput(
        category="oil_gas",
        companies=[CompanyMention(
            name=f"Company {ticker}", ticker=ticker, is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
            key_points=["Crude eases"], confidence_score=85, time_horizon="Short-Term",
        )],
    )


def test_client_none_skips_refinement_entirely(db_session, monkeypatch):
    # Existing direct-call test sites (test_pipeline.py) call _persist_alert
    # with no client argument -- must behave exactly as before this plan.
    article = _article(db_session)
    alert = pipeline_module._persist_alert(db_session, article, category="oil_gas", entries=[], event_type="crude_oil")
    assert alert.summary_short is None
    assert alert.summary_long is None


def test_process_new_articles_populates_summary_and_why_when_measured(db_session, monkeypatch):
    company = _company()
    db_session.add(company)
    db_session.commit()
    article = _article(db_session)
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: _fake_analysis())

    def fake_measure(session, company_obj):
        from app.models import utcnow
        return MarketMove(
            company_id=company_obj.id, benchmark_ticker="^CNXENERGY",
            excess_move_pct=4.2, measurement_status="ok", measured_at=utcnow(),
        )
    monkeypatch.setattr(pipeline_module, "measure_company_move", fake_measure)

    def fake_refine_alert(client, session, alert, article_arg, alert_companies, market_moves):
        alert.summary_short = "Oil supply shock lifts refiners"
        alert.summary_long = "Crude prices jumped on a supply disruption. Refiners benefit from wider margins."
        for ac in alert_companies:
            ac.why = "Higher crude prices lift refining margins for this company."
        from app.models import TimelineEffect as TE
        session.add(TE(alert_id=alert.id, horizon="TODAY", description="Markets react immediately."))
    monkeypatch.setattr(pipeline_module, "refine_alert", fake_refine_alert)

    process_new_articles(db_session, claude_client=object())

    alert = db_session.query(Alert).one()
    assert alert.summary_short == "Oil supply shock lifts refiners"
    ac = db_session.query(AlertCompany).filter_by(alert_id=alert.id).one()
    assert ac.why == "Higher crude prices lift refining margins for this company."
    timeline = db_session.query(TimelineEffect).filter_by(alert_id=alert.id).all()
    assert len(timeline) == 1
    assert timeline[0].horizon == "TODAY"


def test_refine_alert_leaves_why_none_for_a_company_with_no_measured_move(db_session):
    from app.analysis.refinement import refine_alert
    from app.models import utcnow

    company = _company()
    db_session.add(company)
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    ac = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=2.0, magnitude_high=4.0, rationale="r", basis="direct_mention",
    )
    db_session.add(ac)
    no_data_move = MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        measurement_status="no_data", measured_at=utcnow(),
    )
    db_session.add(no_data_move)
    db_session.commit()

    class UnreachableClient:
        class _Completions:
            def create(self, **kwargs):
                raise AssertionError("must not call the LLM for an unmeasured company")

        @property
        def chat(self):
            from types import SimpleNamespace
            return SimpleNamespace(completions=self._Completions())

    refine_alert(UnreachableClient(), db_session, alert, article, [ac], [no_data_move])

    assert ac.why is None
