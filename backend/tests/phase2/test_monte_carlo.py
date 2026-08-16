"""TASK 2.3 -- Monte Carlo, determinism, and driver attribution.

Nothing here touches a database or a clock. Channels are built from the
`_fixture`-marked worked-example corpus.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.phase2.conftest import (
    case_by_id, exposure_from_case, load_worked_examples, params_from_case,
    shock_from_case,
)

EBITDA = 2000000000.0
EVENT_ID = "fixture:phase2-shock-1"
COMPANY_ID = 9101
ANALYSIS_VERSION = "v5:fixture:phase2:deadbeef"


def channel(case_id: str):
    from app.analysis.sensitivity.channels import compute_channel

    case = case_by_id(case_id)
    return compute_channel(exposure_from_case(case), shock_from_case(case),
                           params_from_case(case),
                           horizon_days=int(case["shock"]["horizon_days"]))


def simulate(channels, **kwargs):
    from app.analysis.sensitivity.monte_carlo import simulate as run

    kwargs.setdefault("seed", None)
    return run(channels, ebitda_ttm_inr=EBITDA, event_id=EVENT_ID,
               company_id=COMPANY_ID, analysis_version=ANALYSIS_VERSION, **kwargs)


# --- determinism -----------------------------------------------------------

def test_the_same_event_company_version_yields_a_byte_identical_band():
    from app.analysis.sensitivity.monte_carlo import serialize_materiality

    channels = [channel("C1")]
    first = json.dumps(serialize_materiality(simulate(channels)), sort_keys=True)
    second = json.dumps(serialize_materiality(simulate(channels)), sort_keys=True)
    assert first == second


def test_the_band_is_byte_identical_in_a_SEPARATE_process():
    """`hash()` is salted per process in Python. A seed derived from it would
    pass the in-process test above and silently change on every deploy."""
    from app.analysis.sensitivity.monte_carlo import serialize_materiality

    in_process = json.dumps(serialize_materiality(simulate([channel("C1")])),
                            sort_keys=True)
    backend = Path(__file__).resolve().parents[2]
    script = (
        "import json;"
        "from tests.phase2.test_monte_carlo import channel, simulate;"
        "from app.analysis.sensitivity.monte_carlo import serialize_materiality;"
        "print(json.dumps(serialize_materiality(simulate([channel('C1')])),"
        " sort_keys=True))")
    completed = subprocess.run([sys.executable, "-c", script], cwd=backend,
                               capture_output=True, text=True, timeout=180)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip().splitlines()[-1] == in_process


def test_a_different_company_gets_a_different_seed():
    from app.analysis.sensitivity.monte_carlo import stable_hash

    assert stable_hash(EVENT_ID, COMPANY_ID, ANALYSIS_VERSION) != stable_hash(
        EVENT_ID, COMPANY_ID + 1, ANALYSIS_VERSION)
    assert stable_hash(EVENT_ID, COMPANY_ID, ANALYSIS_VERSION) != stable_hash(
        EVENT_ID, COMPANY_ID, ANALYSIS_VERSION + "x")


def test_the_seed_is_stable_across_processes():
    from app.analysis.sensitivity.monte_carlo import stable_hash

    expected = stable_hash(EVENT_ID, COMPANY_ID, ANALYSIS_VERSION)
    backend = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [sys.executable, "-c",
         "from app.analysis.sensitivity.monte_carlo import stable_hash;"
         f"print(stable_hash({EVENT_ID!r}, {COMPANY_ID}, {ANALYSIS_VERSION!r}))"],
        cwd=backend, capture_output=True, text=True, timeout=180)
    assert completed.returncode == 0, completed.stderr
    assert int(completed.stdout.strip().splitlines()[-1]) == expected


def test_the_default_draw_count_comes_from_config_and_is_two_thousand():
    from app.analysis.sensitivity.config import load_materiality_config

    assert load_materiality_config().monte_carlo_n == 2000
    assert simulate([channel("C1")]).n == 2000


# --- sign consistency ------------------------------------------------------

def test_sign_consistency_is_one_when_every_parameter_shares_a_sign():
    """C1 is a cost channel with a positive shock and bounded [0,1]
    parameters: no draw can flip it positive."""
    result = simulate([channel("C1")])
    assert result.sign_consistency == 1.0
    assert result.delta_ebitda_pct.p50 < 0


def test_sign_consistency_collapses_when_the_band_straddles_zero_symmetrically():
    """A realization elasticity nobody can sign: the draws land either side of
    zero in equal measure, and the system must not call that a direction."""
    from app.analysis.sensitivity.channels import compute_channel
    from app.analysis.sensitivity.params import ParamDist

    case = case_by_id("R1")
    straddle = compute_channel(
        exposure_from_case(case), shock_from_case(case), {
            "realization_elasticity": ParamDist(
                name="realization_elasticity", point=0.0, lo=-1.0, hi=1.0,
                dist="uniform", source="SECTOR_PROXY", evidence_id=None),
            "regulatory_capture_fraction": ParamDist(
                name="regulatory_capture_fraction", point=0.0, lo=0.0, hi=0.0,
                dist="uniform", source="FILED", evidence_id="fixture-ev-1"),
        }, horizon_days=90)
    result = simulate([straddle])
    assert result.sign_consistency < 0.6


# --- buckets ---------------------------------------------------------------

@pytest.mark.parametrize("case_id,expected_bucket", [
    ("C3", "HIGH"),      # +15.0% of EBITDA
    ("C4", "MEDIUM"),    # -2.4%
    ("V1", "LOW"),       # -1.8% ... LOW starts at 0.5, MEDIUM at 2.0
    ("I2", "NO_MATERIAL_IMPACT"),   # -0.25%
])
def test_bucketing_follows_config(case_id, expected_bucket):
    assert simulate([channel(case_id)]).bucket == expected_bucket


def test_bucket_thresholds_are_read_from_the_yaml_not_the_code():
    import app.analysis.sensitivity.monte_carlo as monte_carlo
    from app.analysis.sensitivity.config import load_materiality_config

    config = load_materiality_config()
    assert config.buckets["HIGH"] == 5.0
    assert config.buckets["MEDIUM"] == 2.0
    assert config.buckets["LOW"] == 0.5
    source = Path(monte_carlo.__file__).read_text(encoding="utf-8")
    for literal in ("5.0", "2.0", "0.5", "0.90", "0.60"):
        assert f"= {literal}" not in source, (
            f"{literal} is hardcoded in monte_carlo.py -- config/materiality."
            "yaml is the single source of truth")


# --- driver attribution ----------------------------------------------------

def test_driver_ranking_sums_to_one_and_finds_the_injected_dominant_parameter():
    """One parameter is given a wide band and the others narrow ones; the
    attribution must point at it."""
    from app.analysis.sensitivity.channels import compute_channel
    from app.analysis.sensitivity.params import ParamDist

    case = case_by_id("C1")
    dominant = ParamDist(name="pass_through", point=0.5, lo=0.05, hi=0.95,
                         dist="triangular", source="SECTOR_PROXY", evidence_id=None)
    minor = ParamDist(name="hedge_ratio", point=0.5, lo=0.49, hi=0.51,
                      dist="triangular", source="FILED", evidence_id="fixture-ev-1")
    result = simulate([compute_channel(
        exposure_from_case(case), shock_from_case(case),
        {"pass_through": dominant, "hedge_ratio": minor}, horizon_days=90)])

    assert result.driver_ranking, "driver_ranking is a product feature, not a log line"
    assert abs(sum(d.contribution for d in result.driver_ranking) - 1.0) < 0.01
    assert result.driver_ranking[0].param == "pass_through"
    assert result.driver_ranking[0].contribution > 0.5
    # Every driver states where its value came from -- an analyst who
    # disagrees must be able to see which lever to argue with.
    assert {d.source for d in result.driver_ranking} == {"SECTOR_PROXY", "FILED"}


def test_the_attribution_estimator_is_named_and_versioned():
    from app.analysis.sensitivity.monte_carlo import (
        ATTRIBUTION_METHOD, ENGINE_VERSION)

    assert ATTRIBUTION_METHOD.startswith("correlation_ratio")
    assert ATTRIBUTION_METHOD.endswith("_v1")
    assert simulate([channel("C1")]).attribution_method == ATTRIBUTION_METHOD
    assert ENGINE_VERSION.startswith("sensitivity-v5")


def test_a_channel_with_no_uncertainty_at_all_ranks_no_drivers():
    """Zero-width bands: every draw is the same number. Attribution over zero
    variance must report nothing rather than dividing by zero."""
    from app.analysis.sensitivity.channels import compute_channel
    from app.analysis.sensitivity.params import ParamDist

    case = case_by_id("C1")
    certain = {
        name: ParamDist(name=name, point=point, lo=point, hi=point,
                        dist="triangular", source="FILED", evidence_id=None)
        for name, point in (("pass_through", 0.4), ("hedge_ratio", 0.5))}
    result = simulate([compute_channel(exposure_from_case(case),
                                       shock_from_case(case), certain,
                                       horizon_days=90)])
    assert result.driver_ranking == ()
    band = result.delta_ebitda_pct
    assert band.p10 == band.p50 == band.p90


def test_a_filed_point_of_one_is_still_banded_below_one():
    """C5's point estimate is exactly zero (fully hedged), but a filed 100%
    hedge is a disclosure with a band like any other -- so the Monte Carlo
    median is NOT the point estimate, and the band is what the user sees."""
    result = simulate([channel("C5")])
    assert result.delta_ebitda_pct.p90 <= 0.0
    assert result.delta_ebitda_pct.p10 < result.delta_ebitda_pct.p90


# --- uncomputable channels and abstention ----------------------------------

def test_uncomputable_channels_are_carried_through_to_the_result():
    from app.analysis.sensitivity.channels import UncomputableChannel

    missing = UncomputableChannel("input_cost:fixture_missing", "MISSING_ROW",
                                  "hedge_ratio")
    result = simulate([channel("C1")], uncomputable_channels=(missing,))
    assert result.uncomputable_channels == (missing,)


def test_no_channels_at_all_is_not_a_zero_impact_claim():
    from app.analysis.sensitivity.params import InsufficientParameterData

    with pytest.raises(InsufficientParameterData):
        simulate([])


def test_a_missing_ebitda_base_raises_rather_than_dividing_by_something_invented():
    from app.analysis.sensitivity.monte_carlo import simulate as run
    from app.analysis.sensitivity.params import InsufficientParameterData

    for ebitda in (None, 0.0):
        with pytest.raises(InsufficientParameterData):
            run([channel("C1")], ebitda_ttm_inr=ebitda, event_id=EVENT_ID,
                company_id=COMPANY_ID, analysis_version=ANALYSIS_VERSION)


def test_percentiles_are_ordered_and_the_worked_example_point_sits_inside_them():
    case = case_by_id("C1")
    result = simulate([channel("C1")])
    band = result.delta_ebitda_pct
    assert band.p10 <= band.p50 <= band.p90
    assert band.p10 < float(case["expected_delta_ebitda_pct"]) < band.p90


def test_the_grade_cap_of_the_weakest_parameter_reaches_the_result():
    """The cap TRAVELS with the number -- which is all this test checks.

    CORRECTION (fix round 1): this docstring used to say "sector proxies must
    not reach PRIMARY", which implied an enforcement that did not exist
    anywhere. Carrying a cap and honouring it are different things; the
    honouring is now done in the reducer and is pinned by
    `tests/phase2/test_evidence_grade_cap.py`.
    """
    assert simulate([channel("P1")]).evidence_grade_cap == "C"
    assert simulate([channel("C1")]).evidence_grade_cap is None


# --- FIX ROUND 1 -----------------------------------------------------------

def test_the_band_does_not_depend_on_the_order_the_caller_passes_channels(
        ):
    """M4. Floating-point addition is not associative, so summing the
    channels in the caller's order made the published band depend on an
    iteration order nobody controls."""
    from app.analysis.sensitivity.monte_carlo import serialize_materiality

    channels = [channel("C1"), channel("R1"), channel("V1")]
    forward = json.dumps(serialize_materiality(simulate(channels)), sort_keys=True)
    reverse = json.dumps(serialize_materiality(simulate(list(reversed(channels)))),
                         sort_keys=True)
    assert forward == reverse


def test_the_materiality_bases_of_the_channels_reach_the_result():
    """Concern 4b. An interest-line effect is not an EBITDA effect, and the
    result has to say which it is carrying."""
    assert simulate([channel("C1")]).materiality_bases == ("EBITDA",)
    assert simulate([channel("I1")]).materiality_bases == ("PRE_TAX_INTEREST_LINE",)
    assert simulate([channel("C1"), channel("I1")]).materiality_bases == (
        "EBITDA", "PRE_TAX_INTEREST_LINE")


def test_the_serialized_block_carries_the_bases():
    from app.analysis.sensitivity.monte_carlo import serialize_materiality

    payload = serialize_materiality(simulate([channel("I1")]))
    assert payload["materiality_bases"] == ["PRE_TAX_INTEREST_LINE"]
