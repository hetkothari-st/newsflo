"""TASK 2.1 -- channel computation (spec §5.1).

One `(company, shock, exposure)` triple becomes one CHANNEL: a signed
delta-EBITDA in rupees, with the exposure row that authorises it, the
evidence behind it, the source of every parameter, the horizon it was
evaluated at, and the mechanism it travelled through.

THE FORMULAS ARE THE SPEC'S, VERBATIM WHERE THE SPEC IS EXPLICIT:

  COST                 -base x share x delta x (1-pass_through)
                         x (1-hedge_ratio) x ownership
  INVENTORY_REVALUATION
                       +inventory x share x delta
                         x inventory_realization_fraction x ownership
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
  * V5 PHASE 4 adds INVENTORY_REVALUATION, the channel §8 says dominates the
    IMMEDIATE horizon for commodity processors and the one the V4 OMC
    contradiction was missing. §8 states the mechanism ("inventory
    revaluation") and not a formula, so the formula is written down here:
    the exposed slice of the inventory position is revalued by the price
    move, and `inventory_realization_fraction` -- a ledger parameter, a curve
    like every other -- says how much of that revaluation lands in the P&L
    at the horizon being evaluated. It decays with the horizon because a
    revaluation is a one-off; it is NEVER defaulted, so an inventory exposure
    with no such parameter is uncomputable.

POLICY MODIFIERS (V5 PHASE 4). `evaluate` applies the registered transfer
functions INSIDE the closed form, after the §5.1 formula and before the
result is returned, so the Monte Carlo re-evaluates the whole distribution
under the modifier. A levy that caps the upside narrows the band too; a
modifier applied to the point estimate afterwards would not. The functions
themselves live in `app/analysis/policy/transfer.py`, which this module
imports and which imports nothing back.

NO DEFAULTS. A required parameter that is absent raises
`InsufficientParameterData`; an exposure kind with no §5.1 formula raises the
same. A channel that cannot be computed is not a channel.

PURE. No DB, no clock, no randomness: the caller resolves the parameters and
hands them in. `app/analysis/sensitivity/engine.py` is the impure sibling
that reads the ledger.
"""
from dataclasses import dataclass, field
from typing import Callable, Mapping

from app.analysis.policy.transfer import apply_factor
from app.analysis.sensitivity.config import MaterialityConfig, load_materiality_config
from app.analysis.sensitivity.params import (
    InsufficientParameterData, ParamDist, REASON_MISSING_ROW, REASON_NO_FORMULA,
    resolve_param,  # noqa: F401 (re-export)
)

# Phase 0/1 use a single horizon bucket; Phase 4 adds IMMEDIATE and
# STRUCTURAL. The label travels with the channel so the addition is not a
# schema change.
NEAR_TERM = "NEAR_TERM"

# Best (i.e. strongest) evidence grade first, so "the weakest cap wins" is a
# comparison rather than a special case.
_GRADE_ORDER = ("A", "B", "C", "D", "E")

# WHICH P&L LINE A CHANNEL MOVES (fix round 1, concern 4b). Five of the six
# channels move EBITDA. The interest-rate channel moves the interest line,
# which sits BELOW EBITDA -- §5.1 still divides it by EBITDA_ttm to get a
# comparable percentage, but the record must not let the field name imply the
# effect is an EBITDA effect, and the renderer must not print it as one.
BASE_EBITDA = "EBITDA"
BASE_PRE_TAX_INTEREST_LINE = "PRE_TAX_INTEREST_LINE"

# How a channel's `segment_ownership_fraction` was arrived at.
OWNERSHIP_SELF_CONSOLIDATED = "SELF_CONSOLIDATED"   # the company's own line
OWNERSHIP_SUPPLIED = "SUPPLIED"                     # an attached exposure


