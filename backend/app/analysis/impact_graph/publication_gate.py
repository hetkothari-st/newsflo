"""Company publication gate (spec 2026-08-12 §5): the single deterministic
authority for what reaches the user-facing feed.

Discovery (sector pools, archetypes, ripple branches, completeness audits,
article subjects) proposes candidates; nothing it produces is publishable
by itself. Every candidate walks the same gate sequence and either becomes
DISPLAY_ELIGIBLE with a tier (primary/secondary) or terminates in a
machine-readable REJECT_* state. Publication fails closed: a gate that
cannot be evaluated rejects, it never waves through.

Authority order (spec §64): deterministic policy here outranks any LLM
output -- the model may propose and challenge, never overrule a rejection.
"""
from dataclasses import dataclass, field

# Gate sequence (spec §5). Order matters: gates_passed records progress in
# this order until the first failure, which is the audit trail's spine.
GATE_SEQUENCE = [
    "ENTITY_VALID",
    "BUSINESS_MODEL_VALID",
    "MECHANISM_VALID",
    "COMPANY_SPECIFIC_EXPOSURE_VALID",
    "EVENT_APPLICABILITY_VALID",
    "CAUSAL_PATH_VALID",
    "MATERIALITY_VALID",
    "EVIDENCE_VALID",
    "CONTRADICTION_FREE",
    "VERIFIED",
]

REJECTION_STATES = frozenset({
    "REJECT_ENTITY_AMBIGUOUS",
    "REJECT_UNKNOWN_COMPANY",
    "REJECT_GENERIC_EXPOSURE",
    "REJECT_WEAK_MECHANISM",
    "REJECT_NOT_EVENT_SPECIFIC",
    "REJECT_TOO_DISTANT",
    "REJECT_LOW_MATERIALITY",
    "REJECT_NO_MATERIAL_IMPACT",
    "REJECT_INSUFFICIENT_EVIDENCE",
    "REJECT_CONTRADICTORY",
    "REJECT_UNVERIFIED",
    "REJECT_DUPLICATE",
    "REJECT_LOW_PRIORITY",
    "REJECT_VALIDATOR_UNAVAILABLE",
})

# Evidence classes (spec §9/§10). Ranked by what they may authorize:
# - ARTICLE_SUBJECT / VERIFIED_RELATIONSHIP: primary-capable on their own.
# - CURATED_ARCHETYPE (Tier D): primary only alongside HIGH materiality --
#   archetype membership alone is a hint, never proof (INV-004).
# - MODEL_INFERENCE (Tier E): secondary at best.
# - ARTICLE_MARKET_OBSERVATION: "the stock fell" is a market fact, not
#   fundamental evidence (INV-003); treated like model inference.
PRIMARY_CAPABLE_EVIDENCE = frozenset({"ARTICLE_SUBJECT", "VERIFIED_RELATIONSHIP"})
ARCHETYPE_EVIDENCE = "CURATED_ARCHETYPE"
NEVER_PRIMARY_EVIDENCE = frozenset({"MODEL_INFERENCE", "ARTICLE_MARKET_OBSERVATION"})

# Generic-exposure phrases (spec §28): reasoning interchangeable with a
# sector statement cannot carry a company-specific claim.
_GENERIC_PHRASES = (
    "same sector", "sector exposure", "large company", "major player",
    "market sentiment", "broader theme", "all companies in",
    "sector as a whole", "industry peer",
)

# Materiality grades (spec §15): controlled qualitative grades over the
# engine's [0,1] float; no fake precision.
_MATERIALITY_HIGH = 0.6
_MATERIALITY_MEDIUM = 0.35

_MIN_MECHANISM_CHARS = 20


@dataclass
class CandidateInput:
    """Everything the gate needs, resolved by the caller -- the gate itself
    never touches the DB or an LLM, which is what keeps it testable and
    incorruptible."""
    ticker: str
    entity_resolved: bool
    mechanism: str
    rationale: str
    economic_effect: str          # positive | negative | mixed | uncertain | no_material_impact
    causal_distance: int
    materiality: float | None
    confidence: float | None
    independently_verified: bool
    verification_available: bool  # False when verification could not run at all
    evidence_class: str
    positive_channels: list = field(default_factory=list)
    negative_channels: list = field(default_factory=list)
    net_direction: str = ""
    trigger_shock_present: bool = True


@dataclass
class GateDecision:
    final_state: str              # DISPLAY_ELIGIBLE or a REJECT_* state
    display_tier: str             # primary | secondary | excluded
    gates_passed: list
    rejection_reason: str | None
    materiality_grade: str        # HIGH | MEDIUM | LOW | UNKNOWN


