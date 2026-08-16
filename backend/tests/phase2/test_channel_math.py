"""TASK 2.1 -- channel computation, against 20 hand-computed worked examples.

Every expected value in `fixtures/worked_examples.json` was derived by hand,
step by step, in `.superpowers/sdd/2026-08-17-v5-session0/
phase2-worked-examples.md` (flagged PENDING-OWNER-VERIFICATION). The inputs
are obviously fake round numbers for a company that does not exist; nothing
here is a real elasticity, pass-through ratio, hedge ratio or cost share.

Tolerance is 0.1% relative, per the phase file. Cases whose expected value is
exactly zero are compared with an absolute tolerance instead -- a relative
tolerance around zero is not a test.
"""
from datetime import date

import pytest

from tests.phase2.conftest import (
    FIXTURE_TODAY, cases, case_by_id, exposure_from_case, load_worked_examples,
    make_company, params_from_case, seed_curve, seed_modifier, shock_from_case,
)

TOLERANCE = 0.001            # 0.1%, per the phase file
ABSOLUTE_TOLERANCE = 1.0     # 1 rupee, for the cases whose answer is exactly 0


def _assert_close(actual: float, expected: float, label: str) -> None:
    if expected == 0.0:
        assert abs(actual) <= ABSOLUTE_TOLERANCE, f"{label}: {actual} != 0"
    else:
        assert abs(actual - expected) <= abs(expected) * TOLERANCE, (
            f"{label}: {actual} != {expected}")


COMPUTABLE = [c for c in cases() if "expected_delta_ebitda_inr" in c]
UNCOMPUTABLE = [c for c in cases() if "expected_raises" in c]


def test_the_corpus_has_twenty_examples_spanning_every_channel_type():
    raw = load_worked_examples()
    assert len(raw["cases"]) == 20
    assert {c["channel_type"] for c in raw["cases"]} >= {
        "COST", "REVENUE_REALIZATION", "VOLUME_DEMAND", "FX_TRANSACTION",
        "FX_TRANSLATION", "INTEREST_RATE"}


@pytest.mark.parametrize("case", COMPUTABLE, ids=[c["case_id"] for c in COMPUTABLE])
def test_worked_example_reproduces_within_tolerance(case):
    from app.analysis.sensitivity.channels import compute_channel

    result = compute_channel(
        exposure_from_case(case), shock_from_case(case), params_from_case(case),
        horizon_days=int(case["shock"]["horizon_days"]))
    _assert_close(result.delta_ebitda_inr, float(case["expected_delta_ebitda_inr"]),
                  f"{case['case_id']} delta_ebitda_inr")


@pytest.mark.parametrize("case", COMPUTABLE, ids=[c["case_id"] for c in COMPUTABLE])
def test_worked_example_percentage_of_ebitda_reproduces(case):
    from app.analysis.sensitivity.channels import compute_channel

    ebitda = float(load_worked_examples()["ebitda_ttm_inr"]["value"])
    result = compute_channel(
        exposure_from_case(case), shock_from_case(case), params_from_case(case),
        horizon_days=int(case["shock"]["horizon_days"]))
    _assert_close(result.delta_ebitda_inr / ebitda * 100.0,
                  float(case["expected_delta_ebitda_pct"]),
                  f"{case['case_id']} delta_ebitda_pct")


def test_every_channel_result_carries_its_provenance():
    """Phase file Task 2.1: every ChannelResult carries exposure_id,
    evidence_ids, param_sources, horizon and mechanism_id."""
    from app.analysis.sensitivity.channels import compute_channel

    case = case_by_id("C1")
    result = compute_channel(
        exposure_from_case(case), shock_from_case(case), params_from_case(case),
        horizon_days=90)
    assert result.exposure_id == case["exposure"]["exposure_id"]
    assert result.evidence_ids == (case["exposure"]["exposure_id"],)
    assert result.param_sources == {"pass_through": "DISCLOSED_CALL",
                                    "hedge_ratio": "FILED"}
    assert result.horizon_days == 90
    assert result.horizon == "NEAR_TERM"
    assert result.mechanism_id == "fixture:mechanism:1"


