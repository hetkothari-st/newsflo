"""Strict-mode deterministic sections (spec §23-§26, INV-007/008/010):
sections derive from validated gate output -- economic_effect and the
causal parent taxonomy -- never from an LLM title and never from price.
Flag off keeps the locked 3-tier path byte-identical. Stale-section
prevention (refine_alert delete-before-insert) is unconditional."""
import json

import pytest

from app.config import settings
from app.market.ripple_layers import compute_ripple_layers
from app.models import (
    Alert, AlertCompany, AlertRippleLayer, Article, Company, MarketMove,
    TimelineEffect, utcnow,
)


@pytest.fixture()
def strict_mode(monkeypatch):
    monkeypatch.setattr(settings, "impact_engine_v4_strict", True)


@pytest.fixture()
def legacy_mode(monkeypatch):
    monkeypatch.setattr(settings, "impact_engine_v4_strict", False)


def _seed_alert(db):
    article = Article(source="s", provider="finnhub", url="https://ex.com/a",
                      title="crude spikes", content="c", status="ALERTED")
    db.add(article)
    db.commit()
    alert = Alert(article_id=article.id, category="commodity", event_type="crude_oil")
    db.add(alert)
    db.commit()
    return alert


# Blueprint Sec4 / migration 0008: `economic_effect` is the ONE
# authoritative field and `direction` is DERIVED from it. A GATED fixture
# row whose direction contradicts its own effect is now refused outright by
# the alert_companies_gated_consistency trigger (app/models.py + 0008) --
# the same DB-level guard that would have caught the live OIL.NS row -- so
# these fixtures derive the direction instead of hardcoding one that the
# callers' `economic_effect="positive"` overrides then contradict.
_DIRECTION_FROM_EFFECT = {"positive": "bullish", "negative": "bearish"}


def _add_company(db, alert, ticker, name, sector, *, direction=None,
                 economic_effect="negative", display_tier="primary",
                 gate_state="DISPLAY_ELIGIBLE", causal_parent_id="crude_price",
                 materiality=0.7, excess=None, mechanism="crude-linked input costs"):
    if direction is None:
        direction = _DIRECTION_FROM_EFFECT.get(economic_effect, "bearish")
    company = Company(name=name, ticker=ticker, sector=sector, index_tier="NIFTY50")
    db.add(company)
    db.commit()
    ac = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction=direction,
        magnitude_low=1.0, magnitude_high=3.0, rationale="thesis",
        basis="direct_mention", economic_effect=economic_effect,
        display_tier=display_tier, gate_state=gate_state,
        causal_parent_type="economic_node", causal_parent_id=causal_parent_id,
        materiality=materiality, causal_distance=1, mechanism=mechanism,
    )
    db.add(ac)
    move = MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^NSEI",
        measurement_status="ok" if excess is not None else "no_data",
        excess_move_pct=excess, raw_move_pct=excess, sector_move_pct=0.0,
        measured_at=utcnow(), category="commodity",
    )
    db.add(move)
    db.commit()
    return company, ac


def test_strict_sections_direction_from_economic_effect_not_price(db_session, strict_mode):
    """Apollo case (spec §62): negative fundamental + positive price move
    renders as a negative section. Price never decides the icon."""
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "APOLLOTYRE.NS", "Apollo Tyres", "auto",
                 economic_effect="negative", excess=+2.1)

    layers = compute_ripple_layers(db_session, alert, set())

    assert len(layers) == 1
    assert layers[0]["icon"] == "lose"
    assert layers[0]["title"].startswith("Negative")
    # The measured move still rides along on the row, separate truth:
    assert layers[0]["rows"][0]["excess_move_pct"] == 2.1


def test_strict_sections_group_by_effect_and_parent(db_session, strict_mode):
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "ONGC.NS", "ONGC", "oil_gas",
                 economic_effect="positive", causal_parent_id="crude_price",
                 excess=-0.5)
    _add_company(db_session, alert, "MRF.NS", "MRF", "auto",
                 economic_effect="negative", causal_parent_id="tyre_input_cost",
                 excess=+0.5)

    layers = compute_ripple_layers(db_session, alert, set())

    assert len(layers) == 2
    titles = {layer["title"] for layer in layers}
    assert any(t.startswith("Positive") for t in titles)
    assert any(t.startswith("Negative") for t in titles)
    # every company exactly once (INV-010)
    tickers = [r["ticker"] for layer in layers for r in layer["rows"]]
    assert sorted(tickers) == ["MRF.NS", "ONGC.NS"]


