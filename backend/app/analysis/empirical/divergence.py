"""TASKS 5.2 / 5.5 -- the divergence review queue.

TWO KINDS OF DISAGREEMENT LAND HERE AND NEITHER IS EVER RESOLVED SILENTLY:

  EMPIRICAL_CONFLICT   history disagrees with the fundamental read (§10.3).
                       The tier is capped at SECONDARY_RIPPLE by the gate and
                       a human is asked. NOT a rejection.
  MARKET_DIVERGENCE    the price move disagrees with the fundamental read
                       (§5.5). This one changes NOTHING: "divergence is a
                       monitoring signal, never a correction".

WHY THAT ASYMMETRY IS RIGHT. An empirical conflict is evidence about a
mechanism measured over years; a market divergence is one day of price action,
which is exactly the input master-context invariant 3 forbids from touching a
fundamental verdict. So the empirical one may cap a tier and the market one
may not do anything at all except be visible.

THIS MODULE NEVER TOUCHES `company_impact`. Pinned by an ast scan in
`tests/phase5/test_market_isolation.py`, and by a byte-identity test on the
canonical record either side of a queue write. It also imports NOTHING from
`app/market/*`: the excess move arrives as a number the caller passes in.
"""
from datetime import date, datetime, timezone
from typing import Any

import hashlib

from sqlalchemy import text

from app.analysis.empirical.check import EmpiricalAssessment
from app.analysis.empirical.config import load_empirical_config

KIND_EMPIRICAL_CONFLICT = "EMPIRICAL_CONFLICT"
KIND_MARKET_DIVERGENCE = "MARKET_DIVERGENCE"

STATUS_OPEN = "OPEN"
STATUS_RESOLVED = "RESOLVED"

RESOLUTION_REGIME_CHANGED = "REGIME_CHANGED"
RESOLUTIONS = (RESOLUTION_REGIME_CHANGED, "UPHELD", "MODEL_WRONG", "NOISE")

# What `divergence_status` can say. NOT_APPLICABLE and NO_DATA are separate on
# purpose: "this record claims no direction" and "we have no measured move"
# are different facts and only one of them is somebody's missing feed.
AGREE = "AGREE"
DIVERGENT = "DIVERGENT"
WITHIN_THRESHOLD = "WITHIN_THRESHOLD"
NOT_APPLICABLE = "NOT_APPLICABLE"
NO_DATA = "NO_DATA"

DIRECTIONAL = ("POSITIVE", "NEGATIVE")


def _review_id(kind: str, *parts: Any) -> str:
    """CONTENT-ADDRESSED. Re-running the same analysis re-queues the SAME
    review instead of growing the queue by one row per run."""
    digest = hashlib.sha256(
        "|".join([kind, *(str(p) for p in parts)]).encode("utf-8")).hexdigest()
    return f"{kind.lower()}:{digest[:24]}"


def _insert(session, *, review_id: str, kind: str, company_id: int,
            created_at: datetime, **columns: Any) -> str:
    fields = {
        "review_id": review_id, "kind": kind, "company_id": company_id,
        "event_id": None, "shock_variable": None, "shock_sign": None,
        "horizon": None, "fundamental_direction": None, "empirical_status": None,
        "n_events": None, "median_car": None, "p_value": None,
        "excess_move_pct": None, "threshold_pct": None,
        "created_at": created_at.isoformat(),
    }
    fields.update({k: v for k, v in columns.items() if k in fields})
    session.execute(text(
        "INSERT INTO divergence_review (review_id, kind, event_id, company_id, "
        "shock_variable, shock_sign, horizon, fundamental_direction, "
        "empirical_status, n_events, median_car, p_value, excess_move_pct, "
        "threshold_pct, status, created_at) VALUES (:review_id, :kind, "
        ":event_id, :company_id, :shock_variable, :shock_sign, :horizon, "
        ":fundamental_direction, :empirical_status, :n_events, :median_car, "
        ":p_value, :excess_move_pct, :threshold_pct, 'OPEN', :created_at) "
        "ON CONFLICT (review_id) DO NOTHING"), fields)
    return review_id


def queue_empirical_conflict(session, *, event_id: str | None, company_id: int,
                             assessment: EmpiricalAssessment,
                             fundamental_direction: str | None,
                             created_at: datetime) -> str:
    """Route a conflict to a human. The tier cap is the GATE's doing; this is
    the other half of §10.3 -- somebody has to look at it."""
    review_id = _review_id(
        KIND_EMPIRICAL_CONFLICT, company_id, assessment.shock_variable,
        assessment.shock_sign, assessment.horizon, event_id)
    return _insert(
        session, review_id=review_id, kind=KIND_EMPIRICAL_CONFLICT,
        company_id=company_id, created_at=created_at, event_id=event_id,
        shock_variable=assessment.shock_variable,
        shock_sign=assessment.shock_sign, horizon=assessment.horizon,
        fundamental_direction=fundamental_direction,
        empirical_status=assessment.status, n_events=assessment.n_events,
        median_car=assessment.median_car, p_value=assessment.p_value)


