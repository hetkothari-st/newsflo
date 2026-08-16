"""TASK 2.1 -- channel computation (spec §5.1).

One `(company, shock, exposure)` triple becomes one CHANNEL: a signed
delta-EBITDA in rupees, with the exposure row that authorises it, the
evidence behind it, the source of every parameter, the horizon it was
evaluated at, and the mechanism it travelled through.

THE FORMULAS ARE THE SPEC'S, VERBATIM WHERE THE SPEC IS EXPLICIT:

  COST                 -base x share x delta x (1-pass_through)
                         x (1-hedge_ratio) x ownership
  REVENUE_REALIZATION  +base x share x delta x realization_elasticity
                         x (1-regulatory_capture_fraction) x ownership
  VOLUME_DEMAND        +revenue_base x demand_elasticity x delta
                         x contribution_margin x ownership
  FX_TRANSACTION       +base x share x delta x (1-natural_hedge_fraction)
                         x (1-hedge_ratio) x ownership
  FX_TRANSLATION       +base x share x delta
                         x (1-net_investment_hedge_ratio) x ownership
  INTEREST_RATE        -base x share x delta x (1-hedge_ratio)
                         x repricing_fraction x ownership

WHERE THE SPEC LEAVES A CHOICE, it is written down rather than smuggled:

  * §5.1 says "FX / RATE CHANNELS -- analogous, using net exposure after
    natural hedge". The two FX channels are split because they are different
    exposures with different hedges: a transaction exposure is covered by a
    natural hedge plus forwards; a translation exposure is covered (if at
    all) by a net-investment hedge. Collapsing them would put a forward cover
    ratio on a subsidiary's balance sheet.
  * §5.1's VOLUME_DEMAND `revenue_base` is `base_value_inr x share_of_base`
    -- the exposed slice of revenue, the same shape as every other channel --
    and ownership is applied as everywhere else, because a listco owns only
    its fraction of a segment.
  * INTEREST_RATE `shock.delta_pct` is an ABSOLUTE rate change expressed as a
    fraction (0.005 == +50bp), not a percentage change of the rate. Every
    other channel's delta is a relative change of the exposed variable.
  * an interest expense sits BELOW EBITDA. The field keeps the spec's name
    (`delta_ebitda_inr`) and the ratio is taken against EBITDA_ttm as §5.1
    defines it, but the number is a change in the interest line, not in
    EBITDA. Recorded in DATA_GAPS.md §6 -- when a P&L-line-aware materiality
    base exists, this channel should use it.

NO DEFAULTS. A required parameter that is absent raises
`InsufficientParameterData`; an exposure kind with no §5.1 formula raises the
same. A channel that cannot be computed is not a channel.

PURE. No DB, no clock, no randomness: the caller resolves the parameters and
hands them in. `app/analysis/sensitivity/engine.py` is the impure sibling
that reads the ledger.
"""
from dataclasses import dataclass, field
from typing import Callable, Mapping

from app.analysis.sensitivity.config import MaterialityConfig, load_materiality_config
from app.analysis.sensitivity.params import (
    InsufficientParameterData, ParamDist, resolve_param,  # noqa: F401 (re-export)
)

# Phase 0/1 use a single horizon bucket; Phase 4 adds IMMEDIATE and
# STRUCTURAL. The label travels with the channel so the addition is not a
# schema change.
NEAR_TERM = "NEAR_TERM"

# Best (i.e. strongest) evidence grade first, so "the weakest cap wins" is a
# comparison rather than a special case.
_GRADE_ORDER = ("A", "B", "C", "D", "E")


@dataclass(frozen=True)
class ExposureView:
    """One `company_exposure` row as the channel formulas see it.

    `segment_ownership_fraction` is NEVER defaulted here. The engine supplies
    1.0 only for a company's OWN exposure row -- a company owns all of its
    own P&L line, which is a structural fact, not an estimate -- and for an
    exposure attached from another entity it comes from Phase 1's
    `attach_exposure_to_listco`, which refuses to attach at all when the
    ownership fraction is unknown.
    """
    exposure_id: str
    company_id: int
    exposure_kind: str
    exposure_tag: str
    base_value_inr: float
    share_of_base: float
    segment_ownership_fraction: float
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Shock:
    """The change in the exposed variable. `delta_pct` is a fraction (0.10 is
    +10%); for INTEREST_RATE it is an absolute rate delta (0.005 is +50bp)."""
    shock_id: str
    exposure_tag: str
    delta_pct: float
    horizon_days: int
    mechanism_id: str | None = None


