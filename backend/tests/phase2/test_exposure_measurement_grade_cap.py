"""The exposure row's own measurement caps the channel's evidence grade.

WHY THIS TEST EXISTS. Before this, a channel's evidence grade was derived
only from its PARAMETERS. An exposure row could say `measurement =
'ESTIMATED'` -- meaning nobody found the share stated in a filing, it was
computed from components -- and if the pass-through and hedge parameters
above it happened to be FILED, the channel carried no grade cap at all and
was eligible for PRIMARY. The weakest link was not being read.

The crude ripple bootstrap made that concrete: eleven real rows whose shares
are ratios computed from two filing figures, several of them explicitly
lower bounds. `config/materiality.yaml`'s `exposure_measurement_grade_cap`
maps ESTIMATED and MODELLED to D; gates.yaml gives PRIMARY
`evidence_grades: [A, B, C]`, so those rows cannot lead a publication.

FILED and DISCLOSED_CALL are absent from that mapping on purpose: absent
means "caps nothing", so the key changes no pre-existing verdict.
"""
from tests.phase2.conftest import (
    case_by_id, cases, exposure_from_case, params_from_case, shock_from_case,
)

from app.analysis.sensitivity.channels import ExposureView, compute_channel
from app.analysis.sensitivity.config import load_materiality_config
from app.core.config_loader import load_gate_config


def _channel(measurement):
    case = case_by_id(cases_with_filed_params())
    exposure = exposure_from_case(case)
    return compute_channel(
        ExposureView(**{**exposure.__dict__, "measurement": measurement}),
        shock_from_case(case), params_from_case(case),
        int(case["shock"]["horizon_days"]))


def cases_with_filed_params() -> str:
    """A worked example whose parameters are all FILED, so any cap observed
    can only have come from the exposure measurement."""

    for case in cases():
        params = case.get("params") or {}
        if params and all(p["source"] == "FILED" for p in params.values()):
            return case["case_id"]
    raise AssertionError("no all-FILED worked example to isolate the axis on")


def test_a_filed_exposure_is_not_capped_by_this_axis():
    """The regression guard. Adding the key must not downgrade anything that
    was already fine."""
    assert _channel("FILED").grade_cap is None


def test_an_unstated_measurement_caps_nothing():
    """None means the caller did not say. Silence must not downgrade a row."""
    assert _channel(None).grade_cap is None


def test_an_estimated_exposure_caps_the_channel_at_d():
    assert _channel("ESTIMATED").grade_cap == "D"


def test_a_modelled_exposure_caps_the_channel_at_d():
    assert _channel("MODELLED").grade_cap == "D"


def test_grade_d_is_below_primary_and_admitted_by_secondary():
    """The cap is only worth setting if the gate acts on it. This asserts the
    DEPLOYED policy, not a copy of it."""
    config = load_gate_config()
    primary = config.primary
    ripple = config.secondary
    assert "D" not in (primary.evidence_grades or ())
    assert "D" in (ripple.evidence_grades or ())


def test_the_config_does_not_cap_filed_or_disclosed_call():
    """Stated as a test so a later edit that adds them is a deliberate act."""
    caps = load_materiality_config().exposure_measurement_grade_cap
    assert "FILED" not in caps and "DISCLOSED_CALL" not in caps
    assert caps["ESTIMATED"] == "D" and caps["MODELLED"] == "D"
