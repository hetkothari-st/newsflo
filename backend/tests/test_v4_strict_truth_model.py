"""V4 strict truth model (spec 2026-08-12 §2/§40, INV-001/INV-002):
fundamental economic impact and observed market reaction are separate
truths. Behind IMPACT_ENGINE_V4_STRICT the measured excess move must never
overwrite `AlertCompany.direction`, never delete the fundamental rationale,
and the neutral->bullish persistence coercion must stop. Legacy behavior
is pinned unchanged when the flag is off."""
import json
from datetime import timedelta

import pytest

from app.config import settings
from app.models import Alert, AlertCompany, Article, Company, MarketMove, utcnow
from app.pipeline import (
    _v3_entries,
    measure_and_reconcile_alert_companies,
    remeasure_no_data_moves,
)


@pytest.fixture()
def strict_mode(monkeypatch):
    monkeypatch.setattr(settings, "impact_engine_v4_strict", True)


@pytest.fixture()
def legacy_mode(monkeypatch):
    monkeypatch.setattr(settings, "impact_engine_v4_strict", False)


def _seed(db, *, direction="bullish", economic_effect="positive",
          move_status="no_data", created_at=None):
    article = Article(source="pulse_zerodha", provider="pulse_zerodha",
                      url="https://ex.com/a", title="t", content="c", status="ALERTED")
    company = Company(name="Reliance Industries", ticker="RELIANCE.NS", sector="oil_gas",
                      index_tier="NIFTY50")
    db.add_all([article, company])
    db.commit()
    alert = Alert(article_id=article.id, category="policy")
    if created_at is not None:
        alert.created_at = created_at
    db.add(alert)
    db.commit()
    alert_company = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction=direction,
        magnitude_low=1.0, magnitude_high=3.0, rationale="fundamental thesis text",
        key_points_json=json.dumps(["point"]), basis="direct_mention",
        economic_effect=economic_effect,
    )
    db.add(alert_company)
    if move_status is not None:
        move = MarketMove(
            alert_id=alert.id, company_id=company.id, benchmark_ticker="^NSEI",
            measurement_status=move_status, measured_at=utcnow(), category="policy",
        )
        db.add(move)
    db.commit()
    return alert, company, alert_company


def _ok_move(company, excess=-2.5):
    return MarketMove(
        company_id=company.id, benchmark_ticker="^CNXENERGY", raw_move_pct=excess + 0.5,
        sector_move_pct=0.5, excess_move_pct=excess, volume=1000.0, avg_volume_20d=500.0,
        volume_multiple=2.0, vol_normalized=1.1, materiality=0.01, avg_traded_value=9e8,
        measured_at=utcnow(), measurement_status="ok",
    )


# --- measure_and_reconcile_alert_companies -------------------------------

def test_strict_measurement_never_overwrites_fundamental_direction(
        db_session, monkeypatch, strict_mode):
    """INV-001: a bullish fundamental call with a -2.5% measured move keeps
    its direction, rationale and key points; the move is still recorded."""
    alert, company, alert_company = _seed(db_session, direction="bullish",
                                          move_status=None)
    import app.pipeline as pipeline_module
    monkeypatch.setattr(pipeline_module, "measure_company_move",
                        lambda session, c: _ok_move(c, excess=-2.5))

    moves = measure_and_reconcile_alert_companies(
        db_session, alert.id, [alert_company])

    assert len(moves) == 1
    assert moves[0].measurement_status == "ok"
    assert moves[0].excess_move_pct == -2.5
    assert alert_company.direction == "bullish"
    assert alert_company.rationale == "fundamental thesis text"
    assert json.loads(alert_company.key_points_json) == ["point"]
    assert alert_company.economic_effect == "positive"


def test_legacy_measurement_still_overwrites(db_session, monkeypatch, legacy_mode):
    """Flag off: the pre-strict behavior is pinned -- measured sign wins,
    contradicted prose is dropped, economic_effect is untouched."""
    alert, company, alert_company = _seed(db_session, direction="bullish",
                                          move_status=None)
    import app.pipeline as pipeline_module
    monkeypatch.setattr(pipeline_module, "measure_company_move",
                        lambda session, c: _ok_move(c, excess=-2.5))

    measure_and_reconcile_alert_companies(db_session, alert.id, [alert_company])

    assert alert_company.direction == "bearish"
    assert alert_company.rationale is None
    assert json.loads(alert_company.key_points_json) == []
    assert alert_company.economic_effect == "positive"  # never market-overwritten


# --- remeasure_no_data_moves ----------------------------------------------

