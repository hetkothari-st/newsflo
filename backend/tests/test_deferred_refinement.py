"""Phase 5 of the cost-optimization plan: take the four refinement calls
off the analysis run's critical path.

The safety property is that a deferred alert is indistinguishable from one
whose inline refinement returned nothing -- a state the API and the
translation job have always had to handle. So these tests check both the
queue mechanics and that an unrefined alert still serves.
"""
import json
from types import SimpleNamespace

import app.pipeline as pipeline_module
from app.analysis.refinement import (
    MAX_REFINEMENT_ATTEMPTS, REFINEMENT_DONE, REFINEMENT_FAILED, REFINEMENT_PENDING,
    run_pending_refinements,
)
from app.config import settings
from app.models import Alert, AlertCompany, AlertRippleLayer, Article, Company, MarketMove, TimelineEffect, utcnow


def _article(db_session, url="https://example.com/a"):
    article = Article(source="test", url=url, title="Oil jumps on outage", content="body")
    db_session.add(article)
    db_session.commit()
    return article


class _RefiningClient:
    _ANSWERS = {
        "record_event_summary": {
            "summary_short": "Crude jumps after a supply outage",
            "summary_long": "A supply outage pushed crude prices up. Refiners face costlier input.",
            "is_unconfirmed": False,
        },
        "record_impact_whys": {"whys": []},
        "record_ripple_layers": {"layers": []},
        "record_timeline_effects": {"effects": [{"horizon": "TODAY", "description": "Energy names move first."}]},
    }

    def __init__(self):
        self.calls = 0

    class _Completions:
        def __init__(self, outer):
            self._outer = outer

        def create(self, **kwargs):
            self._outer.calls += 1
            name = kwargs["tool_choice"]["function"]["name"]
            tool_call = SimpleNamespace(function=SimpleNamespace(
                name=name, arguments=json.dumps(self._outer._ANSWERS[name]),
            ))
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[tool_call]))])

    @property
    def chat(self):
        return SimpleNamespace(completions=self._Completions(self))


def test_inline_mode_is_the_default_and_refines_during_the_run(db_session, monkeypatch):
    monkeypatch.setattr(settings, "refinement_mode", "inline")
    calls = []
    monkeypatch.setattr(
        pipeline_module, "refine_alert",
        lambda *args, **kwargs: calls.append(1),
    )
    alert = pipeline_module._persist_alert(
        db_session, _article(db_session), category="oil_gas", entries=[], client=object(),
    )
    assert calls == [1]
    assert alert.refinement_status is None


def test_deferred_mode_queues_instead_of_calling(db_session, monkeypatch):
    monkeypatch.setattr(settings, "refinement_mode", "deferred")
    calls = []
    monkeypatch.setattr(pipeline_module, "refine_alert", lambda *a, **k: calls.append(1))

    alert = pipeline_module._persist_alert(
        db_session, _article(db_session), category="oil_gas", entries=[], client=object(),
    )

    assert calls == []  # no LLM work happened on the analysis run
    assert alert.refinement_status == REFINEMENT_PENDING
    # ...and the alert is fully usable, just without its refinement text.
    assert alert.summary_short is None
    assert alert.id is not None


def test_deferred_pass_fills_in_the_pending_alert(db_session, monkeypatch):
    monkeypatch.setattr(settings, "refinement_mode", "deferred")
    monkeypatch.setattr(pipeline_module, "refine_alert", pipeline_module.refine_alert)
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas", refinement_status=REFINEMENT_PENDING, facts="outage facts")
    db_session.add(alert)
    db_session.commit()

    refined = run_pending_refinements(_RefiningClient(), db_session)

    assert refined == 1
    db_session.refresh(alert)
    assert alert.refinement_status == REFINEMENT_DONE
    assert alert.summary_short == "Crude jumps after a supply outage"
    assert db_session.query(TimelineEffect).filter_by(alert_id=alert.id).count() == 1


def test_deferred_pass_reasons_from_the_stored_facts(db_session):
    """Phases 1 and 5 have to work together: by the time the batch pass
    runs, the article's cascade output is long gone, so the facts it
    reasons from must be the ones persisted on the alert."""
    article = _article(db_session)
    db_session.add(Alert(
        article_id=article.id, category="oil_gas",
        refinement_status=REFINEMENT_PENDING, facts="UNIQUEFACTSMARKER",
    ))
    db_session.commit()

    seen = []

    class _Capturing(_RefiningClient):
        class _Completions(_RefiningClient._Completions):
            def create(self, **kwargs):
                seen.append(kwargs["messages"][-1]["content"])
                return super().create(**kwargs)

    run_pending_refinements(_Capturing(), db_session)
    assert any("UNIQUEFACTSMARKER" in prompt for prompt in seen)


