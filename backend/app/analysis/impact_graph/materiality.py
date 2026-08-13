"""Materiality composite (spec §15, corrective-v4 Task 8): the grade the
publication gate actually evaluates is never the naked LLM float. The
model's [0,1] materiality is a real signal but an uncalibrated one -- a
0.9 from a model with no prior on the company's exposure to this exact
economic dimension is not the same claim as a 0.9 backed by a verified
HIGH exposure record. This module is the single deterministic place that
turns (float, prior, evidence, event knowledge) into one of four grades,
by capping downward only -- it never invents a number, and it never grades
UP past what the float alone earned.
"""

# Base-grade thresholds -- same cut points app.analysis.impact_graph.
# publication_gate.materiality_grade() has always used (spec §15); kept
# here as the single source now that this module owns the composite.
_HIGH = 0.6
_MEDIUM = 0.35

_GRADES = ("UNKNOWN", "LOW", "MEDIUM", "HIGH")
_RANK = {grade: rank for rank, grade in enumerate(_GRADES)}

# Exposure levels that cap the grade at MEDIUM: NONE (no exposure at all)
# and LOW (weak exposure) both mean the mechanism cannot plausibly be a
# HIGH-materiality story for this company, whatever the model's float says.
_LOW_EXPOSURE_LEVELS = frozenset({"NONE", "LOW"})


def _cap(grade: str, ceiling: str) -> str:
    """Never raises a grade -- only pulls it down to `ceiling` when it is
    currently graded higher."""
    return ceiling if _RANK[grade] > _RANK[ceiling] else grade


def materiality_grade(
    llm_materiality: float | None,
    exposure_level: str | None,     # ordinal from CompanyExposure for the mechanism's dimension
    evidence_tier: str,
    shock_magnitude_known: bool,    # reserved -- Task 10 wires event magnitude
) -> str:
    """HIGH/MEDIUM/LOW/UNKNOWN. Deterministic caps, no invented numbers:

    - `llm_materiality` is None -> UNKNOWN (an unmeasured value is not a
      small one).
    - Otherwise the base grade comes from the float alone: >=0.6 HIGH,
      >=0.35 MEDIUM, else LOW.
    - `exposure_level` in (NONE, LOW) caps the grade at MEDIUM -- weak or
      absent prior exposure means the model's own confidence can't carry a
      HIGH claim on its own.
    - `evidence_tier` == "E" (model inference, never authorizing per
      INV-003) caps the grade at LOW.
    - `exposure_level` is None (no prior on file at all, as opposed to a
      verified NONE) applies NO cap -- absence of a record is not evidence
      of absence of exposure.

    `shock_magnitude_known` is accepted but not yet used: no producer of a
    real event-magnitude verdict exists until Task 10 wires one, and
    inventing a cap from a value nobody computed would be the exact
    naked-float problem this function exists to prevent.
    """
    if llm_materiality is None:
        return "UNKNOWN"

    if llm_materiality >= _HIGH:
        grade = "HIGH"
    elif llm_materiality >= _MEDIUM:
        grade = "MEDIUM"
    else:
        grade = "LOW"

    if exposure_level in _LOW_EXPOSURE_LEVELS:
        grade = _cap(grade, "MEDIUM")

    if evidence_tier == "E":
        grade = _cap(grade, "LOW")

    return grade
