"""Reads `config/calibration.yaml` and freezes it. The calibration modules
hold no threshold of their own."""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

CALIBRATION_CONFIG_PATH = (Path(__file__).resolve().parents[3] / "config"
                           / "calibration.yaml")


@dataclass(frozen=True)
class CalibrationConfig:
    version: str
    enabled: bool
    min_corpus_size: int
    ood_method: str
    ood_threshold_quantile: float
    ood_ridge_fraction: float
    ece_bins: int


@lru_cache(maxsize=4)
def load_calibration_config(path: Path | None = None) -> CalibrationConfig:
    raw = yaml.safe_load(
        (path or CALIBRATION_CONFIG_PATH).read_text(encoding="utf-8"))
    ood = raw["ood"]
    return CalibrationConfig(
        version=str(raw["version"]),
        enabled=bool(raw["enabled"]),
        min_corpus_size=int(raw["activation"]["min_corpus_size"]),
        ood_method=str(ood["method"]),
        ood_threshold_quantile=float(ood["threshold_quantile"]),
        ood_ridge_fraction=float(ood["ridge_fraction"]),
        ece_bins=int(raw["reporting"]["ece_bins"]))
