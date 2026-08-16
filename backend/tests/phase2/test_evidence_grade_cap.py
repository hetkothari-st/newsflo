"""FIX ROUND 1, C1 -- the parameter grade cap must actually stop something.

Phase 2 computed `evidence_grade_cap` (C for a SECTOR_PROXY parameter, D for
a MODELLED one), serialized it, and NOTHING consumed it. The reviewer's
demonstration: a company whose every parameter is a sector median, carrying an
A-graded claim binding, reached PRIMARY -- because the gate's
`forbidden_weakest_link_statuses: [SECTOR_PROXY, UNBOUND]` is written in the
CLAIM-BINDING vocabulary, and "SECTOR_PROXY" there is a homonym of the
PARAMETER-SOURCE value the sensitivity engine produces. Two vocabularies, one
spelling, no enforcement.

The fix is in the reducer, at `ImpactDraft` construction (`config/gates.yaml`
and `app/core/gates.py` are owned by a concurrent phase and are untouched):

  * the draft's `evidence_grade` is capped to at most the parameter cap --
    "at most" in BADNESS, so a cap never improves a grade;
  * when the DOMINANT driver (>50% of the attributed variance) is a
    SECTOR_PROXY parameter, the draft's `weakest_link` is set to
    `<param>:SECTOR_PROXY`, which the existing gate rule then refuses. That is
    the vocabulary bridge, made explicit and documented rather than relied on
    by accident.

Both tests below start from a signal set that really does reach PRIMARY, so
none of them is vacuous.
"""
import pytest

from tests.phase2.conftest import FIXTURE_NOW

EVENT_ID = "fixture:phase2-cap"
ANALYSIS_VERSION = "v5:fixture:phase2:cap"
COMPANY_ID = 9401


def block(*, cap=None, drivers=(("pass_through", 1.0, "FILED"),),
          p50=-8.0, sign_consistency=1.0, bucket="HIGH"):
    return {
        "_fixture": True,
        "delta_ebitda_pct": {"p10": p50 - 1.0, "p50": p50, "p90": p50 + 1.0},
        "sign_consistency": sign_consistency,
        "bucket": bucket,
        "driver_ranking": [
            {"param": name, "contribution": contribution, "source": source,
             "point": 0.4, "evidence_id": None}
            for name, contribution, source in drivers],
        "uncomputable_channels": [],
        "n": 2000, "seed": 1111,
        "attribution_method": "correlation_ratio_binned_v1",
        "engine_version": "sensitivity-v5.0.0", "evidence_grade_cap": cap,
    }


FILED_SOURCES = {"pass_through": "FILED", "hedge_ratio": "FILED"}
PROXY_SOURCES = {"pass_through": "SECTOR_PROXY", "hedge_ratio": "FILED"}
MODELLED_SOURCES = {"pass_through": "MODELLED", "hedge_ratio": "FILED"}


def signals(*, sensitivity, evidence_grade="A", materiality="HIGH",
            binding_status="BOUND", param_sources=None):
    from app.core.signals import make_signal

    def emit(stage, kind, payload, created_by):
        return make_signal(event_id=EVENT_ID, company_id=COMPANY_ID, stage=stage,
                           kind=kind, payload=payload, created_by=created_by,
                           analysis_version=ANALYSIS_VERSION, created_at=FIXTURE_NOW)

    return [
        emit("ENTITY", "ENTITY_RESOLUTION",
             {"ticker": "FIXCAP.NS", "isin": "INF0000FIXTURE",
              "resolution": "RESOLVED", "entity_status": "ACTIVE"}, "fixture:entity"),
        emit("DISCOVERY", "DISCOVERY",
             {"discovery_source": "MECHANISM", "directness": "DIRECT",
              "graph_distance": 1}, "fixture:discovery"),
        emit("SENSITIVITY", "CHANNEL", {
            "channel_id": "input_cost:fixture_input",
            "mechanism_id": "fixture:mechanism:1", "horizon": "NEAR_TERM",
            "direction": "NEGATIVE", "materiality": materiality,
            "evidence_ids": ["fixture-exp-1"], "channel_type": "COST",
            "exposure_id": "fixture-exp-1",
            "param_sources": dict(param_sources or FILED_SOURCES),
            "delta_ebitda_pct_p50": sensitivity["delta_ebitda_pct"]["p50"],
            "sensitivity": sensitivity}, "sensitivity:v5"),
        emit("EVIDENCE", "EVIDENCE_BINDING",
             {"claim_id": "fixture:claim:1", "claim_type": "MATERIALITY",
              "binding_status": binding_status, "evidence_grade": evidence_grade,
              "evidence_ids": ["fixture-ev-1"]}, "fixture:evidence"),
        emit("EMPIRICAL", "EMPIRICAL_CHECK", {"status": "NO_DATA", "n_events": None},
             "empirical:not_available"),
        # The verifier ran and sustained nothing -> verifier_status PASS, which
        # PRIMARY requires. Without this the set could never be primary and
        # every assertion below would be vacuous.
        emit("VERIFIER", "OBJECTION",
             {"objection_id": "fixture:verify", "type": "NOT_INDEPENDENTLY_VERIFIED",
              "severity": "MAJOR", "sustained": False}, "fixture:verifier"),
    ]


def reduce(signal_set):
    from app.core.config_loader import load_gate_config, load_sensitivity_policy
    from app.core.reducer import EventContext, ReducerConfig, reduce_company_impact

    return reduce_company_impact(signal_set, ReducerConfig(
        gate_config=load_gate_config(),
        event_context=EventContext(event_status="CONFIRMED",
                                   shock_magnitude_confidence=0.9,
                                   exposure_stale=False),
        sensitivity_policy=load_sensitivity_policy()))