def materiality_grade(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    if value >= _MATERIALITY_HIGH:
        return "HIGH"
    if value >= _MATERIALITY_MEDIUM:
        return "MEDIUM"
    return "LOW"


def _is_generic_rationale(rationale: str) -> bool:
    lowered = (rationale or "").lower()
    return any(phrase in lowered for phrase in _GENERIC_PHRASES)


def _net_as_direction(net_direction: str) -> str:
    return net_direction if net_direction in ("bullish", "bearish") else "neutral"


_EFFECT_AS_DIRECTION = {
    "positive": "bullish", "negative": "bearish",
    "mixed": "neutral", "uncertain": "neutral", "no_material_impact": "neutral",
}


def evaluate_candidate(candidate: CandidateInput) -> GateDecision:
    """Walk the gate sequence; first failure terminates. Returns the full
    decision including the passed-gate trail for the audit record."""
    passed: list = []
    grade = materiality_grade(candidate.materiality)

    def reject(state: str) -> GateDecision:
        return GateDecision(
            final_state=state, display_tier="excluded", gates_passed=passed,
            rejection_reason=state, materiality_grade=grade,
        )

    # ENTITY_VALID -- the ticker resolves to a real, tradeable company.
    if not candidate.entity_resolved:
        return reject("REJECT_UNKNOWN_COMPANY")
    passed.append("ENTITY_VALID")

    # BUSINESS_MODEL_VALID / MECHANISM_VALID -- a real, articulated causal
    # channel; a missing or trivial mechanism is not an analysis.
    if len((candidate.mechanism or "").strip()) < _MIN_MECHANISM_CHARS:
        return reject("REJECT_WEAK_MECHANISM")
    passed.append("BUSINESS_MODEL_VALID")
    passed.append("MECHANISM_VALID")

    # COMPANY_SPECIFIC_EXPOSURE_VALID -- generic sector prose only stands
    # when a company-specific evidence record exists independently of it.
    if (_is_generic_rationale(candidate.rationale)
            and candidate.evidence_class not in PRIMARY_CAPABLE_EVIDENCE):
        return reject("REJECT_GENERIC_EXPOSURE")
    passed.append("COMPANY_SPECIFIC_EXPOSURE_VALID")

    # EVENT_APPLICABILITY_VALID -- counterfactual proxy (spec §14): the
    # causal path must root in this event's own shock; otherwise the claim
    # survives the event's removal and is a generic macro story.
    if not candidate.trigger_shock_present:
        return reject("REJECT_NOT_EVENT_SPECIFIC")
    passed.append("EVENT_APPLICABILITY_VALID")

    # CAUSAL_PATH_VALID -- distance policy (spec §13). d4+ is a third-order
    # chain: excluded outright, no policy override here (INV-013).
    if candidate.causal_distance >= 4:
        return reject("REJECT_TOO_DISTANT")
    passed.append("CAUSAL_PATH_VALID")

    # MATERIALITY_VALID -- NO_MATERIAL_IMPACT and UNKNOWN materiality never
    # display; LOW survives only as secondary (graded below).
    if candidate.economic_effect == "no_material_impact":
        return reject("REJECT_NO_MATERIAL_IMPACT")
    if grade == "UNKNOWN":
        return reject("REJECT_LOW_MATERIALITY")
    passed.append("MATERIALITY_VALID")

    # EVIDENCE_VALID -- an evidence class outside the known vocabulary is a
    # wiring bug; fail closed rather than guess.
    known_evidence = (PRIMARY_CAPABLE_EVIDENCE | NEVER_PRIMARY_EVIDENCE
                      | {ARCHETYPE_EVIDENCE})
    if candidate.evidence_class not in known_evidence:
        return reject("REJECT_INSUFFICIENT_EVIDENCE")
    passed.append("EVIDENCE_VALID")

    # CONTRADICTION_FREE -- effect and net direction must tell one story.
    effect_dir = _EFFECT_AS_DIRECTION.get(candidate.economic_effect)
    if effect_dir is None:
        return reject("REJECT_CONTRADICTORY")
    if candidate.net_direction and _net_as_direction(candidate.net_direction) != effect_dir:
        return reject("REJECT_CONTRADICTORY")
    passed.append("CONTRADICTION_FREE")

    # VERIFIED -- independent verification is mandatory. Unavailable
    # verification is its own state so postmortems can separate "the
    # verifier said no" from "the verifier never ran" (INV-005/016).
    if not candidate.independently_verified:
        if not candidate.verification_available:
            return reject("REJECT_VALIDATOR_UNAVAILABLE")
        return reject("REJECT_UNVERIFIED")
    passed.append("VERIFIED")

    # --- DISPLAY_ELIGIBLE: grade the tier -------------------------------
    tier = _display_tier(candidate, grade)
    return GateDecision(
        final_state="DISPLAY_ELIGIBLE", display_tier=tier, gates_passed=passed,
        rejection_reason=None, materiality_grade=grade,
    )


def _display_tier(candidate: CandidateInput, grade: str) -> str:
    """Primary/secondary policy (spec §13/§15/§19/§26), applied only after
    every mandatory gate passed."""
    # UNCERTAIN never renders as a primary result (INV-012).
    if candidate.economic_effect == "uncertain":
        return "secondary"
    if grade == "LOW":
        return "secondary"
    # Tier E / market-observation evidence cannot authorize primary.
    if candidate.evidence_class in NEVER_PRIMARY_EVIDENCE:
        return "secondary"
    distance = candidate.causal_distance
    if distance >= 3:
        return "secondary"
    if distance == 2:
        # d2 primary needs strong company-specific evidence AND high
        # materiality (spec §13); anything less is secondary.
        if (candidate.evidence_class in PRIMARY_CAPABLE_EVIDENCE
                and grade == "HIGH"):
            return "primary"
        return "secondary"
    # d1: archetype evidence still needs HIGH materiality for primary.
    if candidate.evidence_class == ARCHETYPE_EVIDENCE and grade != "HIGH":
        return "secondary"
    return "primary"