@dataclass(frozen=True)
class ExposureView:
    """One `company_exposure` row as the channel formulas see it.

    `segment_ownership_fraction` is NEVER defaulted here, and since fix round
    1 it is not defaulted in the engine either: it is either 1.0 under the
    stated SELF_CONSOLIDATED rule (a company owns all of its own P&L line) or
    a value the caller supplied for an attached exposure. `ownership_basis`
    records WHICH, so the choice is visible in the channel rather than buried
    in a dictionary lookup.
    """
    exposure_id: str
    company_id: int
    exposure_kind: str
    exposure_tag: str
    base_value_inr: float
    share_of_base: float
    segment_ownership_fraction: float
    evidence_ids: tuple[str, ...] = ()
    ownership_basis: str = OWNERSHIP_SELF_CONSOLIDATED


@dataclass(frozen=True)
class UncomputableChannel:
    """A channel that could NOT be sized, and why (fix round 1, I3).

    Abstention is the right behaviour; abstaining silently is not. Every one
    of these is reported on the run, logged, and carried into the published
    materiality block, so "this company dropped out" is always answerable.
    """
    channel_id: str
    reason: str                      # one of params.UNCOMPUTABLE_REASONS
    param: str | None = None

    def as_dict(self) -> dict:
        return {"channel_id": self.channel_id, "reason": self.reason,
                "param": self.param}


@dataclass(frozen=True)
class Shock:
    """The change in the exposed variable. `delta_pct` is a fraction (0.10 is
    +10%); for INTEREST_RATE it is an absolute rate delta (0.005 is +50bp).

    `level_before` / `level_after` are the LEVEL of the exposed variable on
    either side of the move (a price per barrel, a price per mmbtu). Phase 4
    needs them because a threshold or an administered ceiling is a statement
    about a level, not about a percentage. They are OPTIONAL and default to
    None: a shock that does not know the level is not broken, it simply
    cannot be measured against a threshold, and the modifier that needs one
    widens rather than assuming it.
    """
    shock_id: str
    exposure_tag: str
    delta_pct: float
    horizon_days: int
    mechanism_id: str | None = None
    level_before: float | None = None
    level_after: float | None = None


@dataclass(frozen=True)
class AppliedModifier:
    """One policy modifier, as it acted on one channel (V5 Phase 4).

    `factor` is what the transfer function returned and what `evaluate`
    multiplies by; for STATE_DEPENDENT it is the identity because that type
    acts on the channel's PARAMETERS instead (see
    `app/analysis/policy/transfer.state_dependent`).
    """
    modifier_id: str
    modifier_type: str
    factor: float = 1.0

    def as_dict(self) -> dict:
        return {"modifier_id": self.modifier_id,
                "modifier_type": self.modifier_type,
                "factor": self.factor}


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
    # Which P&L line this channel actually moves, and how its ownership
    # fraction was arrived at. Both travel with the number.
    materiality_base: str = BASE_EBITDA
    segment_ownership_fraction: float = 1.0
    ownership_basis: str = OWNERSHIP_SELF_CONSOLIDATED
    exposure_stale: bool = False
    delta_ebitda_inr: float = field(default=0.0)
    # --- V5 PHASE 4 -------------------------------------------------------
    # The level of the exposed variable on either side of the move, carried
    # from the Shock so a threshold or a ceiling has something to compare
    # against. None = the shock did not say.
    level_before: float | None = None
    level_after: float | None = None
    # The policy modifiers that acted on THIS channel, in application order,
    # and the human-readable notes any of them left (an unknown regime, a
    # missing level). Both travel with the number into the signal payload.
    modifiers: tuple[AppliedModifier, ...] = ()
    policy_notes: tuple[str, ...] = ()

    def evaluate(self, values: Mapping[str, float]) -> float:
        """The channel's delta-EBITDA under a specific set of parameter
        values (the point estimate, or one Monte Carlo draw), AFTER every
        policy modifier that applied to it."""
        return apply_factor(
            FORMULAS[self.channel_type](self.constants, values),
            (modifier.factor for modifier in self.modifiers))


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


