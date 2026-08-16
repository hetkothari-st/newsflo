"""The credibility test (phase file TESTS/test_upstream_realization.py).

    "Publishing 'ONGC POSITIVE' on rising crude while ignoring the windfall
     levy and APM ceiling is an instant credibility loss." -- spec §9

The company here is a fixture, the levy is a fixture, and the threshold is a
round 100 in no unit at all. What is NOT a fixture is the behaviour: a
registered THRESHOLD_CAPTURE modifier in force on the analysis date must
materially cap the realisation upside, and repealing it (setting
`effective_to`) must restore it -- with no code change and no re-analysis.
"""
import pytest

from tests.phase4.helpers import upstream_impact


def _band(impact):
    return impact.sensitivity["delta_ebitda_pct"]


def test_the_naive_call_is_positive_and_high_without_the_levy():
    """The control. Without the modifier the fixture prints exactly the
    over-confident call the phase file names."""
    impact = upstream_impact(levy_active=False)
    assert impact.net_effect == "POSITIVE"
    assert impact.materiality_bucket == "HIGH"
    # 10,000,000,000 x 1.0 x 0.06 x 1.0 x (1 - 0.0) = +600,000,000
    # over an EBITDA of 5,000,000,000 -> +12%
    assert _band(impact)["p50"] == pytest.approx(12.0, abs=0.5)
    assert impact.policy_modifiers_applied == ()


def test_with_the_levy_active_the_upside_is_materially_capped():
    """The whole of the fixture move sits above the fixture threshold and the
    fixture captures nine tenths of it, so +12% becomes +1.2%: still positive,
    no longer HIGH, and no longer a call anybody would make naively."""
    impact = upstream_impact(levy_active=True)

    assert impact.materiality_bucket != "HIGH"
    assert _band(impact)["p50"] == pytest.approx(1.2, abs=0.2)
    assert not (impact.net_effect == "POSITIVE"
                and impact.materiality_bucket == "HIGH"), (
        "the naive POSITIVE-HIGH call printed with a levy in force")


def test_with_the_levy_repealed_the_full_upside_restores():
    """`effective_to` in the past is the ONLY thing that changes."""
    capped = upstream_impact(levy_active=True)
    restored = upstream_impact(levy_active=False)

    assert abs(_band(restored)["p50"]) > abs(_band(capped)["p50"]) * 5
    assert restored.materiality_bucket == "HIGH"
    assert restored.net_effect == "POSITIVE"
    assert "FIXTURE_LEVY_UPSTREAM" not in restored.policy_modifiers_applied


def test_the_levy_is_surfaced_rather_than_silently_folded_in():
    """Task 4.2: "Showing the user you modelled the windfall levy is worth
    more than the impact call itself." A capped number with no explanation is
    indistinguishable from a small number."""
    impact = upstream_impact(levy_active=True)
    assert impact.policy_modifiers_applied == ("FIXTURE_LEVY_UPSTREAM",)
    chip = impact.policy_modifiers_detail[0]
    assert chip["modifier_id"] == "FIXTURE_LEVY_UPSTREAM"
    assert chip["modifier_type"] == "THRESHOLD_CAPTURE"
    assert chip["source_url"]
    assert chip["status"] == "APPLIED"


def test_the_cap_narrows_the_band_it_does_not_only_move_the_midpoint():
    """A transfer function scales the WHOLE distribution, so the band is
    computed under the levy rather than bolted on after it."""
    capped = upstream_impact(levy_active=True)
    restored = upstream_impact(levy_active=False)
    capped_width = _band(capped)["p90"] - _band(capped)["p10"]
    restored_width = _band(restored)["p90"] - _band(restored)["p10"]
    assert capped_width < restored_width


def test_the_modifier_is_not_applied_twice_when_the_reduction_is_replayed():
    """Idempotence of the record: reducing the same signals again yields the
    same trace id and the same single modifier entry."""
    first = upstream_impact(levy_active=True)
    second = upstream_impact(levy_active=True)
    assert first.decision_trace_id == second.decision_trace_id
    assert first.policy_modifiers_applied == second.policy_modifiers_applied
