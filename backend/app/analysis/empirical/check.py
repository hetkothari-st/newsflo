"""TASK 5.2 -- the empirical cross-check, and how a conflict is handled.

    def empirical_check(impact, row) -> "AGREE" | "CONFLICT" | "WEAK" | "NO_DATA"

FOUR OUTCOMES, NO FIFTH. The function below is the phase file's pseudocode
implemented literally; everything else in this module is what the four
outcomes DO.

**CONFLICT IS NOT AUTO-REJECT** (spec §10.3, and this phase's first DO NOT).
Empirical history can be dominated by a regime that no longer applies -- the
pre-windfall-tax upstream names are the canonical example -- and the market
may simply have been wrong, which is the alpha this product claims to find. So
a conflict:

    caps the tier at SECONDARY_RIPPLE   (config/gates.yaml: the PRIMARY walk
                                         does not admit CONFLICT)
    attaches a MAJOR objection          (EMPIRICAL_CONFLICT, sustained)
    routes to divergence_review         (divergence.queue_empirical_conflict)

and never, ever rejects. A human reviewer who decides the old behaviour no
longer applies writes a REGIME_CHANGED annotation with a REASON and an EXPIRY
(`regime.py`), and PRIMARY becomes available again for that (company, shock
class) until it lapses.

WHAT THIS MODULE MAY NOT DO. It may not change direction, materiality, the
band or the evidence grade. A cross-check that could rewrite the thing it is
checking is not a check. `tests/phase5/test_empirical_check.py` pins the
fundamental block byte-identical across AGREE and CONFLICT.

PURE. No I/O, no clock, no LLM. The stored row is fetched by the caller
(`event_study.transmission_row_for`); the annotation is fetched by the caller
(`regime.active_regime_change`); this module only judges.
"""
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, Mapping, Sequence

from app.analysis.empirical.config import EmpiricalPolicy, load_empirical_config

AGREE = "AGREE"
CONFLICT = "CONFLICT"
WEAK = "WEAK"
NO_DATA = "NO_DATA"

OBJECTION_TYPE = "EMPIRICAL_CONFLICT"
OBJECTION_SEVERITY = "MAJOR"

# The only two record-level directions a historical CAR can be compared with.
# MIXED, UNCERTAIN and NO_MATERIAL_IMPACT make no directional claim, so there
# is nothing for history to falsify -- calling that a CONFLICT would
# manufacture a disagreement with a claim nobody made.
DIRECTIONAL = ("POSITIVE", "NEGATIVE")


def headline_direction(impact: Any) -> str | None:
    """The direction the record leads with, whatever shape the caller's
    object is. `None` means "this record claims no direction"."""
    for attribute in ("headline_direction", "net_effect"):
        value = getattr(impact, attribute, None)
        if value is not None:
            return str(value) if str(value) in DIRECTIONAL else None
    return None


def _sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def empirical_check(impact: Any, row: Any, *,
                    policy: EmpiricalPolicy | None = None
                    ) -> Literal["AGREE", "CONFLICT", "WEAK", "NO_DATA"]:
    """Spec §10.2, verbatim, with the thresholds read from config.

    `NO_DATA` is the honest answer in three different situations and they are
    all genuinely "history says nothing about this": no row, too few events,
    and a record that claims no direction. A median of exactly zero has no
    sign, so it cannot agree with anything either.
    """
    policy = policy or load_empirical_config()
    if row is None or int(row.n_events) < policy.min_events:
        return NO_DATA
    if float(row.p_value) > policy.max_p_value:
        return WEAK
    direction = headline_direction(impact)
    if direction is None:
        return NO_DATA
    empirical_sign = _sign(float(row.median_car))
    if empirical_sign == 0:
        return NO_DATA
    claimed_sign = 1 if direction == "POSITIVE" else -1
    return AGREE if empirical_sign == claimed_sign else CONFLICT


@dataclass(frozen=True)
class EmpiricalAssessment:
    """The four-outcome verdict plus everything a reader needs to argue with
    it: the sample, the median, the band, the significance and the estimator
    that produced them. A status with no sample behind it is exactly the
    unfalsifiable claim this phase exists to remove."""
    status: str
    shock_variable: str | None = None
    shock_sign: str | None = None
    horizon: str | None = None
    n_events: int | None = None
    median_car: float | None = None
    iqr_lo: float | None = None
    iqr_hi: float | None = None
    p_value: float | None = None
    sign_consistency: float | None = None
    estimator_version: str | None = None
    regime_changed: bool = False
    regime_change_expires_on: date | None = None
    needs_divergence_review: bool = False

    @property
    def objection(self) -> Mapping[str, Any] | None:
        """The MAJOR objection a conflict attaches -- unless a reviewer has
        already adjudicated it as a regime change, in which case the objection
        would be re-litigating a decision somebody made and recorded."""
        if self.status != CONFLICT or self.regime_changed:
            return None
        return {
            "objection_id": f"empirical:{self.shock_variable}:{self.shock_sign}"
                            f":{self.horizon}",
            "type": OBJECTION_TYPE,
            "severity": OBJECTION_SEVERITY,
            "sustained": True,
        }


