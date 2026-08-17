"""TASK 5.1 -- the event-study transmission matrix.

The phase file's mandatory tests:
  - CAR computation matches a hand-computed fixture
  - thin-trading and corporate-action edge cases handled
  - estimator version recorded on every row

The arithmetic every assertion here checks is written out in
.superpowers/sdd/2026-08-17-v5-session0/phase5-estimator-design.md §4, so a
reviewer can verify the estimator on paper before trusting a single row.

ZERO NETWORK. This module computes over a `ReturnHistory` handed to it. It
fetches nothing, ever -- asserted by an ast scan, because "we would never do
that" is not a guarantee.
"""
import ast
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.phase5.conftest import (
    BACKEND, FIXTURE_COMPANY_ID, FIXTURE_EVENT_DAY, FIXTURE_NOW,
    FIXTURE_VARIABLE, code_lines, load_fixture,
)
from tests.phase5.helpers import (
    hand_computed_history, levels_from_moves, tiny_policy,
)

EMPIRICAL = BACKEND / "app" / "analysis" / "empirical"
EVENT_STUDY = EMPIRICAL / "event_study.py"

BANNED_NETWORK_MODULES = (
    "yfinance", "requests", "httpx", "urllib", "urllib3", "socket", "aiohttp",
    "http", "ftplib", "telnetlib", "smtplib",
)


# --- zero network -----------------------------------------------------------

