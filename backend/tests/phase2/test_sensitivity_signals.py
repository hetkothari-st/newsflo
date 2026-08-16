"""TASK 2.4 + 2.5 -- the engine end to end: ledger -> channels -> signals ->
reducer -> serialized surface, plus the controller addendum (real staleness
reaching the Phase 0 gate).

Everything here runs on `_fixture`-marked rows in a throwaway database.
"""
import json
from datetime import date

import pytest
from sqlalchemy import text

from tests.phase2.conftest import (
    FIXTURE_ANALYSIS_VERSION, FIXTURE_EVENT_ID, FIXTURE_NOW, FIXTURE_TODAY,
    load_worked_examples, make_company, seed_curve, seed_exposure,
    seed_financials, seed_modifier,
)

TAG = "input_cost:fixture_input"


def _shock(delta_pct: float = 0.1, horizon_days: int = 90):
    from app.analysis.sensitivity.channels import Shock

    return Shock(shock_id="fixture-shock-1", exposure_tag=TAG,
                 delta_pct=delta_pct, horizon_days=horizon_days,
                 mechanism_id="fixture:mechanism:1")


def seed_company_with_a_computable_channel(session, *, ticker="FIXG.NS",
                                           as_of_date=FIXTURE_TODAY,
                                           freshness_days=400):
    company = make_company(session, ticker=ticker, name=f"FIXTURECO {ticker}")
    seed_exposure(session, exposure_id=f"fixture-exp-{ticker}",
                  company_id=company.id, exposure_tag=TAG,
                  exposure_kind="INPUT_COST", base_value_inr=10000000000.0,
                  share_of_base=0.25, as_of_date=as_of_date,
                  freshness_days=freshness_days)
    seed_curve(session, curve_id=f"fixture-curve-{ticker}", company_id=company.id,
               exposure_tag=TAG,
               points=load_worked_examples()["pass_through_curve"]["points"],
               basis="DISCLOSED_CALL")
    seed_modifier(session, modifier_id=f"fixture-mod-{ticker}",
                  company_id=company.id, applies_to_tag=TAG, modifier_kind="HEDGE",
                  parameters={"hedge_ratio": 0.5, "measurement": "FILED"})
    seed_financials(session, company_id=company.id, ebitda_inr=2000000000.0)
    session.flush()
    return company


def analyse(session, company_id, **kwargs):
    from app.analysis.sensitivity.engine import analyse_company

    kwargs.setdefault("as_of", FIXTURE_TODAY)
    return analyse_company(
        session, company_id=company_id, shocks=[_shock()],
        event_id=FIXTURE_EVENT_ID, analysis_version=FIXTURE_ANALYSIS_VERSION,
        created_at=FIXTURE_NOW, **kwargs)


# --- the ledger authorises the channel -------------------------------------

def test_an_empty_ledger_emits_no_sensitivity_signal_at_all(sensitivity_session):
    company = make_company(sensitivity_session, ticker="FIXH.NS",
                           name="FIXTURECO H")
    run = analyse(sensitivity_session, company.id)
    assert run.signals == ()
    assert run.channels == ()
    assert run.materiality is None
    assert run.exposure_stale is False


def test_an_exposure_with_no_resolvable_parameter_is_uncomputable_not_guessed(
        sensitivity_session):
    company = make_company(sensitivity_session, ticker="FIXI.NS", name="FIXTURECO I")
    seed_exposure(sensitivity_session, exposure_id="fixture-exp-I",
                  company_id=company.id, exposure_tag=TAG,
                  exposure_kind="INPUT_COST", base_value_inr=10000000000.0,
                  share_of_base=0.25)
    seed_financials(sensitivity_session, company_id=company.id,
                    ebitda_inr=2000000000.0)
    run = analyse(sensitivity_session, company.id)
    assert run.channels == ()
    assert run.signals == ()
    assert run.uncomputable_channels == (TAG,)


def test_a_company_with_no_ebitda_base_publishes_nothing(sensitivity_session):
    company = seed_company_with_a_computable_channel(sensitivity_session,
                                                     ticker="FIXJ.NS")
    sensitivity_session.execute(text("DELETE FROM company_financials"))
    run = analyse(sensitivity_session, company.id)
    assert run.materiality is None
    assert run.signals == ()