@dataclass(frozen=True)
class ChannelResult:
    """Phase file Task 2.1: every ChannelResult carries `exposure_id`,
    `evidence_ids`, `param_sources`, `horizon` and `mechanism_id`.

    `params` and `constants` are kept so the Monte Carlo can re-evaluate the
    SAME closed form under drawn parameters -- the band is the same function
    as the point estimate, not an approximation of it.
    """
    channel_id: str
    channel_type: str
    exposure_id: str
    evidence_ids: tuple[str, ...]
    param_sources: Mapping[str, str]
    horizon: str
    horizon_days: int
    mechanism_id: str | None
    params: Mapping[str, ParamDist]
    constants: Mapping[str, float]
    grade_cap: str | None
    exposure_stale: bool = False
    delta_ebitda_inr: float = field(default=0.0)

    def evaluate(self, values: Mapping[str, float]) -> float:
        """The channel's delta-EBITDA under a specific set of parameter
        values (the point estimate, or one Monte Carlo draw)."""
        return FORMULAS[self.channel_type](self.constants, values)


# --- the closed forms -------------------------------------------------------
# Each takes the exposure-derived constants and the parameter VALUES, and is
# a total function of them. Nothing here reads a default.

def _cost(c: Mapping[str, float], p: Mapping[str, float]) -> float:
    return -(c["base_value_inr"] * c["share_of_base"] * c["delta_pct"]
             * (1.0 - p["pass_through"]) * (1.0 - p["hedge_ratio"])
             * c["segment_ownership_fraction"])


def _revenue_realization(c: Mapping[str, float], p: Mapping[str, float]) -> float:
    return +(c["base_value_inr"] * c["share_of_base"] * c["delta_pct"]
             * p["realization_elasticity"]
             * (1.0 - p["regulatory_capture_fraction"])
             * c["segment_ownership_fraction"])


def _volume_demand(c: Mapping[str, float], p: Mapping[str, float]) -> float:
    return +(c["base_value_inr"] * c["share_of_base"] * p["demand_elasticity"]
             * c["delta_pct"] * p["contribution_margin"]
             * c["segment_ownership_fraction"])


def _fx_transaction(c: Mapping[str, float], p: Mapping[str, float]) -> float:
    return +(c["base_value_inr"] * c["share_of_base"] * c["delta_pct"]
             * (1.0 - p["natural_hedge_fraction"]) * (1.0 - p["hedge_ratio"])
             * c["segment_ownership_fraction"])


def _fx_translation(c: Mapping[str, float], p: Mapping[str, float]) -> float:
    return +(c["base_value_inr"] * c["share_of_base"] * c["delta_pct"]
             * (1.0 - p["net_investment_hedge_ratio"])
             * c["segment_ownership_fraction"])


def _interest_rate(c: Mapping[str, float], p: Mapping[str, float]) -> float:
    return -(c["base_value_inr"] * c["share_of_base"] * c["delta_pct"]
             * (1.0 - p["hedge_ratio"]) * p["repricing_fraction"]
             * c["segment_ownership_fraction"])


FORMULAS: Mapping[str, Callable[[Mapping[str, float], Mapping[str, float]], float]] = {
    "COST": _cost,
    "REVENUE_REALIZATION": _revenue_realization,
    "VOLUME_DEMAND": _volume_demand,
    "FX_TRANSACTION": _fx_transaction,
    "FX_TRANSLATION": _fx_translation,
    "INTEREST_RATE": _interest_rate,
}

# `company_exposure.exposure_kind` -> channel type. The three ledger kinds
# with no §5.1 formula (REGULATORY, LOGISTICS_ENERGY,
# CUSTOMER_CONCENTRATION) are DELIBERATELY ABSENT: they raise, rather than
# borrowing the nearest formula that happens to typecheck.
CHANNEL_FOR_KIND: Mapping[str, str] = {
    "INPUT_COST": "COST",
    "REVENUE_REALIZATION": "REVENUE_REALIZATION",
    "VOLUME_DEMAND": "VOLUME_DEMAND",
    "FX_TRANSACTION": "FX_TRANSACTION",
    "FX_TRANSLATION": "FX_TRANSLATION",
    "INTEREST_RATE": "INTEREST_RATE",
}

REQUIRED_PARAMS: Mapping[str, tuple[str, ...]] = {
    "COST": ("pass_through", "hedge_ratio"),
    "REVENUE_REALIZATION": ("realization_elasticity", "regulatory_capture_fraction"),
    "VOLUME_DEMAND": ("demand_elasticity", "contribution_margin"),
    "FX_TRANSACTION": ("natural_hedge_fraction", "hedge_ratio"),
    "FX_TRANSLATION": ("net_investment_hedge_ratio",),
    "INTEREST_RATE": ("hedge_ratio", "repricing_fraction"),
}


def _weakest_cap(caps) -> str | None:
    present = [c for c in caps if c]
    if not present:
        return None
    return max(present, key=lambda grade: _GRADE_ORDER.index(grade)
               if grade in _GRADE_ORDER else len(_GRADE_ORDER))