@pytest.mark.parametrize("deep_dive_tier", ["secondary_deep_dive", "secondary"])
def test_strict_secondary_companies_render_in_secondary_section_last(
        db_session, strict_mode, deep_dive_tier):
    """"secondary_ripple" is the tier the gate writes now; "secondary_deep_dive"
    and "secondary" are the legacy spellings on pre-0008 rows and must still
    render.

    Final blueprint §12 (Task 5) changed the SHAPE of the trailing section,
    not its position: the single generic "Secondary — indirect exposure"
    bucket (relationship "SECONDARY") is deleted, and secondary rows now
    group on the same mechanism-taxonomy grain as primaries -- here
    "road_freight_fuel_cost" -> "RIPPLE:Logistics & freight". What this test
    has always pinned holds unchanged: secondary rows render in their own
    section(s), AFTER every primary one."""
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "ONGC.NS", "ONGC", "oil_gas",
                 economic_effect="positive", excess=1.0)
    _add_company(db_session, alert, "BLUEDART.NS", "Blue Dart", "railways_transport",
                 economic_effect="negative", display_tier=deep_dive_tier,
                 causal_parent_id="road_freight_fuel_cost", materiality=0.3,
                 excess=-0.2)

    # include_secondary=True (corrective-v4 Task 16): this test pins the
    # deep-dive builder's inclusive behavior directly; the feed's own
    # default (False) is covered by test_feed_primary_only.py.
    layers = compute_ripple_layers(db_session, alert, set(), include_secondary=True)

    assert layers[-1]["relationship"] == "RIPPLE:Logistics & freight"
    assert layers[-1]["title"] == "Secondary — Logistics & freight"
    assert [r["ticker"] for r in layers[-1]["rows"]] == ["BLUEDART.NS"]
    assert all(layer["relationship"].startswith("MECH:") for layer in layers[:-1])
    # The deleted generic bucket never comes back.
    assert all(layer["relationship"] != "SECONDARY" for layer in layers)


def test_strict_mixed_effect_section_is_side(db_session, strict_mode):
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "RELIANCE.NS", "Reliance", "oil_gas",
                 direction="neutral", economic_effect="mixed", excess=0.3)

    layers = compute_ripple_layers(db_session, alert, set())

    assert layers[0]["icon"] == "side"
    assert layers[0]["title"].startswith("Mixed")
    assert layers[0]["relationship"].startswith("MECH:")  # strict taxonomy section


def test_strict_legacy_alert_falls_back_to_three_tier(db_session, strict_mode):
    """Alerts persisted before the gate (display_tier NULL) keep the
    locked 3-tier rendering even in strict mode."""
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "ONGC.NS", "ONGC", "oil_gas",
                 display_tier=None, gate_state=None, excess=1.0)
    db_session.add(AlertRippleLayer(
        alert_id=alert.id, position=0, title="Winners — upstream",
        relationship="DIRECT", note="n", tickers_json=json.dumps(["ONGC.NS"])))
    db_session.commit()

    layers = compute_ripple_layers(db_session, alert, set())

    assert layers[0]["title"] == "Winners — upstream"  # tier-1 LLM layer used


def test_legacy_mode_with_no_gate_data_keeps_three_tier(db_session, legacy_mode):
    """Flag off AND no gate data on this alert's companies (gate_state/
    display_tier NULL): 3-tier path renders. Note this is now the ONLY
    "flag off" scenario that reaches the 3-tier path -- corrective-v4 Task
    12 made the legacy generator structurally unreachable whenever ANY
    company carries gate_state or display_tier, REGARDLESS of the flag
    (see test_sections_structural.py::
    test_gated_alert_legacy_unreachable_even_flag_off for that structural
    case). This test's OLD fixture genuinely did seed gate fields (the
    default gate_state="DISPLAY_ELIGIBLE"/display_tier="primary") and
    correctly pinned the PRE-Task-12 behavior of that combination: flag off
    was the sole authority, so the legacy layer rendered even with gate
    data present. That was a real, exercised assertion, not a no-op --
    the owner's Task 12 ruling deliberately INVERTED it (gate data now
    always wins over the flag), so this fixture was updated to a genuinely
    gate-less alert to keep testing what its name claims: "flag off"
    alone, not "flag off despite gate data" (which now renders strict)."""
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "ONGC.NS", "ONGC", "oil_gas",
                 display_tier=None, gate_state=None,
                 economic_effect="positive", excess=1.0)
    db_session.add(AlertRippleLayer(
        alert_id=alert.id, position=0, title="Winners — upstream",
        relationship="DIRECT", note="n", tickers_json=json.dumps(["ONGC.NS"])))
    db_session.commit()

    layers = compute_ripple_layers(db_session, alert, set())

    assert layers[0]["title"] == "Winners — upstream"


# --- closed-world explanations (Phase 6, spec §32, INV-014) ---------------

