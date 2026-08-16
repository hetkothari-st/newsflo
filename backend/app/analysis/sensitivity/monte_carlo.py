"""TASK 2.3 -- Monte Carlo over the parameter distributions (spec §5.2).

    seed = stable_hash(event_id, company_id, analysis_version)

so the same analysis of the same event for the same company always produces
THE SAME BAND. `stable_hash` is sha256-based, never Python's `hash()`, which
is salted per process and would change the published band on every restart --
a test runs this in a separate interpreter to prove it.

WHAT IS EMITTED (spec §5.2, phase file Task 2.3):
  * `delta_ebitda_pct`  p10 / p50 / p90 as a percentage of EBITDA_ttm
  * `sign_consistency`  the fraction of draws sharing p50's sign
  * `bucket`            from `config/materiality.yaml`, single source of truth
  * `driver_ranking`    variance attribution per parameter
  * `uncomputable_channels`  what could NOT be sized, carried rather than
                             quietly dropped

DRIVER ATTRIBUTION -- WHICH ESTIMATOR, AND WHY IT IS NAMED.
`ATTRIBUTION_METHOD = "correlation_ratio_binned_v1"`: a first-order
sensitivity index estimated as the correlation ratio (eta-squared) of the
output over equal-count bins of each parameter's draws --
Var_bins(E[Y | X in bin]) / Var(Y). It is the "simple correlation-ratio
approximation" the phase file allows, not a full Sobol decomposition: it
captures each parameter's own first-order contribution and attributes none of
the interaction terms, so the raw indices need not sum to 1 and are
NORMALISED to do so before they are reported. The name carries a version
because changing the estimator changes a number a user sees.

INDEPENDENCE. Distinct parameters are drawn independently; identical
parameters (same name, band, source and evidence) share a draw, so one
pass-through curve used by two channels moves both together. No correlation
structure between DIFFERENT parameters exists in the ledger, and inventing a
correlation matrix would be inventing data (DATA_GAPS.md §6).

PURE except for the seeded RNG. No DB, no clock, no network, no model.
"""
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import hashlib
import random

from app.analysis.sensitivity.channels import ChannelResult, UncomputableChannel
from app.analysis.sensitivity.config import (
    MaterialityConfig, load_materiality_config,
)
from app.analysis.sensitivity.params import InsufficientParameterData, ParamDist

ENGINE_VERSION = "sensitivity-v5.0.0"
ATTRIBUTION_METHOD = "correlation_ratio_binned_v1"

# Best grade first; the weakest cap across the channels wins.
_GRADE_ORDER = ("A", "B", "C", "D", "E")


@dataclass(frozen=True)
class Percentiles:
    p10: float
    p50: float
    p90: float


@dataclass(frozen=True)
class DriverContribution:
    param: str
    contribution: float
    source: str
    point: float
    evidence_id: str | None = None


@dataclass(frozen=True)
class MaterialityResult:
    delta_ebitda_pct: Percentiles
    sign_consistency: float
    bucket: str
    driver_ranking: tuple[DriverContribution, ...]
    uncomputable_channels: tuple[UncomputableChannel, ...]
    materiality_bases: tuple[str, ...]
    n: int
    seed: int
    attribution_method: str
    engine_version: str
    channel_ids: tuple[str, ...]
    evidence_grade_cap: str | None
    config_version: str