# --- the control: this set really does reach PRIMARY ------------------------

def test_a_filed_only_company_still_reaches_primary_untouched():
    impact = reduce(signals(sensitivity=block(cap=None)))
    assert impact.publication_tier == "PRIMARY"
    assert impact.evidence_grade == "A"
    assert impact.weakest_link == "MATERIALITY:BOUND"


# --- the reviewer's demonstration, as a regression test ---------------------

def test_an_all_sector_proxy_reduction_cannot_publish_primary():
    impact = reduce(signals(sensitivity=block(
        cap="C", drivers=(("pass_through", 0.8, "SECTOR_PROXY"),
                          ("hedge_ratio", 0.2, "FILED"))),
        param_sources=PROXY_SOURCES))
    assert impact.publication_tier != "PRIMARY", (
        "a company whose dominant parameter is a sector median published a "
        "PRIMARY claim")
    assert impact.evidence_grade == "C"
    assert impact.weakest_link == "pass_through:SECTOR_PROXY"


def test_the_cap_demotes_a_medium_candidate_without_the_bridge_firing():
    """No driver DOMINATES, so the weakest-link bridge does not fire and the
    record keeps describing its claim binding. The cap still demotes:
    MEDIUM materiality needs grade A or B, and a capped grade is C."""
    impact = reduce(signals(
        sensitivity=block(cap="C", p50=-3.0, bucket="MEDIUM",
                          drivers=(("hedge_ratio", 0.6, "FILED"),
                                   ("pass_through", 0.4, "SECTOR_PROXY"))),
        materiality="MEDIUM", param_sources=PROXY_SOURCES))
    assert impact.evidence_grade == "C"
    assert impact.weakest_link == "MATERIALITY:BOUND", "no driver dominates"
    assert impact.publication_tier != "PRIMARY"


def test_the_same_candidate_without_a_cap_does_reach_primary():
    """Non-vacuity for the test above: everything else being equal, removing
    the cap restores PRIMARY."""
    impact = reduce(signals(
        sensitivity=block(cap=None, p50=-3.0, bucket="MEDIUM",
                          drivers=(("hedge_ratio", 0.6, "FILED"),)),
        materiality="MEDIUM"))
    assert impact.evidence_grade == "A"
    assert impact.publication_tier == "PRIMARY"


def test_a_cap_never_improves_a_grade():
    """`max` in badness, not in the alphabet: a D-graded binding stays D under
    a C cap."""
    impact = reduce(signals(sensitivity=block(cap="C"), evidence_grade="D",
                            param_sources=PROXY_SOURCES))
    assert impact.evidence_grade == "D"


def test_a_modelled_parameter_caps_at_d():
    """A MODELLED parameter is not a sector proxy, so only the CAP can
    demote this one -- D is outside PRIMARY's {A, B, C}."""
    impact = reduce(signals(sensitivity=block(cap="D"),
                            param_sources=MODELLED_SOURCES))
    assert impact.evidence_grade == "D"
    assert impact.publication_tier != "PRIMARY"


def test_an_unbound_weakest_link_is_not_overwritten_by_the_bridge():
    """UNBOUND is worse than SECTOR_PROXY. The bridge must not upgrade the
    record's description of its own weakest point."""
    impact = reduce(signals(
        sensitivity=block(cap="C", drivers=(("pass_through", 0.9, "SECTOR_PROXY"),)),
        binding_status="UNBOUND", param_sources=PROXY_SOURCES))
    assert impact.weakest_link == "MATERIALITY:UNBOUND"
    assert impact.publication_tier == "REJECTED"   # unbound claim, hard block


def test_the_capped_grade_and_bridged_link_are_serialized():
    from app.core.reducer import serialize_company_impact

    payload = serialize_company_impact(reduce(signals(
        sensitivity=block(cap="C",
                          drivers=(("pass_through", 0.8, "SECTOR_PROXY"),)),
        param_sources=PROXY_SOURCES)))
    assert payload["evidence"]["grade"] == "C"
    assert payload["evidence"]["weakest_link"] == "pass_through:SECTOR_PROXY"
    assert payload["fundamental"]["materiality"]["evidence_grade_cap"] == "C"


def test_a_signal_set_with_no_sensitivity_block_is_unaffected():
    from tests.phase0 import fixtures as phase0_fixtures
    from app.core.reducer import reduce_company_impact

    impact = reduce_company_impact(
        phase0_fixtures.signals(phase0_fixtures.PRIMARY_COMPANY_ID),
        phase0_fixtures.reducer_config())
    assert impact.publication_tier == "PRIMARY"
    # Its weakest link is still the CLAIM-binding one it always was; the
    # parameter bridge did not touch it.
    assert impact.weakest_link == "COST_EXPOSURE:BOUND"


@pytest.mark.parametrize("cap,grade,expected", [
    ("C", "A", "C"), ("C", "B", "C"), ("C", "C", "C"), ("C", "D", "D"),
    ("D", "A", "D"), ("D", "E", "E"), (None, "A", "A"),
])
def test_the_cap_is_a_worst_of_comparison(cap, grade, expected):
    from app.core.reducer import cap_evidence_grade

    assert cap_evidence_grade(grade, cap) == expected


def test_capping_an_unknown_grade_yields_the_cap():
    """A company with no graded binding at all, whose parameters are sector
    medians, is not ungraded -- it is at best the cap."""
    from app.core.reducer import cap_evidence_grade

    assert cap_evidence_grade(None, "C") == "C"
    assert cap_evidence_grade(None, None) is None
