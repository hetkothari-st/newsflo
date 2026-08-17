"""TASK 2.2 -- every parameter is a DISTRIBUTION, and TASK 2.1's
`resolve_param`, which has exactly three outcomes.

    1. the company's own value, from the ledger   -> FILED | DISCLOSED_CALL
                                                     (| MODELLED, see below)
    2. the sector median, computed from ledger
       rows at runtime                            -> SECTOR_PROXY, wider
                                                     band, evidence grade
                                                     capped at C
    3. nothing available                          -> InsufficientParameterData

THERE IS NO STEP 4. Not a "reasonable default", not a sector-wide constant
compiled into this file, not zero. The caller marks the channel UNCOMPUTABLE
and it does not publish. Every band width, distribution shape, grade cap and
domain bound comes from `config/materiality.yaml`.

WHERE THE VALUES COME FROM

  * `pass_through` is read off `pass_through_curve` (spec §4.2) and evaluated
    at the horizon -- it is a curve, never a scalar. `basis` says how it was
    measured: FILED / DISCLOSED_CALL for a disclosure, SECTOR_MEDIAN for a
    sector-level curve (which resolves as SECTOR_PROXY), ESTIMATED for a
    reviewed judgement (which resolves as MODELLED and is banded as widely
    as a proxy).
  * every other parameter is read off `company_modifier.parameters`, a JSON
    object which must say `measurement` -- FILED, DISCLOSED_CALL or MODELLED.
    A row that cannot say how it was measured cannot be banded, so it is NOT
    USED. Banding it as the more favourable of the two would be a guess about
    a company's disclosure. (Recorded in DATA_GAPS.md §6: `company_modifier`
    has no measurement column, so the extractor must put it in the JSON.)
  * a modifier may carry a horizon CURVE (`<param>_curve`) instead of a
    scalar, in which case it is evaluated at the horizon like a pass-through
    curve. Hedge cover, in particular, is not the same at 30 and 365 days.

PURE except for the SQL reads. No clock: `as_of` is always the caller's.
"""
from dataclasses import dataclass
from datetime import date
from statistics import median
from typing import Any, Mapping, Sequence

import json

from sqlalchemy import text

from app.analysis.sensitivity.config import (
    MaterialityConfig, load_materiality_config,
)

# Sources, in the spec's vocabulary (§5.2 `ParamDist.source`).
FILED = "FILED"
DISCLOSED_CALL = "DISCLOSED_CALL"
SECTOR_PROXY = "SECTOR_PROXY"
MODELLED = "MODELLED"
SOURCES = (FILED, DISCLOSED_CALL, SECTOR_PROXY, MODELLED)

# `pass_through_curve.basis` -> parameter source.
CURVE_BASIS_TO_SOURCE = {
    "FILED": FILED,
    "DISCLOSED_CALL": DISCLOSED_CALL,
    "SECTOR_MEDIAN": SECTOR_PROXY,
    "ESTIMATED": MODELLED,
}

# Measurements a `company_modifier.parameters` JSON may declare. SECTOR_PROXY
# is deliberately absent: a company row claiming to be a sector proxy is a
# contradiction, and the proxy path computes its own median.
MODIFIER_MEASUREMENTS = (FILED, DISCLOSED_CALL, MODELLED)

PASS_THROUGH = "pass_through"

# Every parameter the §5.1 channel formulas need. `resolve_param` refuses a
# name outside this set rather than searching for it and finding nothing --
# a typo must not look like missing data.
RESOLVABLE_PARAMS = (
    PASS_THROUGH,
    "hedge_ratio",
    "realization_elasticity",
    "regulatory_capture_fraction",
    "demand_elasticity",
    "contribution_margin",
    "natural_hedge_fraction",
    "net_investment_hedge_ratio",
    "repricing_fraction",
    # V5 PHASE 4: how much of an inventory revaluation reaches the P&L at the
    # horizon being evaluated (spec §8's inventory-revaluation channel). Like
    # every other parameter it is a ledger value or a sector median, never a
    # default -- and like hedge cover it is usually a CURVE, because a
    # revaluation is a one-off that decays as the horizon lengthens.
    "inventory_realization_fraction",
)


