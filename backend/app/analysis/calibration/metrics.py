"""TASK 5.3 -- the reporting §13.2 requires: reliability diagram, Expected
Calibration Error and Brier score.

Reported OVERALL, PER TIER and PER SECTOR -- `by_group` does the split, so the
question "is it calibrated for ripple candidates in cement?" is answerable
rather than averaged away. An overall ECE of 0.03 that hides 0.20 on one tier
is exactly the number that gets a product trusted wrongly.

Nothing here is deployed: with no labeled corpus there is nothing to score.
`tests/phase5/test_calibration.py` proves the arithmetic by hand and SKIPS the
ECE ship-gate with its reason recorded.
"""
from typing import Any, Mapping, Sequence


def _check(probs: Sequence[float], labels: Sequence[int]) -> None:
    if len(probs) != len(labels):
        raise ValueError("probs and labels must be the same length")
    if not probs:
        raise ValueError("nothing to score")


def brier_score(probs: Sequence[float], labels: Sequence[int]) -> float:
    """Mean squared error of the probability against the outcome."""
    _check(probs, labels)
    return sum((float(p) - float(y)) ** 2
               for p, y in zip(probs, labels)) / len(probs)


def _bin_index(p: float, bins: int) -> int:
    return min(int(float(p) * bins), bins - 1)


def reliability_diagram(probs: Sequence[float], labels: Sequence[int], *,
                        bins: int = 10) -> tuple[Mapping[str, Any], ...]:
    """Equal-width bins over [0, 1]. Empty bins are omitted: a bin with no
    observations has no observed frequency, and drawing one at zero would put
    a point on the chart that no data supports."""
    _check(probs, labels)
    buckets: dict[int, list[tuple[float, float]]] = {}
    for p, y in zip(probs, labels):
        buckets.setdefault(_bin_index(p, bins), []).append((float(p), float(y)))
    out = []
    for index in sorted(buckets):
        entries = buckets[index]
        out.append({
            "bin_lo": index / bins,
            "bin_hi": (index + 1) / bins,
            "count": len(entries),
            "mean_predicted": sum(p for p, _ in entries) / len(entries),
            "observed": sum(y for _, y in entries) / len(entries),
        })
    return tuple(out)


def expected_calibration_error(probs: Sequence[float], labels: Sequence[int], *,
                               bins: int = 10) -> float:
    """Sum over bins of (bin share) x |mean predicted - observed|."""
    diagram = reliability_diagram(probs, labels, bins=bins)
    total = len(probs)
    return sum(entry["count"] / total
               * abs(entry["mean_predicted"] - entry["observed"])
               for entry in diagram)


def by_group(probs: Sequence[float], labels: Sequence[int],
             groups: Sequence[Any], *, bins: int = 10
             ) -> Mapping[Any, Mapping[str, Any]]:
    """`{group: {n, ece, brier}}` -- the per-tier and per-sector split §13.2
    asks for. A group of one is reported with its n so nobody reads its ECE as
    a measurement."""
    _check(probs, labels)
    if len(groups) != len(probs):
        raise ValueError("groups must be the same length as probs")
    split: dict[Any, tuple[list[float], list[int]]] = {}
    for p, y, g in zip(probs, labels, groups):
        entry = split.setdefault(g, ([], []))
        entry[0].append(float(p))
        entry[1].append(int(y))
    return {
        group: {
            "n": len(ps),
            "ece": expected_calibration_error(ps, ys, bins=bins),
            "brier": brier_score(ps, ys),
        }
        for group, (ps, ys) in sorted(split.items(), key=lambda kv: str(kv[0]))
    }