def divergence_status(fundamental_direction: str | None,
                      excess_move_pct: float | None, *,
                      threshold_pct: float | None = None) -> str:
    """PURE. Two numbers in, one word out; no market module is imported and no
    verdict is touched."""
    if threshold_pct is None:
        threshold_pct = load_empirical_config().divergence_threshold_pct
    if str(fundamental_direction) not in DIRECTIONAL:
        return NOT_APPLICABLE
    if excess_move_pct is None:
        return NO_DATA
    if abs(float(excess_move_pct)) < float(threshold_pct):
        return WITHIN_THRESHOLD
    moved_up = float(excess_move_pct) > 0
    claimed_up = str(fundamental_direction) == "POSITIVE"
    return AGREE if moved_up == claimed_up else DIVERGENT


def queue_market_divergence(session, *, event_id: str | None, company_id: int,
                            fundamental_direction: str | None,
                            excess_move_pct: float | None,
                            threshold_pct: float | None = None,
                            created_at: datetime | None = None) -> str | None:
    """Write the disagreement down and stop. Returns None when there is
    nothing to report -- an agreeing move is not news."""
    status = divergence_status(fundamental_direction, excess_move_pct,
                               threshold_pct=threshold_pct)
    if status != DIVERGENT:
        return None
    review_id = _review_id(KIND_MARKET_DIVERGENCE, company_id, event_id)
    return _insert(
        session, review_id=review_id, kind=KIND_MARKET_DIVERGENCE,
        company_id=company_id,
        created_at=created_at or datetime.now(timezone.utc), event_id=event_id,
        fundamental_direction=fundamental_direction,
        excess_move_pct=excess_move_pct,
        threshold_pct=(threshold_pct
                       if threshold_pct is not None
                       else load_empirical_config().divergence_threshold_pct))


def open_reviews(session, *, kind: str | None = None) -> tuple[dict, ...]:
    """The queue, oldest first. The review console reads this."""
    clause = "" if kind is None else " AND kind = :kind"
    rows = session.execute(text(
        "SELECT review_id, kind, event_id, company_id, shock_variable, "
        "shock_sign, horizon, fundamental_direction, empirical_status, "
        "n_events, median_car, p_value, excess_move_pct, created_at "
        f"FROM divergence_review WHERE status = 'OPEN'{clause} "
        "ORDER BY created_at ASC, review_id ASC"),
        {} if kind is None else {"kind": kind}).mappings().all()
    return tuple(dict(row) for row in rows)


def resolve(session, review_id: str, *, resolution: str, reason: str,
            reviewed_by: str, resolved_at: datetime,
            expires_on: date | None = None,
            effective_from: date | None = None) -> None:
    """Close a review. `REGIME_CHANGED` additionally writes the annotation
    that restores PRIMARY eligibility -- with an expiry, always."""
    from app.analysis.empirical.regime import record_regime_change, shock_class

    if resolution not in RESOLUTIONS:
        raise ValueError(
            f"unknown resolution {resolution!r}; the controlled set is "
            f"{RESOLUTIONS}")
    row: Any = session.execute(text(
        "SELECT company_id, shock_variable, shock_sign FROM divergence_review "
        "WHERE review_id = :review_id"), {"review_id": review_id}).mappings().first()
    if row is None:
        raise ValueError(f"no divergence_review row {review_id!r}")

    if resolution == RESOLUTION_REGIME_CHANGED:
        record_regime_change(
            session, company_id=int(row["company_id"]),
            shock_class=shock_class(str(row["shock_variable"]),
                                    str(row["shock_sign"])),
            reason=reason, reviewed_by=reviewed_by,
            effective_from=effective_from or resolved_at.date(),
            expires_on=expires_on, review_id=review_id,
            created_at=resolved_at)

    session.execute(text(
        "UPDATE divergence_review SET status = 'RESOLVED', resolution = "
        ":resolution, reason = :reason, reviewed_by = :reviewed_by, "
        "resolved_at = :resolved_at WHERE review_id = :review_id"), {
            "resolution": resolution, "reason": reason,
            "reviewed_by": reviewed_by, "resolved_at": resolved_at.isoformat(),
            "review_id": review_id})
