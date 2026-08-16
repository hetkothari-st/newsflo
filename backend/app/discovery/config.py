"""The deliberately IMPURE sibling of `engine.py`: reads
`config/discovery.yaml` off disk and freezes it.

Same separation Phase 0 made between `gates.py` and `config_loader.py`, for
the same reason: the module that decides must not be the module that holds
the numbers, or the two drift.
"""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping

import yaml

# backend/config/discovery.yaml
DISCOVERY_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "discovery.yaml"


@dataclass(frozen=True)
class DiscoveryConfig:
    distance_thresholds: Mapping[int, float]
    max_candidates_per_event: int
    peer_closure_min_members: int
    peer_closure_threshold: float
    max_depth: int
    modelled_shock_variables: tuple[str, ...]

    def threshold_for(self, distance: int) -> float | None:
        """The minimum exposure share a candidate found at this distance must
        clear. `None` means the policy does not model this distance at all --
        which is a refusal, never a pass."""
        return self.distance_thresholds.get(int(distance))

    def models(self, variable: str) -> bool:
        return variable in self.modelled_shock_variables


@lru_cache(maxsize=4)
def load_discovery_config(path: Path | None = None) -> DiscoveryConfig:
    raw = yaml.safe_load((path or DISCOVERY_CONFIG_PATH).read_text(encoding="utf-8"))
    thresholds = {int(k): float(v) for k, v in raw["distance_thresholds"].items()}
    max_depth = int(raw["max_depth"])
    if max_depth > max(thresholds):
        raise ValueError(
            "discovery.yaml: max_depth is deeper than the deepest "
            "distance_threshold, so the deepest hop would have no bar to "
            "clear")
    return DiscoveryConfig(
        distance_thresholds=thresholds,
        max_candidates_per_event=int(raw["max_candidates_per_event"]),
        peer_closure_min_members=int(raw["peer_closure_min_members"]),
        peer_closure_threshold=float(raw["peer_closure_threshold"]),
        max_depth=max_depth,
        modelled_shock_variables=tuple(raw["modelled_shock_variables"]))
