"""TASK 5.3 -- the confidence surface, and its UI contract (spec §13.3).

    "Never show a bare number. Show the band and the driver."

Two functions and one refusal:

  `calibrated_p`     -> None in every deployment. There is no active model,
                        and there cannot be one (see `registry.py`).
  `confidence_block` -> the payload a renderer consumes. With calibration
                        disabled it carries `calibrated_p: null`,
                        `degraded: true` and the REASON, plus the evidence
                        grade and the band -- which is exactly what the phase
                        file says the UI shows instead.
  `confidence_line`  -> REFUSES to render a probability without its band and
                        its dominant driver. That is this phase's fourth DO
                        NOT, enforced at the only place a number could reach a
                        reader.

The degraded line says "confidence not calibrated" IN WORDS. It does not print
a placeholder number, and it does not quietly omit the field -- a reader who
sees nothing assumes the system is confident.
"""
from typing import Any, Mapping

from app.analysis.calibration.config import CalibrationConfig, load_calibration_config

REASON_DISABLED = "CALIBRATION_DISABLED_NO_LABELED_CORPUS"
REASON_NO_MODEL = "NO_ACTIVE_CALIBRATION_MODEL"
REASON_FEATURES = "FEATURES_INCOMPLETE"


class ConfidenceRenderError(ValueError):
    """A bare probability, with no band and no dominant driver behind it."""


def calibrated_p(impact: Any, *, model: Any = None, features: Any = None,
                 config: CalibrationConfig | None = None) -> float | None:
    """`P(this directional call is judged CORRECT by expert review)`, or None.

    None is not a failure mode here; it is the shipped state. A number would
    require an ACTIVE `calibration_model` row, and the table refuses one.
    """
    config = config or load_calibration_config()
    if not config.enabled or model is None:
        return None
    if features is None:                              # pragma: no cover
        return None
    return float(model.predict(features))             # pragma: no cover


def _band(impact: Any) -> Mapping[str, Any] | None:
    block = getattr(impact, "sensitivity", None)
    if not block:
        return None
    band = block.get("delta_ebitda_pct")
    return dict(band) if band else None


def _dominant_driver(impact: Any) -> Mapping[str, Any] | None:
    block = getattr(impact, "sensitivity", None)
    drivers = (block or {}).get("driver_ranking") if block else None
    if not drivers:
        return None
    return dict(drivers[0])


def confidence_block(impact: Any, *, model: Any = None, features: Any = None,
                     in_distribution: bool | None = None,
                     config: CalibrationConfig | None = None) -> dict:
    """The payload a renderer consumes. Whole or not at all."""
    config = config or load_calibration_config()
    probability = calibrated_p(impact, model=model, features=features,
                               config=config)
    reason = None
    if probability is None:
        reason = REASON_DISABLED if not config.enabled else REASON_NO_MODEL
    return {
        "calibrated_p": probability,
        "degraded": probability is None,
        "reason": reason,
        "evidence_grade": getattr(impact, "evidence_grade", None),
        "materiality_bucket": getattr(impact, "materiality_bucket", None),
        "net_effect": getattr(impact, "net_effect", None),
        "band": _band(impact),
        "dominant_driver": _dominant_driver(impact),
        "in_distribution": in_distribution,
        "empirical_status": getattr(impact, "empirical_status", None),
    }


def _band_words(band: Mapping[str, Any] | None) -> str:
    if not band or band.get("p10") is None or band.get("p90") is None:
        return "band not computed"
    return f"range {float(band['p10']):.1f}% to {float(band['p90']):.1f}%"


def confidence_line(block: Mapping[str, Any]) -> str:
    """One line, ASCII-separated. Raises rather than print a bare number."""
    grade = block.get("evidence_grade") or "ungraded"
    probability = block.get("calibrated_p")

    if probability is None:
        # THE DEGRADED CONTRACT: grade and band, and the absence stated in
        # words. No placeholder number, and no silent omission.
        return (f"evidence {grade} | {_band_words(block.get('band'))} | "
                "confidence not calibrated (no labeled corpus)")

    band = block.get("band")
    driver = block.get("dominant_driver")
    if not band or not driver:
        raise ConfidenceRenderError(
            "a confidence number is never shown without its band and its "
            "dominant driver (§13.3). Show the degraded line instead.")
    return (f"evidence {grade} | {_band_words(band)} | "
            f"confidence {float(probability):.2f} | most sensitive to: "
            f"{driver.get('param')}")