def test_a_computable_company_emits_one_channel_signal_carrying_its_provenance(
        sensitivity_session):
    company = seed_company_with_a_computable_channel(sensitivity_session)
    run = analyse(sensitivity_session, company.id)

    assert len(run.signals) == 1
    payload = dict(run.signals[0].payload)
    assert payload["channel_id"] == TAG
    assert payload["exposure_id"] == f"fixture-exp-FIXG.NS"
    assert payload["evidence_ids"] == ["fixture-exp-FIXG.NS"]
    assert payload["param_sources"] == {"pass_through": "DISCLOSED_CALL",
                                        "hedge_ratio": "FILED"}
    assert payload["horizon"] == "NEAR_TERM"
    assert payload["mechanism_id"] == "fixture:mechanism:1"
    assert payload["direction"] == "NEGATIVE"
    assert payload["sensitivity"]["bucket"] == run.materiality.bucket
    assert run.signals[0].stage == "SENSITIVITY"
    assert run.signals[0].created_by.startswith("sensitivity:")


def test_the_engine_reproduces_the_worked_example_from_the_ledger(
        sensitivity_session):
    """C1's arithmetic, but every input read out of the database instead of
    handed to the function."""
    company = seed_company_with_a_computable_channel(sensitivity_session,
                                                     ticker="FIXK.NS")
    run = analyse(sensitivity_session, company.id)
    assert abs(run.channels[0].delta_ebitda_inr - (-75000000.0)) <= 75000.0
    assert abs(run.materiality.delta_ebitda_pct.p50 - (-3.75)) <= 0.25


# --- the addendum: real staleness reaches the gate -------------------------

def test_a_company_whose_only_backing_exposure_is_stale_is_rejected_as_stale(
        sensitivity_session):
    from app.core.config_loader import load_gate_config, load_sensitivity_policy
    from app.core.reducer import EventContext, ReducerConfig, reduce_company_impact

    company = seed_company_with_a_computable_channel(
        sensitivity_session, ticker="FIXL.NS",
        as_of_date=date(2224, 1, 1), freshness_days=400)
    run = analyse(sensitivity_session, company.id)
    assert run.exposure_stale is True, (
        "the engine must report the real staleness of the rows that would "
        "back this company's channels")

    signals = _supporting_signals(company.id)
    config = ReducerConfig(
        gate_config=load_gate_config(),
        event_context=EventContext(event_status="CONFIRMED",
                                   shock_magnitude_confidence=0.9,
                                   exposure_stale=run.exposure_stale),
        sensitivity_policy=load_sensitivity_policy())
    impact = reduce_company_impact(signals, config)
    assert impact.publication_tier == "REJECTED"
    assert impact.rejection_reason == "EXPOSURE_STALE"


def test_a_fresh_exposure_passes_the_freshness_hard_block(sensitivity_session):
    from app.core.config_loader import load_gate_config, load_sensitivity_policy
    from app.core.reducer import EventContext, ReducerConfig, reduce_company_impact

    company = seed_company_with_a_computable_channel(sensitivity_session,
                                                     ticker="FIXM.NS")
    run = analyse(sensitivity_session, company.id)
    assert run.exposure_stale is False

    config = ReducerConfig(
        gate_config=load_gate_config(),
        event_context=EventContext(event_status="CONFIRMED",
                                   shock_magnitude_confidence=0.9,
                                   exposure_stale=run.exposure_stale),
        sensitivity_policy=load_sensitivity_policy())
    impact = reduce_company_impact(list(run.signals) + _supporting_signals(company.id),
                                   config)
    freshness = [r for r in impact.gate_trace if r["rule"] == "exposure_freshness"]
    assert freshness and freshness[0]["passed"] is True
    assert impact.rejection_reason != "EXPOSURE_STALE"


