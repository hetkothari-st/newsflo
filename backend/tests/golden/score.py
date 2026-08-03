"""Scores a pipeline run against the golden set.

precision here is deliberately NOT the textbook definition: it is measured
only over LABELLED tickers (must_include + must_exclude), because the label
sets are partial. An unlabelled ticker is ignored entirely.
"""
from dataclasses import dataclass

from tests.golden.cases import GOLDEN_CASES, GoldenCase


@dataclass(frozen=True)
class CaseScore:
    alert_id: int
    missing: set[str]
    forbidden: set[str]
    precision: float
    recall: float


@dataclass(frozen=True)
class RunScore:
    cases: list[CaseScore]
    mean_precision: float
    mean_recall: float
    total_forbidden: int


def score_case(case: GoldenCase, actual_tickers: set[str]) -> CaseScore:
    missing = case.must_include - actual_tickers
    forbidden = case.must_exclude & actual_tickers

    hits = len(case.must_include & actual_tickers)
    # Denominator is labelled tickers the run actually returned, so an
    # unlabelled extra never costs precision.
    labelled_returned = hits + len(forbidden)
    precision = 1.0 if labelled_returned == 0 else hits / labelled_returned
    recall = 1.0 if not case.must_include else hits / len(case.must_include)

    return CaseScore(
        alert_id=case.alert_id, missing=missing, forbidden=forbidden,
        precision=precision, recall=recall,
    )


def score_all(results: dict[int, set[str]], cases: list[GoldenCase] | None = None) -> RunScore:
    """results: {alert_id: set of tickers the pipeline produced}. An alert_id
    absent from `results` is scored as an empty result rather than skipped --
    a case the pipeline dropped entirely is a failure, not a non-event."""
    cases = GOLDEN_CASES if cases is None else cases
    scored = [score_case(c, results.get(c.alert_id, set())) for c in cases]
    n = len(scored) or 1
    return RunScore(
        cases=scored,
        mean_precision=sum(s.precision for s in scored) / n,
        mean_recall=sum(s.recall for s in scored) / n,
        total_forbidden=sum(len(s.forbidden) for s in scored),
    )