def _inventory_revaluation(c: Mapping[str, float], p: Mapping[str, float]) -> float:
    """V5 PHASE 4 / spec §8. The exposed slice of the inventory position is
    revalued by the price move; `inventory_realization_fraction` is how much
    of that revaluation reaches the P&L at the horizon evaluated."""
    return +(c["base_value_inr"] * c["share_of_base"] * c["delta_pct"]
             * p["inventory_realization_fraction"]
             * c["segment_ownership_fraction"])


FORMULAS: Mapping[str, Callable[[Mapping[str, float], Mapping[str, float]], float]] = {
    "COST": _cost,
    "INVENTORY_REVALUATION": _inventory_revaluation,
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
    "INVENTORY": "INVENTORY_REVALUATION",
    "REVENUE_REALIZATION": "REVENUE_REALIZATION",
    "VOLUME_DEMAND": "VOLUME_DEMAND",
    "FX_TRANSACTION": "FX_TRANSACTION",
    "FX_TRANSLATION": "FX_TRANSLATION",
    "INTEREST_RATE": "INTEREST_RATE",
}

MATERIALITY_BASE_FOR_TYPE: Mapping[str, str] = {
    "COST": BASE_EBITDA,
    "INVENTORY_REVALUATION": BASE_EBITDA,
    "REVENUE_REALIZATION": BASE_EBITDA,
    "VOLUME_DEMAND": BASE_EBITDA,
    "FX_TRANSACTION": BASE_EBITDA,
    "FX_TRANSLATION": BASE_EBITDA,
    "INTEREST_RATE": BASE_PRE_TAX_INTEREST_LINE,
}

REQUIRED_PARAMS: Mapping[str, tuple[str, ...]] = {
    "COST": ("pass_through", "hedge_ratio"),
    "INVENTORY_REVALUATION": ("inventory_realization_fraction",),
    "REVENUE_REALIZATION": ("realization_elasticity", "regulatory_capture_fraction"),
    "VOLUME_DEMAND": ("demand_elasticity", "contribution_margin"),
    "FX_TRANSACTION": ("natural_hedge_fraction", "hedge_ratio"),
    "FX_TRANSLATION": ("net_investment_hedge_ratio",),
    "INTEREST_RATE": ("hedge_ratio", "repricing_fraction"),
}


def weakest_grade_cap(caps) -> str | None:
    """The WORST (weakest) evidence-grade cap among several, or None when
    nothing caps anything. Public because Phase 4's modifier layer caps at C
    and must combine its cap with the parameter caps computed here."""
    present = [c for c in caps if c]
    if not present:
        return None
    return max(present, key=lambda grade: _GRADE_ORDER.index(grade)
               if grade in _GRADE_ORDER else len(_GRADE_ORDER))


_weakest_cap = weakest_grade_cap


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
            f"The channel is UNCOMPUTABLE and publishes nothing.",
            reason=REASON_MISSING_ROW, param=sorted(missing)[0])

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
        materiality_base=MATERIALITY_BASE_FOR_TYPE[channel_type],
        segment_ownership_fraction=float(exposure.segment_ownership_fraction),
        ownership_basis=str(exposure.ownership_basis),
        level_before=shock.level_before,
        level_after=shock.level_after,
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


def inventory_revaluation_channel(exposure: ExposureView, shock: Shock,
                                  params: Mapping[str, ParamDist],
                                  horizon_days: int, *, horizon: str = NEAR_TERM,
                                  config: MaterialityConfig | None = None) -> ChannelResult:
    return _build("INVENTORY_REVALUATION", exposure, shock, params, horizon_days,
                  horizon=horizon, config=config)


CHANNEL_FUNCTIONS: Mapping[str, Callable[..., ChannelResult]] = {
    "COST": cost_channel,
    "INVENTORY_REVALUATION": inventory_revaluation_channel,
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
            f"cannot be sized, so it publishes nothing.",
            reason=REASON_NO_FORMULA)
    return CHANNEL_FUNCTIONS[channel_type](
        exposure, shock, params, horizon_days, horizon=horizon, config=config)
