"""TASK 2.4 -- the sign-consistency rule, wired into net-effect resolution.

    sign_consistency >= 0.90  -> directional claim permitted
    0.60 <= sc < 0.90         -> direction = UNCERTAIN, max tier SECONDARY_RIPPLE
    sc < 0.60 with material magnitude both sides -> MIXED

The thresholds come from `config/materiality.yaml` and from nowhere else.
The rule is ADDITIVE: a signal set that carries no sensitivity block (every
Phase 0 fixture, and the whole V4 path in production today) is reduced
exactly as before -- pinned below.
"""
import pytest

from tests.phase0 import fixtures as phase0_fixtures
from tests.phase2.conftest import FIXTURE_NOW

EVENT_ID = "fixture:phase2-sc"
ANALYSIS_VERSION = "v5:fixture:phase2:sc"
COMPANY_ID = 9201


def sensitivity_payload(*, p10, p50, p90, sign_consistency, bucket):
    return {
        "_fixture": True,
        "delta_ebitda_pct": {"p10": p10, "p50": p50, "p90": p90},
        "sign_consistency": sign_consistency,
        "bucket": bucket,
        "driver_ranking": [{"param": "pass_through", "contribution": 1.0,
                            "source": "DISCLOSED_CALL", "point": 0.4,
                            "evidence_id": "fixture-ev-1"}],
        "uncomputable_channels": [],
        "n": 2000, "seed": 1111, "attribution_method": "correlation_ratio_binned_v1",
        "engine_version": "sensitivity-v5.0.0", "evidence_grade_cap": None,
    }


def signal_set(*, sensitivity, direction="NEGATIVE", materiality="MEDIUM",
               evidence_grade="B", binding_status="BOUND"):
    from app.core.signals import make_signal

    def emit(stage, kind, payload, created_by):
        return make_signal(event_id=EVENT_ID, company_id=COMPANY_ID, stage=stage,
                           kind=kind, payload=payload, created_by=created_by,
                           analysis_version=ANALYSIS_VERSION, created_at=FIXTURE_NOW)

    return [
        emit("ENTITY", "ENTITY_RESOLUTION",
             {"ticker": "FIXSC.NS", "isin": "INF0000FIXTURE",
              "resolution": "RESOLVED", "entity_status": "ACTIVE"},
             "fixture:entity"),
        emit("DISCOVERY", "DISCOVERY",
             {"discovery_source": "MECHANISM", "directness": "DIRECT",
              "graph_distance": 1}, "fixture:discovery"),
        emit("SENSITIVITY", "CHANNEL", {
            "channel_id": "input_cost:fixture_input",
            "mechanism_id": "fixture:mechanism:1", "horizon": "NEAR_TERM",
            "direction": direction, "materiality": materiality,
            "evidence_ids": ["fixture-exp-C1"],
            "channel_type": "COST", "exposure_id": "fixture-exp-C1",
            "param_sources": {"pass_through": "DISCLOSED_CALL",
                              "hedge_ratio": "FILED"},
            "delta_ebitda_pct_p50": sensitivity["delta_ebitda_pct"]["p50"],
            "sensitivity": sensitivity,
        }, "sensitivity:v5"),
        emit("EVIDENCE", "EVIDENCE_BINDING",
             {"claim_id": "fixture:claim:1", "claim_type": "MATERIALITY",
              "binding_status": binding_status, "evidence_grade": evidence_grade,
              "evidence_ids": ["fixture-ev-1"]}, "fixture:evidence"),
        emit("EMPIRICAL", "EMPIRICAL_CHECK", {"status": "NO_DATA", "n_events": None},
             "empirical:not_available"),
    ]


def reduce(signals):
    from app.core.config_loader import load_gate_config, load_sensitivity_policy
    from app.core.reducer import EventContext, ReducerConfig, reduce_company_impact

    config = ReducerConfig(
        gate_config=load_gate_config(),
        event_context=EventContext(event_status="CONFIRMED",
                                   shock_magnitude_confidence=0.9,
                                   exposure_stale=False),
        sensitivity_policy=load_sensitivity_policy())
    return reduce_company_impact(signals, config)


# --- the three bands -------------------------------------------------------

def test_a_high_sign_consistency_permits_a_directional_claim():
    impact = reduce(signal_set(sensitivity=sensitivity_payload(
        p10=-6.0, p50=-3.2, p90=-1.1, sign_consistency=0.98, bucket="MEDIUM")))
    assert impact.net_effect == "NEGATIVE"
    assert impact.sign_consistency == 0.98
    assert impact.materiality_bucket == "MEDIUM"


