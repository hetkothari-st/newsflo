"""TASK 5.3 -- isotonic regression by pool-adjacent-violators.

§13.2 says "fit isotonic regression (or logistic + Platt scaling -- pick one,
version it)". Isotonic is picked: it assumes only that a higher score should
not mean a lower hit rate, which is the one thing we actually believe, and it
cannot invent a sigmoid's confident tails out of a handful of labels.

Pure python, stdlib only, ~40 lines. A dependency would be a heavier promise
than the algorithm.

THIS IS THE MATH, NOT A DEPLOYMENT. Nothing in the repo calls `fit_isotonic`
on real labels, because there are no real labels (DATA_GAPS §1). The function
exists so that the day a corpus lands, the fitting is a reviewed thing that
already works rather than a rush job -- and so this phase's tests can prove
the arithmetic on obviously fake data.
"""
from dataclasses import dataclass
from typing import Sequence

METHOD = "isotonic_pav_v1"


@dataclass(frozen=True)
class IsotonicModel:
    """Fitted breakpoints: `x[i]` -> `y[i]`, non-decreasing in y."""
    xs: tuple[float, ...]
    ys: tuple[float, ...]
    method: str = METHOD

    def predict(self, x: float) -> float:
        """Piecewise-constant, held flat outside the fitted range.

        Deliberately NOT extrapolated: a candidate beyond every score the
        corpus contained is exactly the case §13.2's out-of-distribution gate
        exists for, and inventing a trend past the data would hide it.
        """
        if not self.xs:                                # pragma: no cover
            raise ValueError("empty model")
        if x <= self.xs[0]:
            return self.ys[0]
        if x >= self.xs[-1]:
            return self.ys[-1]
        best = self.ys[0]
        for xi, yi in zip(self.xs, self.ys):
            if xi <= x:
                best = yi
            else:
                break
        return best


def fit_isotonic(x: Sequence[float], y: Sequence[float],
                 weights: Sequence[float] | None = None) -> IsotonicModel:
    """Pool-adjacent-violators. Ties in x are pooled before the walk, so the
    fit does not depend on the order two identical scores arrived in."""
    if len(x) != len(y):
        raise ValueError("x and y must be the same length")
    if not x:
        raise ValueError("nothing to fit")
    w = list(weights) if weights is not None else [1.0] * len(x)

    ordered = sorted(zip(x, y, w), key=lambda t: t[0])
    blocks: list[list[float]] = []                     # [x, sum_wy, sum_w]
    for xi, yi, wi in ordered:
        if blocks and blocks[-1][0] == xi:
            blocks[-1][1] += wi * yi
            blocks[-1][2] += wi
            continue
        blocks.append([xi, wi * yi, wi])
        # Pool while the running means violate monotonicity.
        while len(blocks) > 1 and (blocks[-2][1] / blocks[-2][2]
                                   > blocks[-1][1] / blocks[-1][2]):
            merged = blocks.pop()
            blocks[-1][0] = merged[0]
            blocks[-1][1] += merged[1]
            blocks[-1][2] += merged[2]

    xs: list[float] = []
    ys: list[float] = []
    cursor = 0
    for block_x, sum_wy, sum_w in blocks:
        value = sum_wy / sum_w
        while cursor < len(ordered) and ordered[cursor][0] <= block_x:
            xs.append(ordered[cursor][0])
            ys.append(value)
            cursor += 1
    return IsotonicModel(xs=tuple(xs), ys=tuple(ys))