# WHY a channel could not be computed (fix round 1, I3). A channel that
# vanishes silently is indistinguishable from a company nobody looked at, so
# every abstention carries one of these and is logged.
REASON_MISSING_ROW = "MISSING_ROW"                  # nothing in the ledger
REASON_MISSING_MEASUREMENT = "MISSING_MEASUREMENT"  # a row, but unbandable
REASON_MISSING_OWNERSHIP = "MISSING_OWNERSHIP"      # no ownership fraction
REASON_NO_FORMULA = "NO_FORMULA"                    # no §5.1 formula exists
UNCOMPUTABLE_REASONS = (REASON_MISSING_ROW, REASON_MISSING_MEASUREMENT,
                        REASON_MISSING_OWNERSHIP, REASON_NO_FORMULA)


class InsufficientParameterData(LookupError):
    """No sourced value exists for this parameter, for this company, at this
    horizon -- and none may be invented. The channel is UNCOMPUTABLE.

    Carries a reason code and the parameter it is about, so the caller can
    report WHY rather than just that something is missing.
    """

    def __init__(self, message: str, *, reason: str = REASON_MISSING_ROW,
                 param: str | None = None):
        super().__init__(message)
        self.reason = reason
        self.param = param


class ParameterNameError(KeyError):
    """A parameter name outside the closed set."""


@dataclass(frozen=True)
class ParamDist:
    """Spec §5.2. `lo`/`hi` are the 10th and 90th percentiles of the belief,
    whatever the distribution shape, so a band means the same thing across
    sources."""
    name: str
    point: float
    lo: float
    hi: float
    dist: str               # "triangular" | "normal" | "uniform"
    source: str             # FILED | DISCLOSED_CALL | SECTOR_PROXY | MODELLED
    evidence_id: str | None = None

    def key(self) -> tuple:
        """Identity for Monte Carlo draw sharing: two channels resolving THE
        SAME parameter from the same evidence must move together, not
        independently."""
        return (self.name, self.point, self.lo, self.hi, self.dist, self.source,
                self.evidence_id)


@dataclass(frozen=True)
class ResolvedParam:
    dist: ParamDist
    grade_cap: str | None       # best evidence grade this parameter allows
    widened: bool               # band widened beyond its source's base width
    detail: str = ""            # where it came from, for the audit trail


# --- band construction ------------------------------------------------------

def band_for(point: float, source: str, *, name: str = "",
             config: MaterialityConfig | None = None,
             modifier_state_unknown: bool = False) -> tuple[float, float]:
    """The [lo, hi] band around a point value. Width comes from the source
    (a filed number is not a peer median) and is widened further when a
    policy modifier's state is UNKNOWN (Phase 4 hook)."""
    config = config or load_materiality_config()
    width = config.band_width_for(source)
    if modifier_state_unknown:
        width *= config.unknown_modifier_band_multiplier
    lo, hi = point * (1.0 - width), point * (1.0 + width)
    if point < 0:                       # a negative point inverts the order
        lo, hi = hi, lo
    bounds = config.param_bounds.get(name)
    if bounds is not None:
        lo = min(max(lo, bounds[0]), bounds[1])
        hi = min(max(hi, bounds[0]), bounds[1])
    return lo, hi


def dist_for(name: str, point: float, source: str, *,
             evidence_id: str | None = None,
             config: MaterialityConfig | None = None,
             modifier_state_unknown: bool = False) -> ParamDist:
    config = config or load_materiality_config()
    if source not in SOURCES:
        raise ParameterNameError(f"{source!r} is not one of {SOURCES}")
    lo, hi = band_for(point, source, name=name, config=config,
                      modifier_state_unknown=modifier_state_unknown)
    return ParamDist(name=name, point=float(point), lo=lo, hi=hi,
                     dist=config.distribution_for(source), source=source,
                     evidence_id=evidence_id)