def test_the_same_curve_at_a_shorter_horizon_hurts_more():
    """C1 and C6 are the same exposure and the same shock read off the same
    curve at 90 and 30 days. If pass-through were a scalar these would be
    equal -- the whole point of §4.2 is that they are not."""
    from app.analysis.sensitivity.channels import compute_channel

    near, later = (compute_channel(
        exposure_from_case(case_by_id(cid)), shock_from_case(case_by_id(cid)),
        params_from_case(case_by_id(cid)),
        horizon_days=int(case_by_id(cid)["shock"]["horizon_days"]))
        for cid in ("C6", "C1"))
    assert abs(near.delta_ebitda_inr) > abs(later.delta_ebitda_inr)


# --- missing parameters: raise, never default ------------------------------

@pytest.mark.parametrize("case", UNCOMPUTABLE, ids=[c["case_id"] for c in UNCOMPUTABLE])
def test_missing_parameter_raises_and_never_returns_a_default(case):
    from app.analysis.sensitivity.channels import compute_channel
    from app.analysis.sensitivity.params import InsufficientParameterData

    with pytest.raises(InsufficientParameterData):
        compute_channel(exposure_from_case(case), shock_from_case(case),
                        params_from_case(case),
                        horizon_days=int(case["shock"]["horizon_days"]))


def test_every_channel_type_refuses_to_run_with_no_parameters_at_all():
    """No channel type has a "reasonable default" branch: strip the params
    and each one raises."""
    from app.analysis.sensitivity.channels import CHANNEL_FOR_KIND, compute_channel
    from app.analysis.sensitivity.params import InsufficientParameterData

    seen = set()
    for case in COMPUTABLE:
        kind = case["exposure"]["exposure_kind"]
        if kind in seen:
            continue
        seen.add(kind)
        with pytest.raises(InsufficientParameterData):
            compute_channel(exposure_from_case(case), shock_from_case(case), {},
                            horizon_days=int(case["shock"]["horizon_days"]))
    assert seen == set(CHANNEL_FOR_KIND)


def test_an_exposure_kind_with_no_channel_formula_is_uncomputable():
    """REGULATORY / LOGISTICS_ENERGY / CUSTOMER_CONCENTRATION are real ledger
    kinds with no §5.1 formula. They must raise, not be approximated by the
    nearest formula that happens to typecheck."""
    from app.analysis.sensitivity.channels import ExposureView, compute_channel
    from app.analysis.sensitivity.params import InsufficientParameterData

    case = case_by_id("C1")
    exposure = exposure_from_case(case)
    for kind in ("REGULATORY", "LOGISTICS_ENERGY", "CUSTOMER_CONCENTRATION"):
        unmodelled = ExposureView(**{**exposure.__dict__, "exposure_kind": kind})
        with pytest.raises(InsufficientParameterData):
            compute_channel(unmodelled, shock_from_case(case),
                            params_from_case(case), horizon_days=90)


# --- SECTOR_PROXY: wider band, capped grade --------------------------------

def test_a_sector_proxy_parameter_widens_the_band_and_caps_the_grade():
    from app.analysis.sensitivity.channels import compute_channel

    case = case_by_id("P1")
    params = params_from_case(case)
    expected = case["expected_band"]
    proxy = params[expected["param"]]
    assert proxy.source == "SECTOR_PROXY"
    _assert_close(proxy.lo, float(expected["lo"]), "P1 band lo")
    _assert_close(proxy.hi, float(expected["hi"]), "P1 band hi")

    result = compute_channel(exposure_from_case(case), shock_from_case(case),
                             params, horizon_days=90)
    assert result.grade_cap == case["expected_grade_cap"]
    # The POINT estimate is untouched -- a sector proxy is not a different
    # number, it is a less certain one.
    _assert_close(result.delta_ebitda_inr,
                  float(case["expected_delta_ebitda_inr"]), "P1 delta")


