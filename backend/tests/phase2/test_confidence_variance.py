"""REGRESSION GUARD against the V4 near-constant-confidence bug.

V4's defect was not that its materiality was wrong -- it was that every
candidate got nearly the same one, so the number carried no information. A
computed materiality has to MOVE with the inputs.

The corpus is the 19 computable worked examples (obviously fake, all
`_fixture`-marked). The thresholds here are TEST policy, not product policy:
they say "these numbers must differ", not "this is what a company is worth".
"""
import statistics

from tests.phase2.conftest import (
    cases, exposure_from_case, load_worked_examples, params_from_case,
    shock_from_case,
)

# A corpus this diverse producing a standard deviation below this would mean
# the engine is not reading its inputs.
MIN_STDEV_PCT = 1.0
MIN_DISTINCT_BUCKETS = 3

EVENT_ID = "fixture:phase2-corpus"
ANALYSIS_VERSION = "v5:fixture:phase2:corpus"


def corpus_results():
    from app.analysis.sensitivity.channels import compute_channel
    from app.analysis.sensitivity.monte_carlo import simulate

    ebitda = float(load_worked_examples()["ebitda_ttm_inr"]["value"])
    results = []
    for case in cases():
        if "expected_delta_ebitda_inr" not in case:
            continue
        channel = compute_channel(
            exposure_from_case(case), shock_from_case(case), params_from_case(case),
            horizon_days=int(case["shock"]["horizon_days"]))
        results.append((case["case_id"], simulate(
            [channel], ebitda_ttm_inr=ebitda, event_id=EVENT_ID,
            company_id=int(case["exposure"]["company_id"]),
            analysis_version=ANALYSIS_VERSION)))
    return results


def test_materiality_across_the_corpus_is_not_near_constant():
    values = [result.delta_ebitda_pct.p50 for _, result in corpus_results()]
    assert len(values) >= 15
    assert statistics.pstdev(values) > MIN_STDEV_PCT, (
        f"materiality p50 stdev is {statistics.pstdev(values):.4f} -- the V4 "
        "near-constant-confidence bug has returned")


def test_the_corpus_lands_in_several_different_buckets():
    buckets = {result.bucket for _, result in corpus_results()}
    assert len(buckets) >= MIN_DISTINCT_BUCKETS, buckets
    assert "NO_MATERIAL_IMPACT" in buckets, (
        "a corpus where nothing is immaterial is a corpus that cannot say no")


def test_two_companies_with_different_exposure_get_different_numbers():
    """The specific V4 symptom: identical materiality for candidates whose
    exposure is plainly different."""
    results = dict(corpus_results())
    assert results["C1"].delta_ebitda_pct.p50 != results["C4"].delta_ebitda_pct.p50
    assert results["C1"].bucket != results["I2"].bucket


def test_the_band_width_moves_with_the_evidence_quality():
    """A sector-proxied parameter must produce a WIDER band than the same
    point value read off a company disclosure (P1 vs C1). Identical bands
    would mean the uncertainty is decorative."""
    results = dict(corpus_results())
    filed = results["C1"].delta_ebitda_pct
    proxied = results["P1"].delta_ebitda_pct
    assert (proxied.p90 - proxied.p10) > (filed.p90 - filed.p10)