def stable_hash(event_id: str, company_id: int | None, analysis_version: str) -> int:
    """sha256 of the identity triple, folded to a 63-bit integer. Stable
    across processes, machines and Python versions."""
    digest = hashlib.sha256(
        "\x1f".join((str(event_id), str(company_id), str(analysis_version))
                    ).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") >> 1


def _percentile(ordered: Sequence[float], q: float) -> float:
    """Linear interpolation between order statistics."""
    if not ordered:                                   # pragma: no cover
        raise InsufficientParameterData("no draws")
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (q / 100.0)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return ordered[low] + weight * (ordered[high] - ordered[low])


def _draw(rng: random.Random, dist: ParamDist, config: MaterialityConfig) -> float:
    if dist.hi <= dist.lo:
        return dist.point
    if dist.dist == "uniform":
        return rng.uniform(dist.lo, dist.hi)
    if dist.dist == "normal":
        # lo/hi are the 10th/90th percentiles, so sigma follows from z.
        sigma = (dist.hi - dist.lo) / (2.0 * config.normal_band_z)
        return rng.normalvariate(dist.point, sigma)
    mode = min(max(dist.point, dist.lo), dist.hi)
    return rng.triangular(dist.lo, dist.hi, mode)


def _correlation_ratio(parameter_draws: Sequence[float], outputs: Sequence[float],
                       bins: int) -> float:
    """eta-squared of `outputs` over equal-count bins of `parameter_draws`."""
    n = len(outputs)
    mean = sum(outputs) / n
    total = sum((y - mean) ** 2 for y in outputs)
    if total <= 0.0:
        return 0.0
    order = sorted(range(n), key=lambda i: parameter_draws[i])
    size = max(1, n // max(1, bins))
    between = 0.0
    for start in range(0, n, size):
        chunk = order[start:start + size]
        if not chunk:                                  # pragma: no cover
            continue
        chunk_mean = sum(outputs[i] for i in chunk) / len(chunk)
        between += len(chunk) * (chunk_mean - mean) ** 2
    return max(0.0, between / total)


def _weakest_cap(caps) -> str | None:
    present = [c for c in caps if c]
    if not present:
        return None
    return max(present, key=lambda grade: _GRADE_ORDER.index(grade)
               if grade in _GRADE_ORDER else len(_GRADE_ORDER))


def simulate(channels: Sequence[ChannelResult], *, ebitda_ttm_inr: float | None,
             event_id: str, company_id: int | None, analysis_version: str,
             n: int | None = None, seed: int | None = None,
             uncomputable_channels: Sequence[UncomputableChannel] = (),
             config: MaterialityConfig | None = None) -> MaterialityResult:
    """Spec §5.2. Deterministic per (event, company, analysis_version)."""
    config = config or load_materiality_config()
    if not channels:
        raise InsufficientParameterData(
            "no computable channel: there is nothing to size, and 'no impact' "
            "is a different statement from 'we could not compute one'")
    if not ebitda_ttm_inr:
        raise InsufficientParameterData(
            "no EBITDA_ttm for this company: a delta with no base is not a "
            "percentage, and a base invented here would be fabricated data")

    draws = int(n if n is not None else config.monte_carlo_n)
    resolved_seed = int(seed if seed is not None
                        else stable_hash(event_id, company_id, analysis_version))
    rng = random.Random(resolved_seed)

    # One draw series per DISTINCT parameter, in a deterministic order.
    distinct: dict[tuple, ParamDist] = {}
    for channel in sorted(channels, key=lambda c: c.channel_id):
        for _, dist in sorted(channel.params.items()):
            distinct.setdefault(dist.key(), dist)
    series: dict[tuple, list[float]] = {
        key: [_draw(rng, dist, config) for _ in range(draws)]
        for key, dist in sorted(distinct.items(), key=lambda kv: str(kv[0]))}

    base = float(ebitda_ttm_inr)
    # Floating-point addition is not associative, so the channels are summed
    # in a fixed order (fix round 1, M4). Without this the published band
    # depended on the order the caller happened to pass them in.
    ordered_channels = sorted(channels, key=lambda c: c.channel_id)
    outputs: list[float] = []
    for index in range(draws):
        total = 0.0
        for channel in ordered_channels:
            total += channel.evaluate({
                name: series[dist.key()][index]
                for name, dist in channel.params.items()})
        outputs.append(total / base * 100.0)

    ordered = sorted(outputs)
    band = Percentiles(p10=_percentile(ordered, 10.0),
                       p50=_percentile(ordered, 50.0),
                       p90=_percentile(ordered, 90.0))

    if band.p50 > 0:
        consistency = sum(1 for y in outputs if y > 0) / draws
    elif band.p50 < 0:
        consistency = sum(1 for y in outputs if y < 0) / draws
    else:
        # A median of exactly zero is not a direction, and calling it one
        # consistent would be the opposite of what this number means.
        consistency = 0.0

    return MaterialityResult(
        delta_ebitda_pct=band,
        sign_consistency=round(consistency, 6),
        bucket=config.bucket_for(band.p50),
        driver_ranking=_rank_drivers(distinct, series, outputs, config),
        uncomputable_channels=tuple(uncomputable_channels),
        materiality_bases=tuple(sorted({c.materiality_base for c in channels})),
        n=draws, seed=resolved_seed, attribution_method=ATTRIBUTION_METHOD,
        engine_version=ENGINE_VERSION,
        channel_ids=tuple(sorted(c.channel_id for c in channels)),
        evidence_grade_cap=_weakest_cap(c.grade_cap for c in channels),
        config_version=config.version)


def _rank_drivers(distinct: Mapping[tuple, ParamDist],
                  series: Mapping[tuple, Sequence[float]],
                  outputs: Sequence[float],
                  config: MaterialityConfig) -> tuple[DriverContribution, ...]:
    raw: list[tuple[tuple, ParamDist, float]] = []
    for key, dist in distinct.items():
        values = series[key]
        if max(values) == min(values):
            continue                    # a parameter that did not move
        raw.append((key, dist, _correlation_ratio(
            values, outputs, config.attribution_bins)))

    total = sum(index for _, _, index in raw)
    if total <= 0.0:
        return ()

    # A name that appears twice (the same parameter resolved from two
    # different sources) is disambiguated rather than silently merged.
    name_counts: dict[str, int] = {}
    for _, dist, _ in raw:
        name_counts[dist.name] = name_counts.get(dist.name, 0) + 1

    contributions = [
        DriverContribution(
            param=dist.name if name_counts[dist.name] == 1
            else f"{dist.name}({dist.source})",
            contribution=round(index / total, 6), source=dist.source,
            point=dist.point, evidence_id=dist.evidence_id)
        for _, dist, index in raw]
    contributions.sort(key=lambda d: (-d.contribution, d.param))
    return tuple(contributions)


def serialize_materiality(result: MaterialityResult,
                          config: MaterialityConfig | None = None) -> dict:
    """The JSON block that travels on the CHANNEL signal and reaches the API.

    The band is ALWAYS emitted whole: p50 never appears without p10 and p90
    (phase file DO NOT). `driver_ranking` is truncated to the configured top
    N -- the full ranking stays recoverable from the signal's own record.
    """
    config = config or load_materiality_config()
    return {
        "delta_ebitda_pct": {
            "p10": round(result.delta_ebitda_pct.p10, 6),
            "p50": round(result.delta_ebitda_pct.p50, 6),
            "p90": round(result.delta_ebitda_pct.p90, 6),
        },
        "sign_consistency": result.sign_consistency,
        "bucket": result.bucket,
        "driver_ranking": [
            {"param": d.param, "contribution": d.contribution,
             "source": d.source, "point": d.point, "evidence_id": d.evidence_id}
            for d in result.driver_ranking[:config.top_drivers]],
        "uncomputable_channels": [u.as_dict() for u in result.uncomputable_channels],
        # Which P&L line(s) the number describes. An interest-line effect is
        # not an EBITDA effect, and the renderer must not print it as one.
        "materiality_bases": list(result.materiality_bases),
        "channel_ids": list(result.channel_ids),
        "evidence_grade_cap": result.evidence_grade_cap,
        "n": result.n,
        "seed": result.seed,
        "attribution_method": result.attribution_method,
        "engine_version": result.engine_version,
        "config_version": result.config_version,
    }