def grade_cap_for(source: str, config: MaterialityConfig | None = None) -> str | None:
    config = config or load_materiality_config()
    return config.evidence_grade_cap.get(source)


# --- the pass-through curve -------------------------------------------------

def evaluate_curve(points: Sequence[Mapping[str, Any]], horizon_days: int,
                   ceiling: float | None = None) -> float:
    """Piecewise-linear interpolation between the curve's points.

    Before the first point the curve holds its first value; after the last it
    holds its last -- it is never extrapolated, because a curve that has only
    been observed to 90 days says nothing about 400 and pretending otherwise
    is how a pass-through assumption becomes fiction.
    """
    ordered = sorted(({"lag_days": float(p["lag_days"]),
                       "fraction": float(p["fraction"])} for p in points),
                     key=lambda p: p["lag_days"])
    if not ordered:
        raise InsufficientParameterData("pass-through curve has no points")
    horizon = float(horizon_days)
    if horizon <= ordered[0]["lag_days"]:
        value = ordered[0]["fraction"]
    elif horizon >= ordered[-1]["lag_days"]:
        value = ordered[-1]["fraction"]
    else:
        value = ordered[-1]["fraction"]
        for earlier, later in zip(ordered, ordered[1:]):
            if earlier["lag_days"] <= horizon <= later["lag_days"]:
                span = later["lag_days"] - earlier["lag_days"]
                weight = 0.0 if span == 0 else (horizon - earlier["lag_days"]) / span
                value = earlier["fraction"] + weight * (
                    later["fraction"] - earlier["fraction"])
                break
    if ceiling is not None:
        value = min(value, float(ceiling))
    return value


# --- ledger reads -----------------------------------------------------------

def _curve_rows(session, *, exposure_tag: str, as_of: date,
                company_id: int | None = None, sector_id: str | None = None):
    sql = ("SELECT curve_id, points, ceiling, basis, evidence_id, as_of_date "
           "FROM pass_through_curve WHERE exposure_tag = :tag "
           "  AND as_of_date <= :as_of ")
    parameters: dict = {"tag": exposure_tag, "as_of": as_of.isoformat()}
    if company_id is not None:
        sql += " AND company_id = :company_id"
        parameters["company_id"] = int(company_id)
    else:
        sql += " AND company_id IS NULL AND sector_id = :sector_id"
        parameters["sector_id"] = sector_id
    sql += " ORDER BY as_of_date DESC, curve_id ASC"
    return [dict(row) for row in session.execute(text(sql), parameters).mappings()]


def _modifier_rows(session, *, applies_to_tag: str, as_of: date,
                   company_id: int | None = None,
                   company_ids: Sequence[int] | None = None):
    sql = ("SELECT modifier_id, company_id, parameters, as_of_date "
           "FROM company_modifier WHERE applies_to_tag = :tag "
           "  AND effective_from <= :as_of "
           "  AND (effective_to IS NULL OR effective_to >= :as_of) ")
    parameters: dict = {"tag": applies_to_tag, "as_of": as_of.isoformat()}
    if company_id is not None:
        sql += " AND company_id = :company_id"
        parameters["company_id"] = int(company_id)
    elif company_ids is not None:
        if not company_ids:
            return []
        placeholders = ", ".join(f":company{i}" for i in range(len(company_ids)))
        sql += f" AND company_id IN ({placeholders})"
        parameters.update({f"company{i}": int(cid)
                           for i, cid in enumerate(company_ids)})
    sql += " ORDER BY as_of_date DESC, modifier_id ASC"
    return [dict(row) for row in session.execute(text(sql), parameters).mappings()]


def _sector_of(session, company_id: int) -> str | None:
    return session.execute(text("SELECT sector FROM companies WHERE id = :id"),
                           {"id": int(company_id)}).scalar()


def _peer_ids(session, *, sector: str, exclude_company_id: int) -> list[int]:
    rows = session.execute(text(
        "SELECT id FROM companies WHERE sector = :sector AND id <> :exclude "
        "ORDER BY id"), {"sector": sector, "exclude": int(exclude_company_id)}).all()
    return [int(row[0]) for row in rows]