def test_deferred_pass_respects_the_batch_limit(db_session, monkeypatch):
    article = _article(db_session)
    for _ in range(4):
        db_session.add(Alert(article_id=article.id, category="oil_gas", refinement_status=REFINEMENT_PENDING))
    db_session.commit()

    assert run_pending_refinements(_RefiningClient(), db_session, limit=2) == 2
    assert db_session.query(Alert).filter_by(refinement_status=REFINEMENT_PENDING).count() == 2


def test_one_failing_alert_does_not_stop_the_batch(db_session):
    article = _article(db_session)
    good = Alert(article_id=article.id, category="oil_gas", refinement_status=REFINEMENT_PENDING)
    bad = Alert(article_id=article.id, category="oil_gas", refinement_status=REFINEMENT_PENDING)
    db_session.add_all([bad, good])
    db_session.commit()

    class _FailsOnFirst(_RefiningClient):
        class _Completions(_RefiningClient._Completions):
            def create(self, **kwargs):
                if self._outer.calls == 0:
                    self._outer.calls += 1
                    raise RuntimeError("provider exploded")
                return super().create(**kwargs)

    # refine_alert itself swallows generation failures, so force the error
    # past it to exercise run_pending_refinements' own containment.
    import app.analysis.refinement as refinement_module
    original = refinement_module.refine_alert
    state = {"first": True}

    def flaky(client, session, alert, article_arg, alert_companies, market_moves):
        if state["first"]:
            state["first"] = False
            raise RuntimeError("provider exploded")
        return original(client, session, alert, article_arg, alert_companies, market_moves)

    refinement_module.refine_alert = flaky
    try:
        refined = run_pending_refinements(_RefiningClient(), db_session)
    finally:
        refinement_module.refine_alert = original

    assert refined == 1
    db_session.refresh(bad)
    assert bad.refinement_status == REFINEMENT_PENDING  # left for the next pass
    assert bad.refinement_attempts == 1


def test_a_repeatedly_failing_alert_is_eventually_given_up_on(db_session):
    article = _article(db_session)
    alert = Alert(
        article_id=article.id, category="oil_gas", refinement_status=REFINEMENT_PENDING,
        refinement_attempts=MAX_REFINEMENT_ATTEMPTS - 1,
    )
    db_session.add(alert)
    db_session.commit()

    import app.analysis.refinement as refinement_module
    original = refinement_module.refine_alert
    refinement_module.refine_alert = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("nope"))
    try:
        run_pending_refinements(_RefiningClient(), db_session)
    finally:
        refinement_module.refine_alert = original

    db_session.refresh(alert)
    assert alert.refinement_status == REFINEMENT_FAILED
    # A given-up alert keeps exactly the null fields every reader tolerates.
    assert alert.summary_short is None


def test_pending_alert_serves_over_the_api(db_session):
    """The interim state has to render. This is the same null-refinement
    shape the API has always had to handle when an inline refinement call
    came back empty."""
    from app.routers.alerts import _serialize_alert

    company = Company(ticker="RELIANCE.NS", name="Reliance", sector="oil_gas", index_tier="NIFTY50")
    article = _article(db_session)
    db_session.add(company)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_gas", refinement_status=REFINEMENT_PENDING)
    db_session.add(alert)
    db_session.flush()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish", magnitude_low=1.0,
        magnitude_high=2.0, rationale="r", basis="direct_mention",
    ))
    db_session.add(MarketMove(
        company_id=company.id, alert_id=alert.id, benchmark_ticker="^NSEI",
        measurement_status="no_data", measured_at=utcnow(),
    ))
    db_session.commit()

    payload = _serialize_alert(
        alert, held_company_ids=set(), article_titles={}, ac_translations={},
        category_labels={}, mentions_index={},
    )
    assert payload["companies"][0]["why"] is None
    assert payload["companies"][0]["ticker"] == "RELIANCE.NS"

    # The swipe-card feed is the surface that actually shows the event
    # summary, so it gets checked too -- a pending alert must serve there
    # with the summary simply absent, not error out.
    from app.routers.feed_v2 import _serialize

    card = _serialize(alert, measurement={}, held_company_ids=set(), repeated_images=set())
    assert card["summary_short"] is None
    assert card["summary_long"] is None
    assert card["article"]["title"] == "Oil jumps on outage"
    assert db_session.query(AlertRippleLayer).filter_by(alert_id=alert.id).count() == 0


def test_run_pending_refinements_ignores_already_done_alerts(db_session):
    article = _article(db_session)
    db_session.add_all([
        Alert(article_id=article.id, category="oil_gas", refinement_status=REFINEMENT_DONE),
        Alert(article_id=article.id, category="oil_gas"),  # inline-refined, status NULL
    ])
    db_session.commit()

    client = _RefiningClient()
    assert run_pending_refinements(client, db_session) == 0
    assert client.calls == 0
