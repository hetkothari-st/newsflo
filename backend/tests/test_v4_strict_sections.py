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


def _add_company(db, alert, ticker, name, sector, *, direction="bearish",
                 economic_effect="negative", display_tier="primary",
                 gate_state="DISPLAY_ELIGIBLE", causal_parent_id="crude_price",
                 materiality=0.7, excess=None, mechanism="crude-linked input costs"):
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


def test_strict_secondary_companies_render_in_secondary_section_last(db_session, strict_mode):
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "ONGC.NS", "ONGC", "oil_gas",
                 economic_effect="positive", excess=1.0)
    _add_company(db_session, alert, "BLUEDART.NS", "Blue Dart", "railways_transport",
                 economic_effect="negative", display_tier="secondary",
                 causal_parent_id="road_freight_fuel_cost", materiality=0.3,
                 excess=-0.2)

    layers = compute_ripple_layers(db_session, alert, set())

    assert layers[-1]["relationship"] == "SECONDARY"
    assert [r["ticker"] for r in layers[-1]["rows"]] == ["BLUEDART.NS"]
    assert all(layer["relationship"] != "SECONDARY" for layer in layers[:-1])


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


def test_legacy_mode_ignores_gate_fields_entirely(db_session, legacy_mode):
    """Flag off: 3-tier path untouched even when gate fields exist."""
    alert = _seed_alert(db_session)
    _add_company(db_session, alert, "ONGC.NS", "ONGC", "oil_gas",
                 economic_effect="positive", excess=1.0)
    db_session.add(AlertRippleLayer(
        alert_id=alert.id, position=0, title="Winners — upstream",
        relationship="DIRECT", note="n", tickers_json=json.dumps(["ONGC.NS"])))
    db_session.commit()

    layers = compute_ripple_layers(db_session, alert, set())

    assert layers[0]["title"] == "Winners — upstream"


# --- stale-section prevention (unconditional) -----------------------------

def test_refine_alert_rerun_does_not_duplicate_layers_and_timeline(db_session, monkeypatch):
    """refine_alert appended AlertRippleLayer/TimelineEffect rows with no
    delete-before-insert -- a re-run duplicated every section (INV-009)."""
    from app.analysis import refinement

    alert = _seed_alert(db_session)
    company, ac = _add_company(db_session, alert, "ONGC.NS", "ONGC", "oil_gas",
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