def _modifier_value(parameters_json: str, param_name: str,
                    horizon_days: int) -> tuple[float, str] | str:
    """`(value, measurement)` from one modifier's JSON, or a REASON string
    saying why the row is unusable.

    The two failures are worth telling apart (fix round 1, I3): a row that
    does not mention this parameter is MISSING_ROW, while a row that DOES
    mention it but cannot say how it was measured is MISSING_MEASUREMENT --
    a data-entry defect somebody can fix, which used to be invisible.
    """
    try:
        parameters = json.loads(parameters_json or "{}")
    except (TypeError, ValueError):
        return REASON_MISSING_ROW
    if not isinstance(parameters, dict):
        return REASON_MISSING_ROW

    curve = parameters.get(f"{param_name}_curve")
    has_curve = isinstance(curve, list) and bool(curve)
    scalar = parameters.get(param_name)
    has_scalar = not isinstance(scalar, bool) and isinstance(scalar, (int, float))
    if not has_curve and not has_scalar:
        return REASON_MISSING_ROW

    measurement = parameters.get("measurement")
    if measurement not in MODIFIER_MEASUREMENTS:
        # "Missing is missing": a value we cannot band is a value we cannot
        # use. See the module docstring.
        return REASON_MISSING_MEASUREMENT

    if has_curve:
        try:
            return evaluate_curve(curve, horizon_days), str(measurement)
        except (KeyError, TypeError, ValueError, InsufficientParameterData):
            return REASON_MISSING_ROW
    return float(scalar), str(measurement)


# --- the three outcomes -----------------------------------------------------

def resolve_param(session, *, company_id: int, tag: str, param_name: str,
                  horizon_days: int, as_of: date,
                  config: MaterialityConfig | None = None,
                  modifier_state_unknown: bool = False) -> ResolvedParam:
    """Spec §5.1's missing-parameter policy, implemented literally."""
    config = config or load_materiality_config()
    if param_name not in RESOLVABLE_PARAMS:
        raise ParameterNameError(
            f"{param_name!r} is not a parameter any §5.1 channel formula "
            f"takes; the closed set is {RESOLVABLE_PARAMS}")

    # --- 1. the company's own value ----------------------------------------
    if param_name == PASS_THROUGH:
        own, reason = _own_pass_through(session, company_id=company_id, tag=tag,
                                        horizon_days=horizon_days, as_of=as_of)
    else:
        own, reason = _own_modifier(session, company_id=company_id, tag=tag,
                                    param_name=param_name,
                                    horizon_days=horizon_days, as_of=as_of)
    if own is not None:
        point, source, evidence_id, detail = own
        return ResolvedParam(
            dist=dist_for(param_name, point, source, evidence_id=evidence_id,
                          config=config,
                          modifier_state_unknown=modifier_state_unknown),
            grade_cap=grade_cap_for(source, config),
            widened=modifier_state_unknown, detail=detail)

    # --- 2. the sector median, computed here and now -----------------------
    proxy, peer_reason = _sector_median(
        session, company_id=company_id, tag=tag, param_name=param_name,
        horizon_days=horizon_days, as_of=as_of)
    reason = _worse_reason(reason, peer_reason)
    if proxy is not None:
        point, detail = proxy
        return ResolvedParam(
            dist=dist_for(param_name, point, SECTOR_PROXY, config=config,
                          modifier_state_unknown=modifier_state_unknown),
            grade_cap=grade_cap_for(SECTOR_PROXY, config),
            widened=True, detail=detail)

    # --- 3. nothing. There is no step 4. -----------------------------------
    raise InsufficientParameterData(
        f"no sourced value for {param_name!r} on tag {tag!r} for company "
        f"{company_id} at {horizon_days}d, and no sector median to stand in "
        f"for it ({reason}). The channel is UNCOMPUTABLE and publishes "
        f"nothing.", reason=reason, param=param_name)


