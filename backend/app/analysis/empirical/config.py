"""Deliberately IMPURE sibling of the study modules: reads
`config/empirical.yaml` off disk and freezes it into the policy the event
study and the cross-check evaluate.

Kept out of `event_study.py` and `check.py` on purpose -- those two hold NO
threshold of their own, so policy cannot drift between the file and the code,
and `tests/phase5/test_no_fixture_data_reaches_production.py` ast-scans them
for hardcoded numbers.
"""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import yaml

EMPIRICAL_CONFIG_PATH = (Path(__file__).resolve().parents[3] / "config"
                         / "empirical.yaml")


@dataclass(frozen=True)
class EmpiricalPolicy:
    """Every threshold the event study and the cross-check need.

    Frozen and passed in, so a test can shorten one window by name
    (`dataclasses.replace`) and say so out loud, rather than carrying its own
    copy of every number the product ships.
    """
    version: str
    shock_sigma_multiple: float
    shock_dedupe_days: int
    min_series_days: int
    estimation_start_offset: int
    estimation_end_offset: int
    min_estimation_days: int
    min_event_window_traded_fraction: float
    car_horizons: Mapping[str, int]
    min_events: int
    max_p_value: float
    divergence_threshold_pct: float

    def window_days(self, horizon: str) -> int:
        try:
            return int(self.car_horizons[str(horizon)])
        except KeyError as exc:                        # pragma: no cover
            raise ValueError(
                f"no CAR window is configured for horizon {horizon!r}") from exc


@lru_cache(maxsize=4)
def load_empirical_config(path: Path | None = None) -> EmpiricalPolicy:
    raw = yaml.safe_load((path or EMPIRICAL_CONFIG_PATH).read_text(encoding="utf-8"))
    shock = raw["shock_detection"]
    estimator = raw["estimator"]
    check = raw["check"]
    return EmpiricalPolicy(
        version=str(raw["version"]),
        shock_sigma_multiple=float(shock["sigma_multiple"]),
        shock_dedupe_days=int(shock["dedupe_days"]),
        min_series_days=int(shock["min_series_days"]),
        estimation_start_offset=int(estimator["estimation_start_offset"]),
        estimation_end_offset=int(estimator["estimation_end_offset"]),
        min_estimation_days=int(estimator["min_estimation_days"]),
        min_event_window_traded_fraction=float(
            estimator["min_event_window_traded_fraction"]),
        car_horizons=MappingProxyType({
            str(key): int(value)
            for key, value in estimator["car_horizons"].items()}),
        min_events=int(check["min_events"]),
        max_p_value=float(check["max_p_value"]),
        divergence_threshold_pct=float(raw["divergence"]["threshold_pct"]))