def test_strict_refine_uses_validated_mechanism_as_why(db_session, monkeypatch, strict_mode):
    """Strict mode: the per-company 'why' IS the gate-validated mechanism
    -- no LLM call invents a story for the measured move, and the section
    LLM (whose output strict rendering ignores) is not paid for."""
    from app.analysis import refinement

    alert = _seed_alert(db_session)
    company, ac = _add_company(db_session, alert, "MRF.NS", "MRF", "auto",
                               economic_effect="negative", excess=+1.0,
                               mechanism="crude-linked rubber input costs")
    article = db_session.get(Article, alert.article_id)
    move = db_session.query(MarketMove).filter_by(alert_id=alert.id).one()

    called = {"whys": 0, "layers": 0, "summary": 0, "timeline": 0}
    monkeypatch.setattr(refinement, "generate_event_summary",
                        lambda *a, **k: called.__setitem__("summary", called["summary"] + 1)
                        or {"summary_short": "s", "summary_long": "l", "is_unconfirmed": False})
    monkeypatch.setattr(refinement, "generate_impact_whys",
                        lambda *a, **k: called.__setitem__("whys", called["whys"] + 1) or {})
    monkeypatch.setattr(refinement, "generate_ripple_layers",
                        lambda *a, **k: called.__setitem__("layers", called["layers"] + 1) or [])
    monkeypatch.setattr(refinement, "generate_timeline_effects",
                        lambda *a, **k: called.__setitem__("timeline", called["timeline"] + 1) or [])

    refinement.refine_alert(object(), db_session, alert, article, [ac], [move])

    assert ac.why == "crude-linked rubber input costs"
    assert called["whys"] == 0     # market-move rationalization call never made
    assert called["layers"] == 0   # section LLM not paid for in strict mode
    assert called["summary"] == 1  # summaries still generated
    assert called["timeline"] == 1


def test_legacy_refine_still_calls_whys_and_layers(db_session, monkeypatch, legacy_mode):
    from app.analysis import refinement

    alert = _seed_alert(db_session)
    company, ac = _add_company(db_session, alert, "MRF.NS", "MRF", "auto",
                               display_tier=None, gate_state=None, excess=+1.0)
    article = db_session.get(Article, alert.article_id)
    move = db_session.query(MarketMove).filter_by(alert_id=alert.id).one()

    called = {"whys": 0, "layers": 0}
    monkeypatch.setattr(refinement, "generate_event_summary",
                        lambda *a, **k: {"summary_short": "s", "summary_long": "l",
                                         "is_unconfirmed": False})
    monkeypatch.setattr(refinement, "generate_impact_whys",
                        lambda *a, **k: called.__setitem__("whys", called["whys"] + 1) or {})
    monkeypatch.setattr(refinement, "generate_ripple_layers",
                        lambda *a, **k: called.__setitem__("layers", called["layers"] + 1) or [])
    monkeypatch.setattr(refinement, "generate_timeline_effects", lambda *a, **k: [])

    refinement.refine_alert(object(), db_session, alert, article, [ac], [move])

    assert called["whys"] == 1
    assert called["layers"] == 1


# --- stale-section prevention (unconditional) -----------------------------

def test_refine_alert_rerun_does_not_duplicate_layers_and_timeline(db_session, monkeypatch):
    """refine_alert appended AlertRippleLayer/TimelineEffect rows with no
    delete-before-insert -- a re-run duplicated every section (INV-009).
    Needs a LEGACY (gate_state/display_tier NULL) alert_company: since
    corrective-v4 Task 12 (review round 2 / I4) made refine_alert's
    generate_ripple_layers call structurally unreachable for a gated
    alert (is_gated), this file's `_add_company` default (gate_state=
    "DISPLAY_ELIGIBLE") would otherwise skip the AlertRippleLayer branch
    entirely and this test would never exercise the dedup fix it's named
    for. TimelineEffect's delete-before-insert stays unconditional either
    way; this fixture choice is only about reaching the layers branch too."""
    from app.analysis import refinement

    alert = _seed_alert(db_session)
    company, ac = _add_company(db_session, alert, "ONGC.NS", "ONGC", "oil_gas",
                               display_tier=None, gate_state=None,
                               excess=1.0)
    article = db_session.query(Article).get(alert.article_id)
    move = db_session.query(MarketMove).filter_by(alert_id=alert.id).one()

    monkeypatch.setattr(refinement, "generate_event_summary",
                        lambda *a, **k: {"summary_short": "s", "summary_long": "l",
                                         "is_unconfirmed": False})
    monkeypatch.setattr(refinement, "generate_impact_whys", lambda *a, **k: {})
    monkeypatch.setattr(refinement, "generate_ripple_layers",
                        lambda *a, **k: [{"title": "Winners — upstream",
                                          "relationship": "DIRECT", "note": "n",
                                          "tickers": ["ONGC.NS"]}])
    monkeypatch.setattr(refinement, "generate_timeline_effects",
                        lambda *a, **k: [{"horizon": "DAYS", "description": "d"}])

    refinement.refine_alert(object(), db_session, alert, article, [ac], [move])
    refinement.refine_alert(object(), db_session, alert, article, [ac], [move])

    assert db_session.query(AlertRippleLayer).filter_by(alert_id=alert.id).count() == 1
    assert db_session.query(TimelineEffect).filter_by(alert_id=alert.id).count() == 1