def test_a_filed_parameter_is_banded_more_narrowly_than_a_sector_proxy():
    from app.analysis.sensitivity.params import dist_for

    filed = dist_for("pass_through", 0.4, "FILED")
    call = dist_for("pass_through", 0.4, "DISCLOSED_CALL")
    proxy = dist_for("pass_through", 0.4, "SECTOR_PROXY")
    assert (filed.hi - filed.lo) < (call.hi - call.lo) < (proxy.hi - proxy.lo)


def test_an_unknown_modifier_state_widens_the_band_further():
    """Phase 4 hook: the multiplier parameter is in place now."""
    from app.analysis.sensitivity.params import dist_for

    known = dist_for("pass_through", 0.4, "FILED")
    unknown = dist_for("pass_through", 0.4, "FILED", modifier_state_unknown=True)
    assert (unknown.hi - unknown.lo) > (known.hi - known.lo)


def test_a_bounded_parameter_band_is_clipped_to_its_bounds():
    """A pass-through of 1.3 is not a wider belief, it is a meaningless one."""
    from app.analysis.sensitivity.params import dist_for

    dist = dist_for("pass_through", 0.95, "SECTOR_PROXY")
    assert dist.hi <= 1.0 and dist.lo >= 0.0


# --- resolve_param: exactly three outcomes ---------------------------------

def test_resolve_param_returns_the_companys_own_value_when_the_ledger_has_one(
        sensitivity_session):
    from app.analysis.sensitivity.params import resolve_param

    company = make_company(sensitivity_session, ticker="FIXA.NS", name="FIXTURECO A")
    seed_curve(sensitivity_session, curve_id="fixture-curve-A",
               company_id=company.id, exposure_tag="input_cost:fixture_input",
               points=load_worked_examples()["pass_through_curve"]["points"],
               basis="DISCLOSED_CALL")

    resolved = resolve_param(sensitivity_session, company_id=company.id,
                             tag="input_cost:fixture_input",
                             param_name="pass_through", horizon_days=90,
                             as_of=FIXTURE_TODAY)
    assert resolved.dist.source == "DISCLOSED_CALL"
    _assert_close(resolved.dist.point, 0.4, "company curve at 90d")
    assert resolved.grade_cap is None


def test_resolve_param_falls_back_to_the_sector_median_and_caps_the_grade(
        sensitivity_session):
    """Outcome 2: no company value, but peers in the same sector have one.
    The median is computed from ledger rows AT RUNTIME -- there is no
    hardcoded sector table anywhere."""
    from app.analysis.sensitivity.params import resolve_param

    subject = make_company(sensitivity_session, ticker="FIXB.NS",
                           name="FIXTURECO B", sector="Fixture Sector")
    for index, hedge in enumerate((0.2, 0.4, 0.6)):
        peer = make_company(sensitivity_session, ticker=f"FIXP{index}.NS",
                            name=f"FIXTURECO PEER {index}", sector="Fixture Sector")
        seed_modifier(sensitivity_session, modifier_id=f"fixture-mod-{index}",
                      company_id=peer.id, applies_to_tag="input_cost:fixture_input",
                      modifier_kind="HEDGE",
                      parameters={"hedge_ratio": hedge, "measurement": "FILED"})

    resolved = resolve_param(sensitivity_session, company_id=subject.id,
                             tag="input_cost:fixture_input",
                             param_name="hedge_ratio", horizon_days=90,
                             as_of=FIXTURE_TODAY)
    assert resolved.dist.source == "SECTOR_PROXY"
    _assert_close(resolved.dist.point, 0.4, "sector median hedge ratio")
    assert resolved.grade_cap == "C"
    assert resolved.widened is True


