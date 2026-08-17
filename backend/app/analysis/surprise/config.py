"""Reads `config/surprise.yaml` and freezes it. The engine holds no threshold
and no weight of its own."""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import yaml

SURPRISE_CONFIG_PATH = (Path(__file__).resolve().parents[3] / "config"
                        / "surprise.yaml")


@dataclass(frozen=True)
class SurpriseConfig:
    version: str
    min_token_length: int
    novelty_window_days: int
    spreading_min_sources: int
    spreading_min_minutes: float
    saturated_min_sources: int
    saturated_min_minutes: float
    weights: Mapping[str, float]
    consensus_sigma_cap: float
    already_priced_forward_curve_min: float
    latency_p95_target_ms: int


@lru_cache(maxsize=4)
def load_surprise_config(path: Path | None = None) -> SurpriseConfig:
    raw = yaml.safe_load((path or SURPRISE_CONFIG_PATH).read_text(encoding="utf-8"))
    novelty = raw["novelty"]
    dissemination = raw["dissemination"]
    information = raw["information_value"]
    return SurpriseConfig(
        version=str(raw["version"]),
        min_token_length=int(novelty["min_token_length"]),
        novelty_window_days=int(novelty["window_days"]),
        spreading_min_sources=int(dissemination["spreading_min_sources"]),
        spreading_min_minutes=float(dissemination["spreading_min_minutes"]),
        saturated_min_sources=int(dissemination["saturated_min_sources"]),
        saturated_min_minutes=float(dissemination["saturated_min_minutes"]),
        weights=MappingProxyType({
            str(key): float(value)
            for key, value in information["weights"].items()}),
        consensus_sigma_cap=float(information["consensus_sigma_cap"]),
        already_priced_forward_curve_min=float(
            raw["already_priced"]["forward_curve_min"]),
        latency_p95_target_ms=int(raw["slo"]["latency_p95_target_ms"]))