def test_the_event_study_imports_nothing_that_opens_a_socket():
    tree = ast.parse(EVENT_STUDY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            assert name.split(".")[0] not in BANNED_NETWORK_MODULES, (
                f"event_study.py imports {name}: it never fetches a price -- "
                "it computes over a ReturnHistory handed to it")


def test_the_event_study_reads_no_clock():
    """`computed_at` is supplied by the caller. A module that reads a clock
    cannot be replayed, and a transmission matrix that changes when you rerun
    it is not evidence."""
    for number, line in code_lines(EVENT_STUDY):
        assert "now(" not in line and "utcnow" not in line, \
            f"event_study.py:{number} reads a clock: {line.strip()}"


def test_the_protocol_lives_outside_app_market():
    """Task 5.5's import ban must cost the estimator nothing."""
    from app.analysis.empirical import event_study

    assert event_study.__name__.startswith("app.analysis.empirical")
    assert hasattr(event_study, "ReturnHistory")


# --- the estimator ----------------------------------------------------------

def test_the_market_model_recovers_the_fixture_alpha_and_beta():
    from app.analysis.empirical.event_study import fit_market_model

    model = fit_market_model(hand_computed_history(), company_id=FIXTURE_COMPANY_ID,
                             event_day=FIXTURE_EVENT_DAY, policy=tiny_policy())
    assert model is not None
    assert model.beta == pytest.approx(1.5, abs=1e-12)
    assert model.alpha == pytest.approx(0.001, abs=1e-12)
    assert model.n_days >= 120


@pytest.mark.parametrize("horizon,expected", [
    ("1d", -0.0005), ("5d", 0.0015), ("20d", 0.0015)])
def test_car_matches_the_hand_computed_fixture(horizon, expected):
    from app.analysis.empirical.event_study import estimate_car

    results = estimate_car(hand_computed_history(), company_id=FIXTURE_COMPANY_ID,
                           event_day=FIXTURE_EVENT_DAY, policy=tiny_policy())
    result = results[horizon]
    assert result.abstain_reason is None
    assert result.car == pytest.approx(expected, abs=1e-12)
    assert result.car == pytest.approx(
        load_fixture("car_hand_computed.json")["event_window"]["expected_car"][horizon],
        abs=1e-12)


def test_the_estimator_version_is_recorded_on_every_car():
    from app.analysis.empirical.event_study import CAR_ESTIMATOR_VERSION, estimate_car

    results = estimate_car(hand_computed_history(), company_id=FIXTURE_COMPANY_ID,
                           event_day=FIXTURE_EVENT_DAY, policy=tiny_policy())
    assert results
    for result in results.values():
        assert result.estimator_version == CAR_ESTIMATOR_VERSION


def test_the_car_price_history_adapter_agrees_with_the_estimator():
    """Task 3.5's reverse study and Task 5.1's forward study must compute a
    CAR the same way, or the blind-spot detector and the cross-check disagree
    about what history said."""
    from app.analysis.empirical.event_study import CarPriceHistory, estimate_car

    direct = estimate_car(hand_computed_history(), company_id=FIXTURE_COMPANY_ID,
                          event_day=FIXTURE_EVENT_DAY, policy=tiny_policy())
    adapter = CarPriceHistory(hand_computed_history(), policy=tiny_policy())
    assert adapter.cumulative_abnormal_return(
        FIXTURE_COMPANY_ID, FIXTURE_EVENT_DAY, 5) == pytest.approx(
            direct["5d"].car, abs=1e-12)


# --- the four edge cases ----------------------------------------------------

def test_a_company_that_had_not_listed_abstains_rather_than_returning_zero():
    from app.analysis.empirical.event_study import estimate_car

    results = estimate_car(hand_computed_history(not_listed=True),
                           company_id=FIXTURE_COMPANY_ID,
                           event_day=FIXTURE_EVENT_DAY, policy=tiny_policy())
    for result in results.values():
        assert result.car is None
        assert result.abstain_reason == "INSUFFICIENT_ESTIMATION_WINDOW"


def test_a_thinly_traded_name_abstains_rather_than_estimating_on_stale_prints():
    from app.analysis.empirical.event_study import estimate_car

    results = estimate_car(hand_computed_history(thin=True),
                           company_id=FIXTURE_COMPANY_ID,
                           event_day=FIXTURE_EVENT_DAY, policy=tiny_policy())
    for result in results.values():
        assert result.car is None
        assert result.abstain_reason == "INSUFFICIENT_ESTIMATION_WINDOW"


def test_a_corporate_action_inside_the_event_window_voids_the_car():
    """A split print is a -50% return that never happened. The window cannot
    be summed with a hole in it, and the hole is never zero-filled."""
    from app.analysis.empirical.event_study import estimate_car

    results = estimate_car(hand_computed_history(corporate_action_offset=3),
                           company_id=FIXTURE_COMPANY_ID,
                           event_day=FIXTURE_EVENT_DAY, policy=tiny_policy())
    assert results["5d"].car is None
    assert results["5d"].abstain_reason == "MISSING_RETURN_IN_EVENT_WINDOW"
    # +1d closes before the action and is unaffected: an edge case handled is
    # not an edge case that poisons everything near it.
    assert results["1d"].car == pytest.approx(-0.0005, abs=1e-12)


def test_a_corporate_action_inside_the_estimation_window_is_dropped_not_fatal():
    from app.analysis.empirical.event_study import estimate_car

    results = estimate_car(hand_computed_history(estimation_gap_offset=-100),
                           company_id=FIXTURE_COMPANY_ID,
                           event_day=FIXTURE_EVENT_DAY, policy=tiny_policy())
    assert results["5d"].car == pytest.approx(0.0015, abs=1e-12)


def test_a_stale_print_in_the_event_window_is_not_summed_as_a_zero_reaction():
    """REVIEW ROUND 1 (I-2). A day that did not trade carries the previous
    close forward, so the feed reports `traded=False` with a well-formed
    `return_pct = 0.0`. Summing it would report "the company did not react" on
    a day the company COULD not react -- and it would pass a None check.

    Refuse, do not correct: dropping the day would silently shorten the
    horizon, so a "5-day" CAR would be computed over four sessions.
    """
    from app.analysis.empirical.event_study import (
        ABSTAIN_THIN_EVENT_WINDOW, estimate_car,
    )

    results = estimate_car(hand_computed_history(stale_print_offsets=(2,)),
                           company_id=FIXTURE_COMPANY_ID,
                           event_day=FIXTURE_EVENT_DAY, policy=tiny_policy())
    assert results["5d"].car is None, (
        "a stale print was summed as a genuine zero abnormal return")
    assert results["5d"].abstain_reason == ABSTAIN_THIN_EVENT_WINDOW
    # The +1d window closes before the untouched session and is unaffected.
    assert results["1d"].car == pytest.approx(-0.0005, abs=1e-12)


def test_enough_stale_prints_fail_the_traded_fraction_before_the_sum():
    """The aggregate gate fires first, and names the same reason -- so a
    mostly-untraded window and a single stale session are both refusals rather
    than one refusal and one silently shortened horizon."""
    from app.analysis.empirical.event_study import (
        ABSTAIN_THIN_EVENT_WINDOW, estimate_car,
    )

    results = estimate_car(
        hand_computed_history(stale_print_offsets=(1, 2, 3, 4)),
        company_id=FIXTURE_COMPANY_ID, event_day=FIXTURE_EVENT_DAY,
        policy=tiny_policy())
    assert results["5d"].car is None
    assert results["5d"].abstain_reason == ABSTAIN_THIN_EVENT_WINDOW


def test_the_estimation_window_ignores_stale_prints_too():
    """The same shape on the ESTIMATION side: 110 real sessions out of 220,
    which is below the 120 the policy requires. If `traded` were ignored the
    zeros would have flattened beta instead."""
    from app.analysis.empirical.event_study import ABSTAIN_ESTIMATION, fit_market_model

    assert fit_market_model(hand_computed_history(thin=True),
                            company_id=FIXTURE_COMPANY_ID,
                            event_day=FIXTURE_EVENT_DAY,
                            policy=tiny_policy()) is None
    results = estimate_car_of(hand_computed_history(thin=True))
    assert all(r.abstain_reason == ABSTAIN_ESTIMATION for r in results.values())


def estimate_car_of(history):
    from app.analysis.empirical.event_study import estimate_car

    return estimate_car(history, company_id=FIXTURE_COMPANY_ID,
                        event_day=FIXTURE_EVENT_DAY, policy=tiny_policy())


def test_a_circuit_day_is_kept_and_flagged_rather_than_dropped():
    """The move is real, it is merely truncated: the true reaction is AT
    LEAST this large. Dropping it understates; pretending it is complete
    misstates. Recording it lets a reviewer discount it."""
    from app.analysis.empirical.event_study import estimate_car

    results = estimate_car(hand_computed_history(circuit_offset=2),
                           company_id=FIXTURE_COMPANY_ID,
                           event_day=FIXTURE_EVENT_DAY, policy=tiny_policy())
    assert results["5d"].car == pytest.approx(0.0015, abs=1e-12)
    assert results["5d"].censored_days == 1
    assert results["1d"].censored_days == 0


# --- shock detection --------------------------------------------------------

def test_the_shock_threshold_is_one_and_a_half_sigma_of_the_daily_distribution():
    from app.analysis.empirical.event_study import daily_moves, sigma_of

    fixture = load_fixture("car_hand_computed.json")["shock_series"]
    moves = daily_moves(levels_from_moves(fixture["moves"]))
    sigma = sigma_of([m for _, m in moves])
    assert sigma == pytest.approx(fixture["expected_sigma"], rel=1e-9)
    assert 1.5 * sigma == pytest.approx(fixture["expected_threshold"], rel=1e-9)


def test_only_the_moves_above_the_threshold_become_shock_instances():
    from app.analysis.empirical.event_study import detect_shocks

    fixture = load_fixture("car_hand_computed.json")["shock_series"]
    shocks = detect_shocks(FIXTURE_VARIABLE, levels_from_moves(fixture["moves"]),
                           policy=tiny_policy(min_series_days=10))
    assert len(shocks) == 4
    assert {s.sign for s in shocks} == {"UP", "DOWN"}
    assert all(abs(s.move) > fixture["expected_threshold"] for s in shocks)


def test_two_shocks_inside_one_five_day_window_deduplicate_to_the_larger():
    from app.analysis.empirical.event_study import detect_shocks

    moves = [0.01, -0.01] * 10 + [0.03, 0.0, 0.05]
    series = levels_from_moves(moves)
    shocks = detect_shocks(FIXTURE_VARIABLE, series, policy=tiny_policy(min_series_days=10))
    assert len(shocks) == 1
    assert shocks[0].move == pytest.approx(0.05, rel=1e-9)


def test_a_series_shorter_than_the_deployed_minimum_is_refused_not_computed():
    from app.analysis.empirical.event_study import ShockSeriesTooShort, detect_shocks

    with pytest.raises(ShockSeriesTooShort):
        detect_shocks(FIXTURE_VARIABLE, levels_from_moves([0.01, -0.01]))


def test_the_deployed_policy_requires_at_least_eight_years_of_series():
    from app.analysis.empirical.config import load_empirical_config

    policy = load_empirical_config()
    assert policy.min_series_days >= 8 * 250, (
        "spec §10.1 asks for >= 8 years of history per variable")


# --- aggregation and persistence -------------------------------------------

def _flat_history(car_by_event: dict):
    """A `PriceHistory`-shaped stand-in that returns CARs directly, so the
    aggregation can be tested without re-deriving the estimator."""

    class Flat:
        def cumulative_abnormal_return(self, company_id, event_date, window_days):
            return car_by_event.get((company_id, event_date, window_days))
    return Flat()


def test_aggregation_reports_n_median_iqr_sign_consistency_and_p():
    from app.analysis.empirical.event_study import summarise_cars

    row = summarise_cars([-0.02] * 8 + [0.01, 0.03])
    assert row is not None
    median, lo, hi, consistency, p_value = row
    assert median < 0
    assert lo <= median <= hi
    assert consistency == pytest.approx(0.8, abs=1e-9)
    assert 0.0 <= p_value <= 1.0


def test_every_persisted_row_carries_the_estimator_version(phase5_session):
    from app.analysis.empirical.event_study import (
        CAR_ESTIMATOR_VERSION, persist_transmission_rows,
    )
    from tests.phase5.helpers import transmission_row

    persist_transmission_rows(phase5_session, [transmission_row()],
                              computed_at=FIXTURE_NOW)
    rows = phase5_session.execute(text(
        "SELECT estimator_version, n_events FROM transmission_empirical")).all()
    assert rows and all(r[0] == CAR_ESTIMATOR_VERSION for r in rows)


def test_persisting_the_same_study_twice_refreshes_rather_than_duplicates(phase5_session):
    from app.analysis.empirical.event_study import persist_transmission_rows
    from tests.phase5.helpers import transmission_row

    persist_transmission_rows(phase5_session, [transmission_row(n_events=12)],
                              computed_at=FIXTURE_NOW)
    persist_transmission_rows(phase5_session, [transmission_row(n_events=34)],
                              computed_at=FIXTURE_NOW)
    rows = phase5_session.execute(text(
        "SELECT n_events FROM transmission_empirical")).all()
    assert [r[0] for r in rows] == [34]


def test_the_builder_produces_nothing_when_no_event_yields_a_usable_car():
    """The deployed state: no price history, therefore no rows. The matrix is
    empty because the data is missing, not because the study is broken."""
    from app.analysis.empirical.event_study import build_transmission_rows

    rows = build_transmission_rows(
        _flat_history({}), company_ids=(FIXTURE_COMPANY_ID,),
        variable=FIXTURE_VARIABLE, shock_days=(date(2222, 1, 1),),
        shock_sign="UP", policy=tiny_policy())
    assert rows == ()


def test_the_builder_counts_only_events_that_produced_a_car():
    from app.analysis.empirical.event_study import build_transmission_rows

    days = tuple(date(2222, 1, 1) + timedelta(days=7 * i) for i in range(12))
    cars = {(FIXTURE_COMPANY_ID, day, 5): -0.02 for day in days[:10]}
    rows = build_transmission_rows(
        _flat_history(cars), company_ids=(FIXTURE_COMPANY_ID,),
        variable=FIXTURE_VARIABLE, shock_days=days, shock_sign="UP",
        policy=tiny_policy(), horizons=("5d",))
    assert len(rows) == 1
    assert rows[0].n_events == 10
    assert rows[0].median_car == pytest.approx(-0.02, abs=1e-12)
    assert rows[0].sign_consistency == pytest.approx(1.0, abs=1e-12)


def test_the_rebuild_script_exists_and_refuses_to_invent_a_price_feed():
    script = BACKEND / "scripts" / "rebuild_transmission_matrix.py"
    assert script.exists()
    for number, line in code_lines(script):
        for banned in BANNED_NETWORK_MODULES:
            assert f"import {banned}" not in line, f"{script.name}:{number}"