def test_a_stale_row_also_carries_the_flag_on_the_channel_payload(
        sensitivity_session):
    """Both lines of defence: `ledger_exposures` filters stale rows out, AND
    the flag travels with the signal so the reducer can hard-block even when
    the caller forgot to thread the event context."""
    from app.core.config_loader import load_gate_config, load_sensitivity_policy
    from app.core.reducer import EventContext, ReducerConfig, reduce_company_impact

    company = seed_company_with_a_computable_channel(sensitivity_session,
                                                     ticker="FIXN.NS")
    # A SECOND exposure for the same tag, stale, which therefore does not
    # back a channel -- but does make this company's exposure set stale.
    seed_exposure(sensitivity_session, exposure_id="fixture-exp-FIXN-stale",
                  company_id=company.id, exposure_tag=TAG,
                  exposure_kind="INPUT_COST", base_value_inr=10000000000.0,
                  share_of_base=0.25, as_of_date=date(2224, 1, 1),
                  freshness_days=400)
    run = analyse(sensitivity_session, company.id)
    assert run.channels, "the fresh row still backs a channel"
    assert run.exposure_stale is True
    assert dict(run.signals[0].payload)["exposure_stale"] is True

    config = ReducerConfig(
        gate_config=load_gate_config(),
        event_context=EventContext(event_status="CONFIRMED",
                                   shock_magnitude_confidence=0.9,
                                   exposure_stale=False),   # caller forgot
        sensitivity_policy=load_sensitivity_policy())
    impact = reduce_company_impact(list(run.signals) + _supporting_signals(company.id),
                                   config)
    assert impact.rejection_reason == "EXPOSURE_STALE"


def _supporting_signals(company_id: int):
    """Entity + discovery + evidence + empirical for the SAME company and
    event as the engine's channel signals, so a reduction is well formed."""
    from app.core.signals import make_signal

    def emit(stage, kind, payload, created_by):
        return make_signal(event_id=FIXTURE_EVENT_ID, company_id=company_id,
                           stage=stage, kind=kind, payload=payload,
                           created_by=created_by,
                           analysis_version=FIXTURE_ANALYSIS_VERSION,
                           created_at=FIXTURE_NOW)

    return [
        emit("ENTITY", "ENTITY_RESOLUTION",
             {"ticker": "FIXTURE.NS", "isin": "INF0000FIXTURE",
              "resolution": "RESOLVED", "entity_status": "ACTIVE"},
             "fixture:entity"),
        emit("DISCOVERY", "DISCOVERY",
             {"discovery_source": "MECHANISM", "directness": "DIRECT",
              "graph_distance": 1}, "fixture:discovery"),
        emit("EVIDENCE", "EVIDENCE_BINDING",
             {"claim_id": "fixture:claim:1", "claim_type": "MATERIALITY",
              "binding_status": "BOUND", "evidence_grade": "B",
              "evidence_ids": ["fixture-ev-1"]}, "fixture:evidence"),
        emit("EMPIRICAL", "EMPIRICAL_CHECK", {"status": "NO_DATA", "n_events": None},
             "empirical:not_available"),
    ]


# --- adapter precedence ----------------------------------------------------

def v4_entry():
    return {
        "company_id": 9301, "ticker": "FIXV4.NS", "economic_effect": "negative",
        "materiality_grade": "HIGH", "evidence_tier": "B",
        "causal_directness": "DIRECT", "causal_distance": 1,
        "discovery_source_vocab": "ARTICLE_MENTION",
        "evidence_ids": ["fixture-ev-9"], "causal_parent_id": "fixture:mech",
    }


def test_without_sensitivity_channels_the_adapter_output_is_byte_identical():
    """The empty-ledger case, which is production today: the V4 signals must
    be exactly what they were before Phase 2 existed."""
    from app.core.signal_adapters import signals_from_entry

    plain = signals_from_entry(v4_entry(), event_id=FIXTURE_EVENT_ID,
                               analysis_version=FIXTURE_ANALYSIS_VERSION,
                               created_at=FIXTURE_NOW)
    with_empty = signals_from_entry(v4_entry(), event_id=FIXTURE_EVENT_ID,
                                    analysis_version=FIXTURE_ANALYSIS_VERSION,
                                    created_at=FIXTURE_NOW,
                                    sensitivity_channels=())
    assert [s.signal_id for s in plain] == [s.signal_id for s in with_empty]
    assert any(str(s.kind) == "CHANNEL" for s in plain)


