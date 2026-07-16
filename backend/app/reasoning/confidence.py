"""Deterministic Confidence Engine. Computes confidence_score from evidence,
calibration history, and reasoning-quality signals instead of asking the LLM
to self-rate its own confidence -- see
docs/superpowers/specs/2026-07-15-reasoning-engine-upgrade-design.md.

compute_confidence is a pure function: every input is a plain value the
caller has already looked up (from CalibrationSample stats, the resolved
company entry, and the source article), so this module has no DB or network
dependency and is fully unit-testable with fixed inputs.
"""

from dataclasses import dataclass, field

# Weights sum to 1.0. Kept as separate named constants (not one dict literal)
# so a future calibration-health review can retune a single weight without
# hunting through compute_confidence's body.
WEIGHT_HISTORICAL_CALIBRATION = 0.30
WEIGHT_EVIDENCE_COMPLETENESS = 0.20
WEIGHT_RULEBOOK_MATCH = 0.20
WEIGHT_SOURCE_CREDIBILITY = 0.10
WEIGHT_REASONING_CONSISTENCY = 0.10
WEIGHT_DATA_FRESHNESS = 0.10

# Mirrors app.calibration.blender.CALIBRATION_SAMPLE_THRESHOLD -- duplicated
# rather than imported to keep this module dependency-free (no DB imports);
# both must be changed together if ever retuned.
CALIBRATION_SAMPLE_THRESHOLD = 5

# Static per-source scores for known RSS feeds (see
# app/ingestion/sources.py::RSS_FEEDS). Deliberately small and roughly equal
# for now -- real differentiation should come from calibration-health data
# once enough volume exists per source, not from an editorial guess.
SOURCE_CREDIBILITY: dict[str, float] = {
    "economic_times": 0.85,
    "moneycontrol": 0.8,
    "business_standard": 0.8,
}
DEFAULT_SOURCE_CREDIBILITY = 0.7


def source_credibility(source: str) -> float:
    return SOURCE_CREDIBILITY.get(source, DEFAULT_SOURCE_CREDIBILITY)


@dataclass
class ConfidenceResult:
    score: int  # 0-100
    band: str  # LOW | MODERATE | HIGH | VERY_HIGH
    contributors: list[str] = field(default_factory=list)
    penalties: list[str] = field(default_factory=list)


def _band(score: int) -> str:
    if score < 40:
        return "LOW"
    if score < 70:
        return "MODERATE"
    if score < 90:
        return "HIGH"
    return "VERY_HIGH"


def compute_confidence(
    *,
    calibration_sample_count: int,
    calibration_hit_rate: float | None,
    claim_count: int,
    evidence_ref_count: int,
    rule_matched: bool,
    source_credibility: float,
    reasoning_consistent: bool,
    article_age_hours: float,
) -> ConfidenceResult:
    contributors: list[str] = []
    penalties: list[str] = []

    # Historical calibration: 0 until enough real-outcome samples exist (same
    # threshold app.calibration.blender uses for magnitude blending), then
    # hit_rate itself IS the 0-1 component score.
    if calibration_sample_count < CALIBRATION_SAMPLE_THRESHOLD or calibration_hit_rate is None:
        historical_component = 0.0
        penalties.append(
            f"No historical calibration yet ({calibration_sample_count} samples, "
            f"need {CALIBRATION_SAMPLE_THRESHOLD})"
        )
    else:
        historical_component = calibration_hit_rate
        contributors.append(
            f"Historical calibration: {calibration_hit_rate:.0%} hit rate over "
            f"{calibration_sample_count} samples"
        )

    # Evidence completeness: fraction of claims that cite at least one piece
    # of evidence. claim_count == 0 is treated as fully covered (nothing to
    # cite), not a penalty for an empty claim list.
    if claim_count == 0:
        evidence_component = 1.0
    else:
        evidence_component = min(1.0, evidence_ref_count / claim_count)
    if evidence_component >= 0.8:
        contributors.append(f"Evidence cited for {evidence_ref_count}/{max(claim_count, 1)} claims")
    else:
        penalties.append(f"Only {evidence_ref_count}/{max(claim_count, 1)} claims cite evidence")

    rule_component = 1.0 if rule_matched else 0.0
    if rule_matched:
        contributors.append("Matched a known rulebook rule")
    else:
        penalties.append("No rulebook rule matched -- generic reasoning only")

    source_component = max(0.0, min(1.0, source_credibility))

    consistency_component = 1.0 if reasoning_consistent else 0.0
    if not reasoning_consistent:
        penalties.append("Reasoning flagged as internally inconsistent")

    # Freshness: linear decay to 0 over 7 days (168h) -- older than that
    # contributes nothing, since news relevance genuinely fades.
    freshness_component = max(0.0, min(1.0, 1 - (article_age_hours / 168)))
    if freshness_component < 0.5:
        penalties.append("Article is more than 3.5 days old")

    raw = (
        historical_component * WEIGHT_HISTORICAL_CALIBRATION
        + evidence_component * WEIGHT_EVIDENCE_COMPLETENESS
        + rule_component * WEIGHT_RULEBOOK_MATCH
        + source_component * WEIGHT_SOURCE_CREDIBILITY
        + consistency_component * WEIGHT_REASONING_CONSISTENCY
        + freshness_component * WEIGHT_DATA_FRESHNESS
    )
    score = max(0, min(100, round(raw * 100)))

    return ConfidenceResult(score=score, band=_band(score), contributors=contributors, penalties=penalties)
