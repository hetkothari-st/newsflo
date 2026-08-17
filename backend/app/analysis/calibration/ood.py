"""TASK 5.3 -- the out-of-distribution gate (spec §13.2).

    "If the feature vector lies outside the training manifold (simple
     Mahalanobis or isolation-forest gate), set in_distribution=false, and the
     gate caps the tier at SECONDARY_RIPPLE. Novel event types must not inherit
     confidence from unrelated history."

Mahalanobis is picked -- it is the simple one, it needs no trees and no
randomness, and its threshold is a quantile of the TRAINING distances rather
than a number somebody chose.

THE SEMANTICS OF "NO MANIFOLD" ARE THE IMPORTANT PART. With no fitted model,
`in_distribution` is **None** -- unknown -- and the gate does NOT cap. Absence
of a model is not evidence of novelty, and capping every company at ripple
because calibration is off would be a silent tightening nobody chose. That is
the deployed state today, and it is stated out loud in `config/gates.yaml`.

Pure python: a Gauss-Jordan inverse of a ridge-regularised covariance. The
ridge matters -- real feature sets contain exactly-collinear columns (a bucket
and its own floor), which make the raw covariance singular.
"""
from dataclasses import dataclass
from typing import Sequence

from app.analysis.calibration.config import CalibrationConfig, load_calibration_config

METHOD = "mahalanobis_v1"


@dataclass(frozen=True)
class Manifold:
    mean: tuple[float, ...]
    inverse_covariance: tuple[tuple[float, ...], ...]
    threshold: float
    n_rows: int
    method: str = METHOD


def _invert(matrix: list[list[float]]) -> tuple[tuple[float, ...], ...]:
    """Gauss-Jordan with partial pivoting. Small matrices only -- the feature
    vector is twenty wide."""
    size = len(matrix)
    work = [list(row) + [1.0 if i == j else 0.0 for j in range(size)]
            for i, row in enumerate(matrix)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda r: abs(work[r][column]))
        if abs(work[pivot][column]) == 0.0:
            raise ValueError(
                "the covariance is singular even after regularisation; the "
                "manifold cannot be fitted on this feature set")
        work[column], work[pivot] = work[pivot], work[column]
        divisor = work[column][column]
        work[column] = [value / divisor for value in work[column]]
        for row in range(size):
            if row == column:
                continue
            factor = work[row][column]
            if factor == 0.0:
                continue
            work[row] = [value - factor * other
                         for value, other in zip(work[row], work[column])]
    return tuple(tuple(row[size:]) for row in work)


def _distance(row: Sequence[float], mean: Sequence[float],
              inverse: Sequence[Sequence[float]]) -> float:
    delta = [float(value) - float(centre) for value, centre in zip(row, mean)]
    total = 0.0
    for i, di in enumerate(delta):
        for j, dj in enumerate(delta):
            total += di * inverse[i][j] * dj
    return max(total, 0.0) ** 0.5


def fit_manifold(rows: Sequence[Sequence[float]], *,
                 config: CalibrationConfig | None = None) -> Manifold:
    """Mean, regularised inverse covariance, and the distance threshold."""
    config = config or load_calibration_config()
    if not rows:
        raise ValueError("nothing to fit")
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        raise ValueError("every row must have the same width")

    mean = [sum(float(row[i]) for row in rows) / len(rows) for i in range(width)]
    covariance = [[0.0] * width for _ in range(width)]
    for row in rows:
        delta = [float(row[i]) - mean[i] for i in range(width)]
        for i in range(width):
            for j in range(width):
                covariance[i][j] += delta[i] * delta[j]
    denominator = max(len(rows) - 1, 1)
    for i in range(width):
        for j in range(width):
            covariance[i][j] /= denominator

    scale = sum(covariance[i][i] for i in range(width)) / width
    ridge = config.ood_ridge_fraction * (scale if scale > 0 else 1.0)
    for i in range(width):
        covariance[i][i] += ridge

    inverse = _invert(covariance)
    distances = sorted(_distance(row, mean, inverse) for row in rows)
    index = min(int(config.ood_threshold_quantile * (len(distances) - 1)),
                len(distances) - 1)
    return Manifold(mean=tuple(mean), inverse_covariance=inverse,
                    threshold=distances[index], n_rows=len(rows))


def mahalanobis(row: Sequence[float], manifold: Manifold) -> float:
    return _distance(row, manifold.mean, manifold.inverse_covariance)


def in_distribution(row: Sequence[float], manifold: Manifold | None
                    ) -> bool | None:
    """True / False / **None**.

    None means NO FITTED MANIFOLD, which is the deployed state. It is not
    False: the gate treats an unknown as "not evaluated" and does not cap,
    because the absence of a model says nothing about this candidate.
    """
    if manifold is None:
        return None
    return mahalanobis(row, manifold) <= manifold.threshold
