"""Silent-default instrumentation (2026-08-17).

`impact_strength` and `materiality` are NOT in SCHEMA_SHOCKS' required list,
so a model response that omits them silently parses as 0.5 -- indistinguishable
downstream from a deliberate 0.5 claim. These tests pin the LOG-ONLY audit that
makes the fire visible, and pin that it changes NOTHING about the parsed values.

Every LLM call is faked at the router layer -- no network anywhere.
"""
import logging

import pytest

from app.analysis.impact_graph.budget import ArticleBudget
from app.analysis.impact_graph.engine import (
    _audit_shock_defaults, _build_graph, _GraphState, _narrow_single_call,
)
from app.analysis.impact_graph.router import StageRouterError
from app.analysis.impact_graph.schemas import EventFacts

FULL_SHOCK = {
    "shock_id": "steel_input_cost",
    "label": "Steel input cost rises",
    "direction": "negative",
    "mechanism": "Import duty raises landed cost of hot-rolled coil",
    "confidence": 0.8,
    "impact_strength": 0.7,
    "materiality": 0.6,
    "time_horizon": "Short-Term",
}
# Schema-legal omission: shock_id/label/direction/mechanism/confidence are all
# present, so this response would pass structured-output validation intact.
OMITTING_SHOCK = {k: v for k, v in FULL_SHOCK.items()
                  if k not in ("impact_strength", "materiality")}


class FakeRouter:
    """Canned stage responses; raises if the engine asks for a stage we did
    not can, so an unexpected extra call can never silently pass."""

    def __init__(self, responses: dict):
        self._responses = responses
        self.calls: list[str] = []
        self.provider = "gemini"
        self.quality = "authoritative"
        self.budget = ArticleBudget()

    def call(self, stage, **kwargs):
        self.calls.append(stage)
        if stage not in self._responses:
            raise StageRouterError(f"no canned response for {stage}")
        return self._responses[stage]


def _facts() -> EventFacts:
    return EventFacts(event="Import duty raised on steel", facts="Duty up 15%.",
                      category="metals_mining", event_type="policy")


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records
            if r.levelno >= logging.WARNING and "shock_default_fired" in r.getMessage()]


def _shock_edges(state: _GraphState):
    return [e for e in state.edges if e.child_type == "economic_node"]


# --- unit: the audit helper itself --------------------------------------

def test_audit_logs_one_line_naming_both_defaulted_fields(caplog):
    with caplog.at_level(logging.WARNING):
        _audit_shock_defaults("initial_shocks", OMITTING_SHOCK, article_id=4242)
    warnings = _warnings(caplog)
    assert len(warnings) == 1, "one line per shock, never one per field"
    message = warnings[0]
    assert "stage=initial_shocks" in message
    assert "article=4242" in message
    assert "shock=steel_input_cost" in message
    assert "fields=impact_strength,materiality" in message


def test_audit_silent_when_every_defaulted_field_is_present(caplog):
    with caplog.at_level(logging.WARNING):
        _audit_shock_defaults("initial_shocks", FULL_SHOCK, article_id=1)
    assert _warnings(caplog) == []


def test_audit_also_covers_confidence_as_a_schema_enforcement_control(caplog):
    """`confidence` IS schema-required; a fire on it means the structured
    output contract was not enforced, which is worth seeing."""
    shock = {k: v for k, v in FULL_SHOCK.items() if k != "confidence"}
    with caplog.at_level(logging.WARNING):
        _audit_shock_defaults("narrow_graph", shock, article_id=None)
    assert "fields=confidence" in _warnings(caplog)[0]


def test_audit_falls_back_to_label_then_placeholder(caplog):
    with caplog.at_level(logging.WARNING):
        _audit_shock_defaults("narrow_graph", {"label": "Freight rates"}, article_id=7)
        _audit_shock_defaults("narrow_graph", {}, article_id=7)
    messages = _warnings(caplog)
    assert "shock=Freight rates" in messages[0]
    assert "shock=<unlabelled>" in messages[1]


# --- call site 1: _build_graph / initial_shocks -------------------------

@pytest.mark.parametrize("shock,expect_warning", [(OMITTING_SHOCK, True), (FULL_SHOCK, False)])
def test_initial_shocks_call_site_logs_only(caplog, shock, expect_warning):
    router = FakeRouter({"initial_shocks": {"shocks": [dict(shock)], "direct_nodes": [],
                                            "channel_audit": []}})
    state = _GraphState()
    with caplog.at_level(logging.WARNING):
        _build_graph(router, None, _facts(), state, ArticleBudget(), article_id=9021)
    assert bool(_warnings(caplog)) is expect_warning
    if expect_warning:
        assert "stage=initial_shocks article=9021" in _warnings(caplog)[0]


# --- call site 2: _narrow_single_call / narrow_graph --------------------

@pytest.mark.parametrize("shock,expect_warning", [(OMITTING_SHOCK, True), (FULL_SHOCK, False)])
def test_narrow_graph_call_site_logs_only(caplog, shock, expect_warning):
    router = FakeRouter({"narrow_graph": {"shocks": [dict(shock)], "edges": []}})
    state = _GraphState()
    with caplog.at_level(logging.WARNING):
        _narrow_single_call(router, None, _facts(), state, ArticleBudget(), article_id=9021)
    assert bool(_warnings(caplog)) is expect_warning
    if expect_warning:
        assert "stage=narrow_graph article=9021" in _warnings(caplog)[0]


# --- the load-bearing half: ZERO behaviour change ------------------------

@pytest.mark.parametrize("build", ["initial_shocks", "narrow_graph"])
def test_parsed_values_are_identical_with_and_without_the_audit(build):
    """The audit must not touch the shock dict or the values the engine
    derives from it -- the defaults still fire exactly as before."""
    def run(shock):
        state = _GraphState()
        if build == "initial_shocks":
            router = FakeRouter({"initial_shocks": {"shocks": [dict(shock)],
                                                    "direct_nodes": [], "channel_audit": []}})
            _build_graph(router, None, _facts(), state, ArticleBudget(), article_id=1)
        else:
            router = FakeRouter({"narrow_graph": {"shocks": [dict(shock)], "edges": []}})
            _narrow_single_call(router, None, _facts(), state, ArticleBudget(), article_id=1)
        return _shock_edges(state)

    omitting = run(OMITTING_SHOCK)
    full = run(FULL_SHOCK)
    assert len(omitting) == 1 and len(full) == 1
    # The silent default is UNCHANGED by instrumentation -- that is the point:
    # we are measuring it, not fixing it.
    assert omitting[0].impact_strength == 0.5
    assert omitting[0].materiality == 0.5
    assert full[0].impact_strength == 0.7
    assert full[0].materiality == 0.6
    # Everything the model DID state survives identically in both runs.
    for field in ("child_id", "direction", "mechanism", "confidence", "time_horizon"):
        assert getattr(omitting[0], field) == getattr(full[0], field)


def test_audit_does_not_mutate_the_shock_dict():
    shock = dict(OMITTING_SHOCK)
    _audit_shock_defaults("initial_shocks", shock, article_id=1)
    assert shock == OMITTING_SHOCK
