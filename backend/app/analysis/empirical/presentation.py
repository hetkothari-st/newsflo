"""TASK 5.2 -- the empirical context sentence. A FEATURE, NOT AN APOLOGY.

    "Our fundamental read is positive. In 34 comparable historical shocks this
     name's 5-day abnormal return was -1.4% (IQR -3.2 to +0.1). We are taking
     the other side of history here."

No 20-year analyst dismisses that sentence, because it is exactly how they
think. Which is why it is COMPILED FROM STORED NUMBERS and never written by a
model: every figure in it comes off one `transmission_empirical` row, and the
renderer REFUSES to produce the sentence when the row is not there.

There is no V5 serving path yet (the standing Phase 0 ruling), so this is the
surface a future renderer consumes, and it is tested as such.
"""
from app.analysis.empirical.check import AGREE, CONFLICT, EmpiricalAssessment, WEAK


class EmpiricalRenderError(ValueError):
    """An assessment with no sample behind it. There is no sentence to write:
    a claim about history needs the history in it."""


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _bare_pct(value: float) -> str:
    return f"{value * 100:.1f}"


def _horizon_words(horizon: str | None) -> str:
    """'5d' -> '5-day'. Unknown spellings are passed through rather than
    guessed at."""
    text_ = str(horizon or "")
    return f"{text_[:-1]}-day" if text_.endswith("d") and text_[:-1].isdigit() else text_


def empirical_line(assessment: EmpiricalAssessment, *,
                   fundamental_direction: str | None) -> str:
    """One sentence of measured history, or a refusal."""
    if assessment.status not in (AGREE, CONFLICT, WEAK):
        raise EmpiricalRenderError(
            f"status {assessment.status}: there is no measured history to "
            "describe")
    if (assessment.n_events is None or assessment.median_car is None
            or assessment.iqr_lo is None or assessment.iqr_hi is None):
        raise EmpiricalRenderError(
            "a historical claim is rendered with its sample and its band or "
            "not at all")

    read = (f"Our fundamental read is {str(fundamental_direction).lower()}."
            if fundamental_direction else "")
    body = (f"In {assessment.n_events} comparable historical shocks this "
            f"name's {_horizon_words(assessment.horizon)} abnormal return was "
            f"{_pct(assessment.median_car)} "
            f"(IQR {_bare_pct(assessment.iqr_lo)} to "
            f"{_bare_pct(assessment.iqr_hi)}).")
    tail = {
        CONFLICT: "We are taking the other side of history here.",
        AGREE: "History agrees.",
        WEAK: "History is not significant either way.",
    }[assessment.status]
    if assessment.regime_changed:
        tail = (f"{tail} A reviewer has recorded a regime change for this "
                f"shock class, expiring {assessment.regime_change_expires_on}.")
    return " ".join(part for part in (read, body, tail) if part)
