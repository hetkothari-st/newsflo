from tests.golden.cases import GoldenCase
from tests.golden.score import score_all, score_case


def _case(**overrides):
    defaults = {
        "alert_id": 1,
        "title": "test",
        "must_include": {"A.NS"},
        "must_exclude": {"BAD.NS"},
    }
    defaults.update(overrides)
    return GoldenCase(**defaults)


def test_perfect_result_scores_1_0():
    result = score_case(_case(), {"A.NS"})
    assert result.missing == set()
    assert result.forbidden == set()
    assert result.precision == 1.0
    assert result.recall == 1.0


def test_forbidden_ticker_is_reported():
    result = score_case(_case(), {"A.NS", "BAD.NS"})
    assert result.forbidden == {"BAD.NS"}
    assert result.recall == 1.0
    assert result.precision == 0.5


def test_missing_ticker_lowers_recall():
    result = score_case(_case(must_include={"A.NS", "B.NS"}), {"A.NS"})
    assert result.missing == {"B.NS"}
    assert result.recall == 0.5


def test_unlabelled_extra_ticker_is_not_forbidden():
    # A company that is neither required nor banned is not scored against --
    # the label set is deliberately partial, so an unlabelled name is
    # "unknown", not "wrong".
    result = score_case(_case(), {"A.NS", "UNLABELLED.NS"})
    assert result.forbidden == set()
    assert result.precision == 1.0


def test_empty_result_scores_zero_recall_not_a_crash():
    result = score_case(_case(), set())
    assert result.missing == {"A.NS"}
    assert result.recall == 0.0
    assert result.precision == 1.0


def test_score_all_aggregates_and_counts_forbidden():
    cases = [_case(alert_id=1), _case(alert_id=2)]
    run = score_all({1: {"A.NS"}, 2: {"A.NS", "BAD.NS"}}, cases=cases)
    assert run.total_forbidden == 1
    assert run.mean_recall == 1.0
    assert run.mean_precision == 0.75


def test_score_all_treats_a_missing_alert_as_empty():
    cases = [_case(alert_id=1), _case(alert_id=2)]
    run = score_all({1: {"A.NS"}}, cases=cases)
    assert run.mean_recall == 0.5