def test_sensitivity_channels_supersede_the_v4_materiality_forwarding(
        sensitivity_session):
    from app.core.signal_adapters import signals_from_entry

    company = seed_company_with_a_computable_channel(sensitivity_session,
                                                     ticker="FIXO.NS")
    run = analyse(sensitivity_session, company.id)
    signals = signals_from_entry(
        v4_entry(), event_id=FIXTURE_EVENT_ID,
        analysis_version=FIXTURE_ANALYSIS_VERSION, created_at=FIXTURE_NOW,
        sensitivity_channels=run.signals)

    channels = [s for s in signals if str(s.kind) == "CHANNEL"]
    assert channels == list(run.signals), (
        "when the sensitivity engine has an answer, the V4 materiality "
        "forwarding must not also be emitted")
    assert all(s.created_by.startswith("sensitivity:") for s in channels)
    # Everything the V4 stages know that Phase 2 does not is still emitted.
    assert {str(s.kind) for s in signals} >= {
        "ENTITY_RESOLUTION", "DISCOVERY", "EVIDENCE_BINDING", "EMPIRICAL_CHECK"}


# --- Task 2.5: the API surface ---------------------------------------------

def reduced_with_sensitivity(session):
    from app.core.config_loader import load_gate_config, load_sensitivity_policy
    from app.core.reducer import EventContext, ReducerConfig, reduce_company_impact

    company = seed_company_with_a_computable_channel(session, ticker="FIXP.NS")
    run = analyse(session, company.id)
    config = ReducerConfig(
        gate_config=load_gate_config(),
        event_context=EventContext(event_status="CONFIRMED",
                                   shock_magnitude_confidence=0.9,
                                   exposure_stale=run.exposure_stale),
        sensitivity_policy=load_sensitivity_policy())
    return reduce_company_impact(
        list(run.signals) + _supporting_signals(company.id), config)


def test_the_serializer_exposes_the_band_bucket_consistency_and_drivers(
        sensitivity_session):
    from app.core.reducer import serialize_company_impact

    payload = serialize_company_impact(reduced_with_sensitivity(sensitivity_session))
    materiality = payload["fundamental"]["materiality"]
    assert set(materiality["delta_ebitda_pct"]) == {"p10", "p50", "p90"}
    assert materiality["bucket"] in ("HIGH", "MEDIUM", "LOW", "NO_MATERIAL_IMPACT")
    assert 0.0 <= materiality["sign_consistency"] <= 1.0
    assert 1 <= len(materiality["driver_ranking"]) <= 3
    for driver in materiality["driver_ranking"]:
        assert set(driver) >= {"param", "contribution", "source", "point"}


def test_a_p50_never_appears_without_its_band(sensitivity_session):
    """DO NOT: do not present a p50 without its band in any user-facing
    surface."""
    from app.core.reducer import serialize_company_impact

    payload = serialize_company_impact(reduced_with_sensitivity(sensitivity_session))
    blob = json.dumps(payload)
    assert '"p50"' in blob
    for fragment in ('"p10"', '"p90"'):
        assert fragment in blob


def test_the_ui_contract_line_is_never_a_bare_number(sensitivity_session):
    from app.analysis.sensitivity.presentation import materiality_line

    impact = reduced_with_sensitivity(sensitivity_session)
    line = materiality_line(impact)
    assert "EBITDA" in line and "range" in line
    assert impact.net_effect in line
    assert "NEAR TERM" in line
    assert "Most sensitive to:" in line
    assert "%" in line


def test_the_ui_contract_line_refuses_an_impact_with_no_sensitivity_block():
    from app.analysis.sensitivity.presentation import materiality_line
    from tests.phase0 import fixtures as phase0_fixtures
    from app.core.reducer import reduce_company_impact

    impact = reduce_company_impact(
        phase0_fixtures.signals(phase0_fixtures.PRIMARY_COMPANY_ID),
        phase0_fixtures.reducer_config())
    with pytest.raises(ValueError):
        materiality_line(impact)