def test_strict_remeasure_updates_move_but_not_direction(
        db_session, monkeypatch, strict_mode):
    alert, company, alert_company = _seed(db_session, direction="bullish")
    import app.pipeline as pipeline_module
    monkeypatch.setattr(pipeline_module, "measure_company_move",
                        lambda session, c: _ok_move(c, excess=-2.5))

    assert remeasure_no_data_moves(db_session) == 1
    move = db_session.query(MarketMove).filter_by(alert_id=alert.id).one()
    assert move.measurement_status == "ok"
    assert move.excess_move_pct == -2.5
    db_session.refresh(alert_company)
    assert alert_company.direction == "bullish"
    assert alert_company.rationale == "fundamental thesis text"


def test_legacy_remeasure_still_overwrites(db_session, monkeypatch, legacy_mode):
    alert, company, alert_company = _seed(db_session, direction="bullish")
    import app.pipeline as pipeline_module
    monkeypatch.setattr(pipeline_module, "measure_company_move",
                        lambda session, c: _ok_move(c, excess=-2.5))

    assert remeasure_no_data_moves(db_session) == 1
    db_session.refresh(alert_company)
    assert alert_company.direction == "bearish"
    assert alert_company.rationale is None


# --- _v3_entries persistence coercion -------------------------------------

def _graph_company(**overrides):
    from app.analysis.impact_graph.schemas import GraphCompany
    payload = dict(
        ticker="RELIANCE.NS", name="Reliance Industries", direction="neutral",
        impact_strength=0.6, confidence=0.7, materiality=0.5, causal_distance=1,
        time_horizon="Short-Term", parent_type="economic_node", parent_id="crude_price",
        mechanism="integrated refiner: crude cost up, marketing margin down",
        rationale="offsetting channels", net_direction="mixed",
        economic_effect="mixed",
        positive_channels=["upstream realization"], negative_channels=["fuel cost"],
    )
    payload.update(overrides)
    return GraphCompany(**payload)


def _result_with(companies):
    class _Result:
        pass
    result = _Result()
    result.companies = companies
    result.edges = []
    return result


def test_strict_v3_entries_preserve_neutral_and_mixed(db_session, strict_mode):
    """A mixed/uncertain company must persist as what it is -- not be
    laundered into 'bullish' at the persistence boundary (spec §19)."""
    _seed(db_session, move_status=None)
    entries = _v3_entries(db_session, _result_with([_graph_company()]))

    assert len(entries) == 1
    assert entries[0]["direction"] == "neutral"
    assert entries[0]["economic_effect"] == "mixed"


def test_legacy_v3_entries_coerce_neutral_to_bullish(db_session, legacy_mode):
    _seed(db_session, move_status=None)
    entries = _v3_entries(db_session, _result_with([_graph_company()]))

    assert entries[0]["direction"] == "bullish"
    assert entries[0]["economic_effect"] == "mixed"


def test_strict_v3_edges_preserve_neutral_direction(db_session, strict_mode):
    """Edge persistence must not launder neutral into bullish either --
    both the graph edges and the synthetic company-attachment edges."""
    from app.pipeline import _v3_edges
    from app.analysis.impact_graph.schemas import GraphEdge

    edge = GraphEdge(parent_type="event", parent_id="crude_supply_shock",
                     child_type="economic_node", child_id="crude_price",
                     direction="neutral", economic_effect="mixed",
                     mechanism="supply disruption", causal_distance=1,
                     impact_strength=0.7, confidence=0.8, materiality=0.6,
                     time_horizon="Short-Term")
    result = _result_with([_graph_company()])
    result.edges = [edge]

    edges = _v3_edges(result)

    assert edges[0]["direction"] == "neutral"      # graph edge
    assert edges[1]["direction"] == "neutral"      # company-attachment edge


# --- verifier corrections must keep direction/effect consistent -----------

def test_verifier_direction_correction_reconciles_economic_effect():
    """Bug fix (unconditional): a verification correction that flips
    `direction` must re-reconcile `economic_effect`, or the two truths
    diverge silently (engine.py corrections path)."""
    from app.analysis.impact_graph.engine import _apply_company_correction

    company = _graph_company(direction="bullish", economic_effect="positive",
                             net_direction="")
    _apply_company_correction(company, {"ticker": company.ticker,
                                        "direction": "bearish"})
    assert company.direction == "bearish"
    assert company.economic_effect == "negative"


def test_verifier_neutral_correction_preserves_mixed_effect():
    """Correcting to 'neutral' must NOT flatten a genuinely mixed effect --
    mixed already renders as neutral direction (spec §42)."""
    from app.analysis.impact_graph.engine import _apply_company_correction

    company = _graph_company(direction="bullish", economic_effect="mixed")
    _apply_company_correction(company, {"ticker": company.ticker,
                                        "direction": "neutral"})
    assert company.direction == "neutral"
    assert company.economic_effect == "mixed"
