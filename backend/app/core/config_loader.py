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
    policy = TierPolicy(**kwargs)

    # V5 PHASE 3 / A5.1: `min_evidence_grade` and `evidence_grades` are two
    # spellings of ONE policy. A file where they disagree is a file where
    # nobody knows which one publishes, so it is refused rather than
    # resolved -- resolving it would mean picking a winner silently.
    if policy.min_evidence_grade is not None:
        if not policy.evidence_grades:
            raise ValueError(
                "gates.yaml: min_evidence_grade is set but evidence_grades is "
                "empty")
        if policy.evidence_grades[-1] != policy.min_evidence_grade:
            raise ValueError(
                f"gates.yaml: min_evidence_grade "
                f"{policy.min_evidence_grade!r} contradicts evidence_grades "
                f"{list(policy.evidence_grades)} (whose weakest entry is "
                f"{policy.evidence_grades[-1]!r}). One policy, one value.")
    return policy


@lru_cache(maxsize=4)
def load_gate_config(path: Path | None = None) -> GateConfig:
    raw = yaml.safe_load((path or GATES_CONFIG_PATH).read_text(encoding="utf-8"))
    hard = raw["hard_blocks"]
    # A5.1 names the ripple block `secondary_ripple`; Phase 0 deployed it as
    # `secondary`. Both spellings load into the SAME policy so that renaming
    # the key could not quietly change what publishes. A file carrying both
    # is refused: two blocks with one meaning is a config nobody can read.
    if "secondary_ripple" in raw and "secondary" in raw:
        raise ValueError(
            "gates.yaml: both `secondary` and `secondary_ripple` are present. "
            "They are two spellings of one policy -- keep `secondary_ripple` "
            "(addendum A5.1) and delete the other.")
    secondary = raw.get("secondary_ripple", raw.get("secondary"))
    if secondary is None:
        raise ValueError("gates.yaml: no `secondary_ripple` block")
    return GateConfig(
        version=raw["version"],
        hard_blocks=HardBlockPolicy(
            required_entity_status=hard["required_entity_status"],
            min_shock_magnitude_confidence=float(hard["min_shock_magnitude_confidence"]),
            no_impact_buckets=_tuple(hard["no_impact_buckets"])),
        primary=_tier_policy(raw["primary"]),
        secondary=_tier_policy(secondary))


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
def load_horizon_policy(path: Path | None = None):
    """V5 PHASE 4 -- the headline-selection weights, from
    `config/horizons.yaml`.

    Parsed by `app.analysis.sensitivity.horizons` so that the engine which
    evaluates the three horizons and the reducer which ranks them read ONE
    file through ONE parser. The reducer itself still imports nothing that
    touches a disk; it receives the frozen policy in its config.
    """
    from app.analysis.sensitivity.horizons import load_horizon_config
    from app.core.reducer import HorizonPolicy

    config = load_horizon_config(path)
    return HorizonPolicy(materiality_weight=config.materiality_weight,
                         tie_break=config.tie_break)


@lru_cache(maxsize=4)
def load_reducer_config(path: Path | None = None):
    """The `ReducerConfig` the deployed policy implies. Separate from
    `load_gate_config` so a caller that only wants to inspect the gate does
    not construct a reducer config."""
    from app.core.reducer import ReducerConfig

    # `path` is the GATE policy's path; the sensitivity policy always comes
    # from its own deployed file (config/materiality.yaml).
    return ReducerConfig(gate_config=load_gate_config(path),
                         sensitivity_policy=load_sensitivity_policy(),
                         horizon_policy=load_horizon_policy())