def _build(channel_type: str, exposure: ExposureView, shock: Shock,
           params: Mapping[str, ParamDist], horizon_days: int, *,
           horizon: str, config: MaterialityConfig | None) -> ChannelResult:
    config = config or load_materiality_config()
    required = REQUIRED_PARAMS[channel_type]
    missing = [name for name in required if name not in params]
    if missing:
        raise InsufficientParameterData(
            f"{channel_type} channel on {exposure.exposure_tag!r} needs "
            f"{sorted(missing)} and the ledger has no sourced value for them. "
            f"The channel is UNCOMPUTABLE and publishes nothing.")

    used = {name: params[name] for name in required}
    constants = {
        "base_value_inr": float(exposure.base_value_inr),
        "share_of_base": float(exposure.share_of_base),
        "delta_pct": float(shock.delta_pct),
        "segment_ownership_fraction": float(exposure.segment_ownership_fraction),
    }
    result = ChannelResult(
        channel_id=exposure.exposure_tag,
        channel_type=channel_type,
        exposure_id=exposure.exposure_id,
        evidence_ids=tuple(exposure.evidence_ids),
        param_sources={name: dist.source for name, dist in used.items()},
        horizon=horizon,
        horizon_days=int(horizon_days),
        mechanism_id=shock.mechanism_id,
        params=used,
        constants=constants,
        grade_cap=_weakest_cap(
            config.evidence_grade_cap.get(dist.source) for dist in used.values()),
    )
    point = result.evaluate({name: dist.point for name, dist in used.items()})
    return ChannelResult(**{**result.__dict__, "delta_ebitda_inr": point})


# --- the six channel types, as the phase file names them --------------------

def cost_channel(exposure: ExposureView, shock: Shock,
                 params: Mapping[str, ParamDist], horizon_days: int, *,
                 horizon: str = NEAR_TERM,
                 config: MaterialityConfig | None = None) -> ChannelResult:
    return _build("COST", exposure, shock, params, horizon_days,
                  horizon=horizon, config=config)


def revenue_realization_channel(exposure: ExposureView, shock: Shock,
                                params: Mapping[str, ParamDist], horizon_days: int,
                                *, horizon: str = NEAR_TERM,
                                config: MaterialityConfig | None = None) -> ChannelResult:
    return _build("REVENUE_REALIZATION", exposure, shock, params, horizon_days,
                  horizon=horizon, config=config)


def volume_demand_channel(exposure: ExposureView, shock: Shock,
                          params: Mapping[str, ParamDist], horizon_days: int, *,
                          horizon: str = NEAR_TERM,
                          config: MaterialityConfig | None = None) -> ChannelResult:
    return _build("VOLUME_DEMAND", exposure, shock, params, horizon_days,
                  horizon=horizon, config=config)


def fx_transaction_channel(exposure: ExposureView, shock: Shock,
                           params: Mapping[str, ParamDist], horizon_days: int, *,
                           horizon: str = NEAR_TERM,
                           config: MaterialityConfig | None = None) -> ChannelResult:
    return _build("FX_TRANSACTION", exposure, shock, params, horizon_days,
                  horizon=horizon, config=config)


def fx_translation_channel(exposure: ExposureView, shock: Shock,
                           params: Mapping[str, ParamDist], horizon_days: int, *,
                           horizon: str = NEAR_TERM,
                           config: MaterialityConfig | None = None) -> ChannelResult:
    return _build("FX_TRANSLATION", exposure, shock, params, horizon_days,
                  horizon=horizon, config=config)


def interest_rate_channel(exposure: ExposureView, shock: Shock,
                          params: Mapping[str, ParamDist], horizon_days: int, *,
                          horizon: str = NEAR_TERM,
                          config: MaterialityConfig | None = None) -> ChannelResult:
    return _build("INTEREST_RATE", exposure, shock, params, horizon_days,
                  horizon=horizon, config=config)


CHANNEL_FUNCTIONS: Mapping[str, Callable[..., ChannelResult]] = {
    "COST": cost_channel,
    "REVENUE_REALIZATION": revenue_realization_channel,
    "VOLUME_DEMAND": volume_demand_channel,
    "FX_TRANSACTION": fx_transaction_channel,
    "FX_TRANSLATION": fx_translation_channel,
    "INTEREST_RATE": interest_rate_channel,
}


def compute_channel(exposure: ExposureView, shock: Shock,
                    params: Mapping[str, ParamDist], horizon_days: int, *,
                    horizon: str = NEAR_TERM,
                    config: MaterialityConfig | None = None) -> ChannelResult:
    """Dispatch on the ledger row's `exposure_kind`."""
    channel_type = CHANNEL_FOR_KIND.get(str(exposure.exposure_kind))
    if channel_type is None:
        raise InsufficientParameterData(
            f"exposure_kind {exposure.exposure_kind!r} has no §5.1 channel "
            f"formula. It is a real exposure and it is recorded, but it "
            f"cannot be sized, so it publishes nothing.")
    return CHANNEL_FUNCTIONS[channel_type](
        exposure, shock, params, horizon_days, horizon=horizon, config=config)
