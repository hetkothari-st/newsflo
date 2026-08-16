"""TASK 1.1 -- freshness policy, loaded from `config/freshness.yaml`.

Deliberately impure (it reads a file) and deliberately tiny. The numbers
live in the YAML so that "how old is too old" is a policy decision in the
open, not a constant buried in a module.

There is no fallback. A kind the policy does not name raises
`FreshnessNotConfigured`, because a default freshness invented here would
silently authorise a claim on a disclosure nobody decided to trust.
"""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping

import yaml

# backend/config/freshness.yaml
FRESHNESS_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "freshness.yaml"


class FreshnessNotConfigured(KeyError):
    """No freshness policy exists for this exposure kind. Missing is
    missing: the caller must supply an explicit value or refuse the row."""


@dataclass(frozen=True)
class FreshnessConfig:
    version: str
    freshness_days: Mapping[str, int]
    p90_age_alert_days: int


@lru_cache(maxsize=4)
def load_freshness_config(path: Path | None = None) -> FreshnessConfig:
    raw = yaml.safe_load((path or FRESHNESS_CONFIG_PATH).read_text(encoding="utf-8"))
    return FreshnessConfig(
        version=str(raw["version"]),
        freshness_days={str(k): int(v) for k, v in raw["freshness_days"].items()},
        p90_age_alert_days=int(raw["p90_age_alert_days"]))


def freshness_days_for(exposure_kind: str, path: Path | None = None) -> int:
    config = load_freshness_config(path)
    try:
        return config.freshness_days[str(exposure_kind)]
    except KeyError as exc:
        raise FreshnessNotConfigured(
            f"config/freshness.yaml has no freshness_days for exposure_kind "
            f"{exposure_kind!r}. Supply one explicitly at approval time -- a "
            f"default invented here would be a policy nobody chose."
        ) from exc


def p90_age_alert_days(path: Path | None = None) -> int:
    return load_freshness_config(path).p90_age_alert_days
