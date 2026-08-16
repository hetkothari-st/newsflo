"""The linear algebra: (I - A)^-1, and the pruning rule.

CONVENTION, stated once so no caller has to guess. `A[i][j]` is
`a(industry_i -> industry_j)`: the share of industry j's TOTAL INPUT that it
buys from industry i. Columns are therefore cost structures and each column
sums to at most 1. The Leontief inverse `L = (I - A)^-1` has `L[i][j]` = the
total output of i required, directly and indirectly, per unit of final
demand for j. `L - I` is the INDIRECT-INCLUSIVE requirement, which is what a
mechanism edge should carry.

The toy 3x3 matrix this is verified against is deliberately ASYMMETRIC and
CYCLIC, so a transposed orientation -- the classic input-output bug -- fails
a test instead of passing every test.
"""
from typing import Iterable, Sequence

import numpy as np

# Addendum A2.4: "Prune aggressively: total_coeff < 0.02 is noise at industry
# level." This is the one number in this package, and it is the phase file's.
PRUNE_THRESHOLD = 0.02


class LeontiefError(ValueError):
    """The matrix cannot be inverted, or is not an input matrix at all."""


def leontief_inverse(a: np.ndarray) -> np.ndarray:
    """`(I - A)^-1`, the total requirement matrix.

    Raises rather than approximating. An economy whose input matrix does not
    converge is a data error -- typically a column that was normalised
    against the wrong total -- and quietly returning a pseudo-inverse would
    hide it behind plausible numbers.
    """
    a = np.asarray(a, dtype=float)
    if a.ndim != 2 or a.shape[0] != a.shape[1]:
        raise LeontiefError(
            f"the input matrix must be square; got shape {a.shape}")
    if not np.isfinite(a).all():
        raise LeontiefError("the input matrix carries a non-finite entry")
    if (a < 0).any():
        raise LeontiefError(
            "a negative input coefficient is not an input coefficient")

    # Convergence: the Leontief series I + A + A^2 + ... converges iff the
    # spectral radius of A is below 1. Checking it here turns an unusable
    # matrix into a loud failure rather than a silent one.
    radius = float(max(abs(np.linalg.eigvals(a))))
    if radius >= 1.0:
        raise LeontiefError(
            f"the input matrix does not converge (spectral radius {radius:.4f} "
            ">= 1); an economy cannot require more than its own output")

    try:
        return np.linalg.inv(np.eye(a.shape[0]) - a)
    except np.linalg.LinAlgError as error:      # pragma: no cover - guarded above
        raise LeontiefError(f"(I - A) is singular: {error}") from error


def total_requirements(a: np.ndarray) -> np.ndarray:
    """`(I - A)^-1 - I`: total requirement EXCLUDING the unit of the industry
    itself, which is what an edge coefficient means."""
    a = np.asarray(a, dtype=float)
    return leontief_inverse(a) - np.eye(a.shape[0])


def coefficient_rows(industries: Sequence[str], direct: np.ndarray,
                     total: np.ndarray) -> tuple[dict, ...]:
    """The matrices as rows, self-pairs dropped (an industry's requirement of
    itself is not a mechanism edge)."""
    out = []
    for i, source in enumerate(industries):
        for j, target in enumerate(industries):
            if i == j:
                continue
            out.append({"source_industry": source, "target_industry": target,
                        "direct_coeff": float(direct[i][j]),
                        "total_coeff": float(total[i][j])})
    return tuple(out)


def prune(rows: Iterable[dict],
          threshold: float = PRUNE_THRESHOLD) -> tuple[dict, ...]:
    """Drop rows whose total coefficient is below the noise floor."""
    return tuple(row for row in rows
                 if float(row["total_coeff"]) >= float(threshold))