def assess(impact: Any, row: Any, *, as_of: date, shock_variable: str | None = None,
           shock_sign: str | None = None, horizon: str | None = None,
           regime_change: Any = None,
           policy: EmpiricalPolicy | None = None) -> EmpiricalAssessment:
    """`empirical_check` plus the consequences, as one immutable record."""
    policy = policy or load_empirical_config()
    status = empirical_check(impact, row, policy=policy)
    active = bool(regime_change is not None
                  and status == CONFLICT
                  and regime_change.is_active(as_of))
    return EmpiricalAssessment(
        status=status,
        shock_variable=(shock_variable if shock_variable is not None
                        else getattr(row, "shock_variable", None)),
        shock_sign=(shock_sign if shock_sign is not None
                    else getattr(row, "shock_sign", None)),
        horizon=(horizon if horizon is not None
                 else getattr(row, "horizon", None)),
        n_events=(None if row is None else int(row.n_events)),
        median_car=(None if row is None else float(row.median_car)),
        iqr_lo=(None if row is None else _optional_float(row, "iqr_lo")),
        iqr_hi=(None if row is None else _optional_float(row, "iqr_hi")),
        p_value=(None if row is None else float(row.p_value)),
        sign_consistency=(None if row is None
                          else _optional_float(row, "sign_consistency")),
        estimator_version=(None if row is None
                           else getattr(row, "estimator_version", None)),
        regime_changed=active,
        regime_change_expires_on=(regime_change.expires_on if active else None),
        # A conflict a reviewer has already adjudicated is not a new question.
        needs_divergence_review=(status == CONFLICT and not active))


def _optional_float(row: Any, name: str) -> float | None:
    value = getattr(row, name, None)
    return None if value is None else float(value)


def signals_from_assessment(assessment: EmpiricalAssessment, *, event_id: str,
                            company_id: int | None, analysis_version: str,
                            created_at: datetime, stage: str = "EMPIRICAL",
                            created_by: str = "empirical:event_study"
                            ) -> tuple:
    """The EMPIRICAL_CHECK signal, and the OBJECTION when there is one.

    The status travels with its SAMPLE. A payload carrying only "CONFLICT"
    would leave the record unable to explain itself, and §10.3's whole point is
    that the disagreement is a feature you show the user.
    """
    from app.core.signals import make_signal

    payload: dict[str, Any] = {
        "status": assessment.status,
        "n_events": assessment.n_events,
        "shock_variable": assessment.shock_variable,
        "shock_sign": assessment.shock_sign,
        "horizon": assessment.horizon,
        "median_car": assessment.median_car,
        "p_value": assessment.p_value,
        "sign_consistency": assessment.sign_consistency,
        "estimator_version": assessment.estimator_version,
        "regime_changed": assessment.regime_changed,
        "regime_change_expires_on": (
            assessment.regime_change_expires_on.isoformat()
            if assessment.regime_change_expires_on else None),
    }
    signals = [make_signal(
        event_id=event_id, company_id=company_id, stage=stage,
        kind="EMPIRICAL_CHECK", payload=payload, created_by=created_by,
        analysis_version=analysis_version, created_at=created_at)]

    objection = assessment.objection
    if objection is not None:
        signals.append(make_signal(
            event_id=event_id, company_id=company_id, stage=stage,
            kind="OBJECTION", payload=dict(objection), created_by=created_by,
            analysis_version=analysis_version, created_at=created_at))
    return tuple(signals)


def assessments_for(session, impact: Any, *, shock_variable: str,
                    shock_sign: str, as_of: date,
                    horizons: Sequence[str] | None = None,
                    policy: EmpiricalPolicy | None = None
                    ) -> tuple[EmpiricalAssessment, ...]:
    """The DB-backed convenience path: read the stored row(s) and the active
    annotation, then assess. In the deployed state every result is NO_DATA,
    because `transmission_empirical` is empty."""
    from app.analysis.empirical.event_study import transmission_row_for
    from app.analysis.empirical.regime import active_regime_change, shock_class

    policy = policy or load_empirical_config()
    company_id = getattr(impact, "company_id", None)
    annotation = None if company_id is None else active_regime_change(
        session, company_id=int(company_id),
        shock_class=shock_class(shock_variable, shock_sign), as_of=as_of)
    return tuple(
        assess(impact,
               (None if company_id is None else transmission_row_for(
                   session, company_id=int(company_id),
                   shock_variable=shock_variable, shock_sign=shock_sign,
                   horizon=horizon)),
               as_of=as_of, shock_variable=shock_variable,
               shock_sign=shock_sign, horizon=horizon,
               regime_change=annotation, policy=policy)
        for horizon in (horizons or tuple(policy.car_horizons)))
