"""Canonical fundamental-effect vocabulary (corrective plan 2026-08-13
task 2): economic_effect is a DISTINCT five-way enum -- mixed ("both real
channels present"), uncertain ("we don't know enough") and
no_material_impact ("we know enough to conclude it doesn't matter") never
collapse into each other. "neutral" is only a legacy/compat alias accepted
at parse boundaries and mapped to "no_material_impact"; it is never the
canonical or persisted value. The 3-way `direction` (bullish/bearish/
neutral) is a DIFFERENT axis and keeps "neutral" as a real value -- this
file never touches it."""
from app.analysis.impact_graph.schemas import (
    ECONOMIC_EFFECTS, GraphCompany, normalize_effect,
)


def _company(**overrides):
    """Minimal GraphCompany, mirroring tests/test_v4_strict_truth_model.py's
    _graph_company. .clamp() is called explicitly so economic_effect is
    reconciled from net_direction/direction exactly like the real engine
    pipeline does after construction."""
    payload = dict(
        ticker="RELIANCE.NS", name="Reliance Industries", direction="",
        impact_strength=0.6, confidence=0.7, materiality=0.5,
        causal_distance=1, time_horizon="Short-Term",
        parent_type="event", parent_id="event", mechanism="m",
    )
    payload.update(overrides)
    return GraphCompany(**payload).clamp()


def _company_without_materiality(**overrides):
    payload = dict(
        ticker="RELIANCE.NS", name="Reliance Industries", direction="bullish",
        impact_strength=0.6, confidence=0.7, causal_distance=1,
        time_horizon="Short-Term", parent_type="event", parent_id="event",
        mechanism="m",
    )
    payload.update(overrides)
    return GraphCompany(**payload).clamp()


def test_vocabulary_is_five_way_distinct():
    assert ECONOMIC_EFFECTS == [
        "positive", "negative", "mixed", "uncertain", "no_material_impact"]


def test_neutral_is_alias_not_canonical():
    assert normalize_effect("neutral") == "no_material_impact"
    assert normalize_effect("no_material_impact") == "no_material_impact"
    assert normalize_effect("mixed") == "mixed"
    assert normalize_effect(None) == "uncertain"


def test_uncertain_and_no_material_impact_never_collapse():
    c1 = _company(net_direction="uncertain")
    c2 = _company(net_direction="neutral")
    assert c1.economic_effect == "uncertain"
    assert c2.economic_effect == "no_material_impact"


def test_materiality_omission_is_none_not_zero():
    c = _company_without_materiality()
    assert c.materiality is None