def test_resolve_param_raises_when_nothing_is_available(sensitivity_session):
    """Outcome 3, and there is no outcome 4."""
    from app.analysis.sensitivity.params import (
        InsufficientParameterData, resolve_param)

    company = make_company(sensitivity_session, ticker="FIXC.NS", name="FIXTURECO C")
    with pytest.raises(InsufficientParameterData):
        resolve_param(sensitivity_session, company_id=company.id,
                      tag="input_cost:fixture_input", param_name="hedge_ratio",
                      horizon_days=90, as_of=FIXTURE_TODAY)


def test_resolve_param_raises_for_every_parameter_on_an_empty_ledger(
        sensitivity_session):
    from app.analysis.sensitivity.params import (
        InsufficientParameterData, RESOLVABLE_PARAMS, resolve_param)

    company = make_company(sensitivity_session, ticker="FIXD.NS", name="FIXTURECO D")
    for param_name in RESOLVABLE_PARAMS:
        with pytest.raises(InsufficientParameterData):
            resolve_param(sensitivity_session, company_id=company.id,
                          tag="input_cost:fixture_input", param_name=param_name,
                          horizon_days=90, as_of=FIXTURE_TODAY)


def test_a_modifier_row_that_does_not_say_how_it_was_measured_is_unusable(
        sensitivity_session):
    """FILED and DISCLOSED_CALL band differently. A row that cannot say which
    it is cannot be banded, so it is not used -- rather than being banded as
    the more favourable of the two."""
    from app.analysis.sensitivity.params import (
        InsufficientParameterData, resolve_param)

    company = make_company(sensitivity_session, ticker="FIXE.NS", name="FIXTURECO E")
    seed_modifier(sensitivity_session, modifier_id="fixture-mod-nomeasure",
                  company_id=company.id, applies_to_tag="input_cost:fixture_input",
                  modifier_kind="HEDGE", parameters={"hedge_ratio": 0.5})
    with pytest.raises(InsufficientParameterData):
        resolve_param(sensitivity_session, company_id=company.id,
                      tag="input_cost:fixture_input", param_name="hedge_ratio",
                      horizon_days=90, as_of=FIXTURE_TODAY)


def test_an_expired_modifier_is_not_used(sensitivity_session):
    from app.analysis.sensitivity.params import (
        InsufficientParameterData, resolve_param)

    from sqlalchemy import text

    company = make_company(sensitivity_session, ticker="FIXF.NS", name="FIXTURECO F")
    seed_modifier(sensitivity_session, modifier_id="fixture-mod-expired",
                  company_id=company.id, applies_to_tag="input_cost:fixture_input",
                  modifier_kind="HEDGE",
                  parameters={"hedge_ratio": 0.5, "measurement": "FILED"},
                  effective_from=date(2225, 1, 1))
    sensitivity_session.execute(text(
        "UPDATE company_modifier SET effective_to = '2225-12-31'"))
    with pytest.raises(InsufficientParameterData):
        resolve_param(sensitivity_session, company_id=company.id,
                      tag="input_cost:fixture_input", param_name="hedge_ratio",
                      horizon_days=90, as_of=FIXTURE_TODAY)


def test_the_curve_is_interpolated_not_snapped():
    from app.analysis.sensitivity.params import evaluate_curve

    points = load_worked_examples()["pass_through_curve"]["points"]
    _assert_close(evaluate_curve(points, 0), 0.0, "curve at 0")
    _assert_close(evaluate_curve(points, 30), 0.25, "curve at 30")
    _assert_close(evaluate_curve(points, 90), 0.4, "curve at 90")
    # Halfway between the 30d and 90d points.
    _assert_close(evaluate_curve(points, 60), 0.325, "curve at 60")
    # Beyond the last point the curve is flat, never extrapolated upward.
    _assert_close(evaluate_curve(points, 400), 0.4, "curve beyond the last point")
