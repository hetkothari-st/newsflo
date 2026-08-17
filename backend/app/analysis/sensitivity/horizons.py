"""TASK 4.3 -- the three horizons, and how a headline is chosen among them.

`config/horizons.yaml`, frozen into a dataclass, plus the two pure functions
the reducer and the engine both need. Deliberately IMPURE (it reads a file)
and deliberately tiny, exactly like `app/analysis/sensitivity/config.py`.

    IMMEDIATE    0-5 trading days      inventory revaluation, mark-to-market
    NEAR_TERM    current + next qtr    margin transmission, pass-through lag
    STRUCTURAL   2-4 quarters          capex, competitive position, demand

Each horizon runs its OWN channel computation with `pass_through(horizon_days)`
and `hedge_ratio_effective(horizon_days)` evaluated at that horizon (spec §8).
Nothing here averages them, and nothing here discards the two that are not the
headline -- discarding them is precisely how V4 produced three contradictory
Oil India representations.

There is no fallback anywhere in this file. A missing section raises.
"""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping

import yaml

# backend/config/horizons.yaml
HORIZONS_CONFIG_PATH = (
    Path(__file__).resolve().parents[3] / "config" / "horizons.yaml")

IMMEDIATE = "IMMEDIATE"
NEAR_TERM = "NEAR_TERM"
STRUCTURAL = "STRUCTURAL"

# The order is the TIME order, and it is the order every record, payload and
# renderer walks. It is not a preference ranking.
HORIZON_ORDER = (IMMEDIATE, NEAR_TERM, STRUCTURAL)


class HorizonConfigError(KeyError):
    """The policy file does not say something the engine needs it to say."""


@dataclass(frozen=True)
class HorizonConfig:
    version: str
    order: tuple[str, ...]
    days: Mapping[str, int]
    window: Mapping[str, str]
    dominated_by: Mapping[str, str]
    tie_break: str
    materiality_weight: Mapping[str, float]

    def weight_for(self, bucket: str) -> float:
        try:
            return float(self.materiality_weight[str(bucket)])
        except KeyError as exc:                        # pragma: no cover
            raise HorizonConfigError(
                f"config/horizons.yaml has no materiality_weight for bucket "
                f"{bucket!r}. A weight invented here would be a ranking "
                f"nobody chose.") from exc


@lru_cache(maxsize=4)
def load_horizon_config(path: Path | None = None) -> HorizonConfig:
    raw = yaml.safe_load((path or HORIZONS_CONFIG_PATH).read_text(encoding="utf-8"))
    try:
        horizons = raw["horizons"]
        missing = [name for name in HORIZON_ORDER if name not in horizons]
        if missing:
            raise HorizonConfigError(
                f"config/horizons.yaml does not define {missing}. All three "
                f"horizons are mandatory: a config that can omit one is a "
                f"config that can collapse the vector.")
        return HorizonConfig(
            version=str(raw["version"]),
            order=HORIZON_ORDER,
            days={name: int(horizons[name]["days"]) for name in HORIZON_ORDER},
            window={name: str(horizons[name]["window"]) for name in HORIZON_ORDER},
            dominated_by={name: str(horizons[name]["dominated_by"])
                          for name in HORIZON_ORDER},
            tie_break=str(raw["headline"]["tie_break"]),
            materiality_weight={str(k): float(v)
                                for k, v in raw["materiality_weight"].items()})
    except (KeyError, TypeError) as exc:               # pragma: no cover
        raise HorizonConfigError(
            f"config/horizons.yaml is missing {exc}") from exc


def select_headline(scored: Mapping[str, float],
                    config: HorizonConfig | None = None) -> str | None:
    """§8's rule: the horizon with the largest score, tie-broken toward
    NEAR_TERM.

    `scored` is `{horizon: |delta_ebitda_pct_p50| x materiality_weight}` over
    the horizons that were actually EVALUATED. An empty mapping has no
    headline, which is a different statement from "the headline is NEAR_TERM".
    """
    config = config or load_horizon_config()
    if not scored:
        return None
    best = max(scored.values())
    tied = [name for name, value in scored.items() if value == best]
    if len(tied) == 1:
        return tied[0]
    if config.tie_break in tied:
        return config.tie_break
    # Still tied and the tie-break horizon is not among them: fall back to the
    # TIME order, which is stable and stated, rather than to dictionary order.
    return next(name for name in config.order if name in tied)