def test_a_candidate_at_075_cannot_reach_primary_and_is_not_given_a_direction():
    impact = reduce(signal_set(sensitivity=sensitivity_payload(
        p10=-6.0, p50=-3.2, p90=1.5, sign_consistency=0.75, bucket="MEDIUM")))
    assert impact.net_effect == "UNCERTAIN"
    assert impact.publication_tier != "PRIMARY"


def test_a_candidate_at_055_with_material_magnitude_both_sides_publishes_mixed():
    impact = reduce(signal_set(sensitivity=sensitivity_payload(
        p10=-5.0, p50=-2.5, p90=5.0, sign_consistency=0.55, bucket="MEDIUM")))
    assert impact.net_effect == "MIXED"
    assert impact.net_effect not in ("POSITIVE", "NEGATIVE")
    assert impact.publication_tier != "PRIMARY"


def test_below_the_floor_without_material_magnitude_both_sides_is_uncertain_not_mixed():
    """MIXED is a claim that both sides are material. When they are not, the
    honest answer is UNCERTAIN."""
    impact = reduce(signal_set(sensitivity=sensitivity_payload(
        p10=-0.3, p50=-0.05, p90=0.2, sign_consistency=0.55,
        bucket="NO_MATERIAL_IMPACT")))
    assert impact.net_effect == "UNCERTAIN"


def test_the_bucket_comes_from_the_sensitivity_engine_not_from_the_channel_payload():
    """The channel payload says MEDIUM; the computed band says HIGH. The
    computed number wins -- that is the whole point of Phase 2."""
    impact = reduce(signal_set(
        sensitivity=sensitivity_payload(p10=-12.0, p50=-8.0, p90=-5.0,
                                        sign_consistency=1.0, bucket="HIGH"),
        materiality="MEDIUM"))
    assert impact.materiality_bucket == "HIGH"


def test_the_thresholds_are_the_deployed_yaml_ones():
    from app.core.config_loader import load_sensitivity_policy

    policy = load_sensitivity_policy()
    assert policy.directional_claim_min == 0.90
    assert policy.secondary_min == 0.60


def test_a_sensitivity_block_without_a_policy_fails_closed():
    """No hardcoded thresholds anywhere: if the policy is not configured, the
    reducer refuses rather than picking numbers."""
    from app.core.config_loader import load_gate_config
    from app.core.reducer import (
        EventContext, ReducerConfig, ReducerInputError, reduce_company_impact)

    config = ReducerConfig(gate_config=load_gate_config(),
                           event_context=EventContext(event_status="CONFIRMED"),
                           sensitivity_policy=None)
    with pytest.raises(ReducerInputError):
        reduce_company_impact(signal_set(sensitivity=sensitivity_payload(
            p10=-6.0, p50=-3.2, p90=-1.1, sign_consistency=0.98,
            bucket="MEDIUM")), config)


def test_two_conflicting_sensitivity_blocks_are_refused_not_averaged():
    signals = signal_set(sensitivity=sensitivity_payload(
        p10=-6.0, p50=-3.2, p90=-1.1, sign_consistency=0.98, bucket="MEDIUM"))
    signals += [s for s in signal_set(sensitivity=sensitivity_payload(
        p10=1.0, p50=2.0, p90=3.0, sign_consistency=0.91, bucket="MEDIUM"),
        direction="POSITIVE") if str(s.kind) == "CHANNEL"]

    from app.core.reducer import ReducerInputError

    with pytest.raises(ReducerInputError):
        reduce(signals)


# --- preservation: the rule does not touch signal sets without a block -----

def test_the_phase0_fixture_company_is_reduced_exactly_as_before():
    from app.core.reducer import reduce_company_impact

    impact = reduce_company_impact(
        phase0_fixtures.signals(phase0_fixtures.PRIMARY_COMPANY_ID),
        phase0_fixtures.reducer_config())
    assert impact.sensitivity is None
    assert impact.publication_tier == "PRIMARY"
    assert impact.net_effect in ("POSITIVE", "NEGATIVE")


def test_the_phase0_fixture_reduction_is_unchanged_with_a_policy_configured():
    """Configuring the sensitivity policy must not change a single byte of a
    reduction that carries no sensitivity block."""
    import json

    from app.core.config_loader import load_sensitivity_policy
    from app.core.reducer import (
        ReducerConfig, reduce_company_impact, serialize_company_impact)

    base = phase0_fixtures.reducer_config()
    with_policy = ReducerConfig(gate_config=base.gate_config,
                                event_context=base.event_context,
                                sensitivity_policy=load_sensitivity_policy())
    signals = phase0_fixtures.signals(phase0_fixtures.PRIMARY_COMPANY_ID)
    assert json.dumps(serialize_company_impact(
        reduce_company_impact(signals, base)), sort_keys=True) == json.dumps(
        serialize_company_impact(
            reduce_company_impact(signals, with_policy)), sort_keys=True)
