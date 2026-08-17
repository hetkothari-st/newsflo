"""`config/materiality.yaml`, frozen into dataclasses.

Deliberately IMPURE (it reads a file) and deliberately tiny, exactly like
`app/ledger/freshness.py` and `app/core/config_loader.py`. The numbers live
in the YAML so that "how big is material" and "how wide is a sector proxy"
are policy decisions in the open, not constants buried in a module -- and so
that the reducer's sign-consistency rule and this engine's bucketing cannot
drift apart.

There is no fallback anywhere in this file. A missing section raises.
"""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping

import yaml

# backend/config/materiality.yaml
MATERIALITY_CONFIG_PATH = (
    Path(__file__).resolve().parents[3] / "config" / "materiality.yaml")

NO_MATERIAL_IMPACT = "NO_MATERIAL_IMPACT"


class MaterialityConfigError(KeyError):
    """The policy file does not say something the engine needs it to say."""


@dataclass(frozen=True)
class MaterialityConfig:
    version: str
    buckets: Mapping[str, float]              # name -> min |p50| in %
    directional_claim_min: float
    secondary_min: float
    mixed_requires_material_tail_pct: float
    monte_carlo_n: int
    attribution_bins: int
    normal_band_z: float
    top_drivers: int
    band_width: Mapping[str, float]           # source -> relative half width
    distribution: Mapping[str, str]           # source -> distribution name
    evidence_grade_cap: Mapping[str, str]     # param source -> best allowed grade
    # exposure_row measurement -> best allowed grade. A separate axis from
    # the parameter caps: FILED/DISCLOSED_CALL are absent, meaning uncapped.
    exposure_measurement_grade_cap: Mapping[str, str]
    unknown_modifier_band_multiplier: float
    param_bounds: Mapping[str, tuple[float, float]]

    def band_width_for(self, source: str) -> float:
        try:
            return float(self.band_width[str(source)])
        except KeyError as exc:                      # pragma: no cover
            raise MaterialityConfigError(
                f"config/materiality.yaml has no band_width for source "
                f"{source!r}. A band width invented here would be an "
                f"uncertainty nobody chose.") from exc

    def distribution_for(self, source: str) -> str:
        try:
            return str(self.distribution[str(source)])
        except KeyError as exc:                      # pragma: no cover
            raise MaterialityConfigError(
                f"config/materiality.yaml has no distribution for source "
                f"{source!r}") from exc

    def bucket_for(self, abs_pct: float) -> str:
        """|p50| of delta EBITDA % -> bucket. Evaluated from the largest
        threshold down, so the table order in the YAML cannot change the
        answer."""
        for name, floor in sorted(self.buckets.items(), key=lambda kv: -kv[1]):
            if abs(abs_pct) >= floor:
                return name
        return NO_MATERIAL_IMPACT


@lru_cache(maxsize=4)
def load_materiality_config(path: Path | None = None) -> MaterialityConfig:
    raw = yaml.safe_load((path or MATERIALITY_CONFIG_PATH).read_text(encoding="utf-8"))
    try:
        buckets = {str(name): float(spec["min_abs_pct"])
                   for name, spec in raw["buckets"].items()}
        consistency = raw["sign_consistency"]
        monte_carlo = raw["monte_carlo"]
        return MaterialityConfig(
            version=str(raw["version"]),
            buckets=buckets,
            directional_claim_min=float(consistency["directional_claim_min"]),
            secondary_min=float(consistency["secondary_min"]),
            mixed_requires_material_tail_pct=float(
                consistency["mixed_requires_material_tail_pct"]),
            monte_carlo_n=int(monte_carlo["n"]),
            attribution_bins=int(monte_carlo["attribution_bins"]),
            normal_band_z=float(monte_carlo["normal_band_z"]),
            top_drivers=int(monte_carlo["top_drivers"]),
            band_width={str(k): float(v) for k, v in raw["band_width"].items()},
            distribution={str(k): str(v) for k, v in raw["distribution"].items()},
            evidence_grade_cap={str(k): str(v)
                                for k, v in raw["evidence_grade_cap"].items()},
            exposure_measurement_grade_cap={
                str(k): str(v) for k, v in
                (raw.get("exposure_measurement_grade_cap") or {}).items()},
            unknown_modifier_band_multiplier=float(
                raw["unknown_modifier_state"]["band_width_multiplier"]),
            param_bounds={str(k): (float(v[0]), float(v[1]))
                          for k, v in (raw.get("param_bounds") or {}).items()})
    except (KeyError, TypeError) as exc:             # pragma: no cover
        raise MaterialityConfigError(
            f"config/materiality.yaml is missing {exc}") from exc
