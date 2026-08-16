"""Deliberately IMPURE sibling of the pure core: reads `config/gates.yaml`
off disk and freezes it into the dataclasses `app.core.gates` evaluates.

Kept out of `gates.py` and `reducer.py` on purpose -- those two must import
nothing that touches a disk, and `tests/phase0/test_reducer_purity.py`
enforces that neither of them imports this module.
"""
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml

from app.core.gates import GateConfig, HardBlockPolicy, TierPolicy

# backend/config/gates.yaml
GATES_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "gates.yaml"


def _tuple(value: Any) -> tuple:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return (value,)


def _tier_policy(raw: Mapping[str, Any]) -> TierPolicy:
    known = set(TierPolicy.__dataclass_fields__)
    unknown = set(raw) - known
    if unknown:
        raise ValueError(
            f"gates.yaml: unknown tier policy key(s) {sorted(unknown)} -- a "
            "silently ignored policy key is a policy that is not applied")

    kwargs: dict[str, Any] = {}
    for key, value in raw.items():
        field_type = TierPolicy.__dataclass_fields__[key].type
        kwargs[key] = _tuple(value) if "tuple" in str(field_type) else value
    return TierPolicy(**kwargs)


@lru_cache(maxsize=4)
def load_gate_config(path: Path | None = None) -> GateConfig:
    raw = yaml.safe_load((path or GATES_CONFIG_PATH).read_text(encoding="utf-8"))
    hard = raw["hard_blocks"]
    return GateConfig(
        version=raw["version"],
        hard_blocks=HardBlockPolicy(
            required_entity_status=hard["required_entity_status"],
            min_shock_magnitude_confidence=float(hard["min_shock_magnitude_confidence"]),
            no_impact_buckets=_tuple(hard["no_impact_buckets"])),
        primary=_tier_policy(raw["primary"]),
        secondary=_tier_policy(raw["secondary"]))


@lru_cache(maxsize=4)
def load_sensitivity_policy(path: Path | None = None):
    """V5 PHASE 2 -- the sign-consistency thresholds, from
    `config/materiality.yaml`.

    Parsed by `app.analysis.sensitivity.config` so that the reducer's rule
    and the engine that produces the number read ONE file through ONE parser
    and cannot drift apart. The reducer itself still imports nothing that
    touches a disk; it receives the frozen policy in its config.
    """
    from app.analysis.sensitivity.config import load_materiality_config
    from app.core.reducer import SensitivityPolicy

    config = load_materiality_config(path)
    return SensitivityPolicy(
        directional_claim_min=config.directional_claim_min,
        secondary_min=config.secondary_min,
        mixed_requires_material_tail_pct=config.mixed_requires_material_tail_pct)


@lru_cache(maxsize=4)
def load_reducer_config(path: Path | None = None):
    """The `ReducerConfig` the deployed policy implies. Separate from
    `load_gate_config` so a caller that only wants to inspect the gate does
    not construct a reducer config."""
    from app.core.reducer import ReducerConfig

    # `path` is the GATE policy's path; the sensitivity policy always comes
    # from its own deployed file (config/materiality.yaml).
    return ReducerConfig(gate_config=load_gate_config(path),
                         sensitivity_policy=load_sensitivity_policy())
