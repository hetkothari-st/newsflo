"""Deterministic Confidence Engine. Computes confidence_score from evidence
completeness, rulebook match, source credibility, and article freshness
instead of asking the LLM to self-rate its own confidence -- see
docs/superpowers/specs/2026-07-15-reasoning-engine-upgrade-design.md.

Deliberately excludes anything derived from realized market movement data
(historical outcome hit-rate, reasoning-vs-movement contradiction) -- see
docs/superpowers/sdd/2026-08-13-newsflo-corrective-v4/task-3-brief.md. A
fundamental judgment about a company must not be scored, up or down, by
what its shares did afterward; that coupling let a real market panic quietly
delete an alert's own confidence in the ORIGINAL reasoning that (correctly
or not) motivated the panic. Market observation now lives entirely outside
this engine -- app.reasoning.financial_context still computes and persists
it on the row, but nothing here reads it.

compute_confidence is a pure function: every input is a plain value the
caller has already looked up (from the resolved company entry and the
source article), so this module has no DB or network dependency and is
fully unit-testable with fixed inputs.
"""

from dataclasses import dataclass, field

# Weights sum to 1.0. Kept as separate named constants (not one dict literal)
# so a future review can retune a single weight without hunting through
# compute_confidence's body. Renormalized (proportionally, from the original
# 0.20/0.20/0.10/0.10) after WEIGHT_HISTORICAL_CALIBRATION (0.30) and
# WEIGHT_REASONING_CONSISTENCY (0.10) were removed -- both were derived from
# realized market movement, not fundamental evidence quality.
WEIGHT_EVIDENCE_COMPLETENESS = 1 / 3
WEIGHT_RULEBOOK_MATCH = 1 / 3
WEIGHT_SOURCE_CREDIBILITY = 1 / 6
WEIGHT_DATA_FRESHNESS = 1 / 6

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


def _weighted(components: list[tuple[float, float]]) -> float:
    """Weighted mean of (component, weight) pairs, renormalised by the
    weights actually passed in. Passing a SUBSET therefore redistributes the
    omitted weights proportionally across the rest, which is how an
    inapplicable signal is excluded without silently scoring it as zero."""
    total_weight = sum(weight for _, weight in components)
    if total_weight <= 0:
        return 0.0
    return sum(value * weight for value, weight in components) / total_weight


def compute_confidence(
    *,
    claim_count: int,
    evidence_ref_count: int,
    rule_matched: bool,
    source_credibility: float,
    article_age_hours: float,
) -> ConfidenceResult:
    contributors: list[str] = []
    penalties: list[str] = []

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

    # Freshness: linear decay to 0 over 7 days (168h) -- older than that
    # contributes nothing, since news relevance genuinely fades.
    freshness_component = max(0.0, min(1.0, 1 - (article_age_hours / 168)))
    if freshness_component < 0.5:
        penalties.append("Article is more than 3.5 days old")

    # Two scorings of the same evidence, and the BETTER one wins.
    #
    # `evidence_refs` is no longer a required tool-schema field (see
    # app.analysis.cascade._COMPANY_ITEM_REQUIRED -- it was dropped to fit
    # the company prompt under openai/gpt-oss-20b's token ceiling, which is
    # what makes company identification work at all). Scored the old way,
    # a company that supplies none would take a hard 0.0 on BOTH the
    # evidence and rulebook components and land at ~28 -- under
    # app.pipeline.CONFIDENCE_FLOOR (40), which silently deletes it. Every
    # company of every alert would be deleted: the exact zero-companies
    # outage the prompt work exists to fix, re-entered through the scorer.
    #
    # So both components are treated as INAPPLICABLE, not failed, when the
    # model supplied no evidence refs: their weight is renormalised across
    # the components that ARE applicable. The rulebook component belongs in
    # that pair because a rule match is derived exclusively FROM
    # evidence_refs (app.pipeline._build_alert_company) -- with no refs a
    # match is structurally impossible, not merely absent.
    #
    # Taking the max of the two scorings, rather than switching on
    # evidence_ref_count == 0, is what keeps the incentive honest: it makes
    # supplying SOME evidence never score worse than supplying none.
    # Switching would have made a company with 1 ref for 3 claims (35) score
    # below one with 0 refs (48) -- rewarding the model for omitting an
    # optional field, and dropping the more forthcoming answer. Nothing is
    # ever scored lower than before this change; a full set of refs still
    # scores exactly as it always did.
    applicable = [
        (source_component, WEIGHT_SOURCE_CREDIBILITY),
        (freshness_component, WEIGHT_DATA_FRESHNESS),
    ]
    evidence_scored = applicable + [
        (evidence_component, WEIGHT_EVIDENCE_COMPLETENESS),
        (rule_component, WEIGHT_RULEBOOK_MATCH),
    ]
    raw = max(_weighted(evidence_scored), _weighted(applicable))
    score = max(0, min(100, round(raw * 100)))

    return ConfidenceResult(score=score, band=_band(score), contributors=contributors, penalties=penalties)