def _own_pass_through(session, *, company_id: int, tag: str, horizon_days: int,
                      as_of: date):
    """`((value, source, evidence_id, detail) | None, reason)`."""
    reason = REASON_MISSING_ROW
    for row in _curve_rows(session, exposure_tag=tag, as_of=as_of,
                           company_id=company_id):
        source = CURVE_BASIS_TO_SOURCE.get(str(row["basis"]))
        if source is None:
            # A curve exists but its basis is outside the vocabulary, so we
            # cannot say how wide to band it. Same defect as a modifier with
            # no measurement, and repairable in the same way.
            reason = _worse_reason(reason, REASON_MISSING_MEASUREMENT)
            continue
        try:
            points = json.loads(row["points"] or "[]")
            value = evaluate_curve(points, horizon_days,
                                   ceiling=row["ceiling"])
        except (TypeError, ValueError, KeyError, InsufficientParameterData):
            continue
        return (value, source, row["evidence_id"],
                f"pass_through_curve:{row['curve_id']}@{horizon_days}d"), reason
    return None, reason


def _own_modifier(session, *, company_id: int, tag: str, param_name: str,
                  horizon_days: int, as_of: date):
    """`(value, source, evidence_id, detail)` or None. Records the most
    informative failure reason it saw in `_own_modifier.last_reason`-style
    fashion by returning it alongside -- see `_first_usable`."""
    reason = REASON_MISSING_ROW
    for row in _modifier_rows(session, applies_to_tag=tag, as_of=as_of,
                              company_id=company_id):
        resolved = _modifier_value(row["parameters"], param_name, horizon_days)
        if isinstance(resolved, str):
            reason = _worse_reason(reason, resolved)
            continue
        value, measurement = resolved
        return (value, measurement, None,
                f"company_modifier:{row['modifier_id']}"), reason
    return None, reason


def _worse_reason(current: str, candidate: str) -> str:
    """MISSING_MEASUREMENT is the more informative of the two: it means a row
    exists and can be repaired."""
    return (REASON_MISSING_MEASUREMENT
            if REASON_MISSING_MEASUREMENT in (current, candidate)
            else candidate or current)


def _sector_median(session, *, company_id: int, tag: str, param_name: str,
                   horizon_days: int, as_of: date):
    """The median over the company's SECTOR PEERS, computed from ledger rows
    at runtime, as `(value_and_detail | None, reason)`. An empty ledger has no
    median, so this returns None and the caller raises -- there is no stored
    sector table to fall back on."""
    reason = REASON_MISSING_ROW
    sector = _sector_of(session, company_id)
    if not sector:
        return None, reason

    if param_name == PASS_THROUGH:
        # A sector-level curve is itself the median somebody approved.
        for row in _curve_rows(session, exposure_tag=tag, as_of=as_of,
                               sector_id=str(sector)):
            try:
                value = evaluate_curve(json.loads(row["points"] or "[]"),
                                       horizon_days, ceiling=row["ceiling"])
            except (TypeError, ValueError, KeyError, InsufficientParameterData):
                continue
            return (value, f"pass_through_curve:{row['curve_id']}(sector)"), reason

    peers = _peer_ids(session, sector=str(sector), exclude_company_id=company_id)
    if not peers:
        return None, reason

    values: list[float] = []
    if param_name == PASS_THROUGH:
        for peer in peers:
            own, peer_reason = _own_pass_through(
                session, company_id=peer, tag=tag, horizon_days=horizon_days,
                as_of=as_of)
            reason = _worse_reason(reason, peer_reason)
            if own is not None:
                values.append(own[0])
    else:
        seen: set[int] = set()
        for row in _modifier_rows(session, applies_to_tag=tag, as_of=as_of,
                                  company_ids=peers):
            peer = int(row["company_id"])
            if peer in seen:
                continue           # one vote per company, newest row first
            resolved = _modifier_value(row["parameters"], param_name, horizon_days)
            if isinstance(resolved, str):
                reason = _worse_reason(reason, resolved)
                continue
            seen.add(peer)
            values.append(resolved[0])

    if not values:
        return None, reason
    return (median(values), f"sector_median:{sector}:n={len(values)}"), reason
