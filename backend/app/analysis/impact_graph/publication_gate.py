"""Company publication gate (spec 2026-08-12 §5, corrective-v4 Task 4): the
single deterministic authority for what reaches the user-facing feed.

Discovery (sector pools, archetypes, ripple branches, completeness audits,
article subjects) proposes candidates; nothing it produces is publishable
by itself. Every candidate walks the same ordered state machine and either
becomes DISPLAY_ELIGIBLE with a tier (primary / secondary_deep_dive) or
terminates in a machine-readable REJECT_* state. Publication fails closed:
a gate that cannot be evaluated rejects, it never waves through.

The state machine is EXECUTABLE, not documentation: ``GATE_SEQUENCE`` is a
list of ``(name, check)`` pairs and :func:`evaluate_candidate` does nothing
but walk it. The constant IS the execution order (INV-006 by construction) --
there is no second, hidden ordering in straight-line ``if`` statements that
can drift away from it. Every state in ``REJECTION_STATES`` is reachable
from at least one check; the parametrized reachability test pins that, which
is what keeps the vocabulary from rotting into dead strings.

Purity: this module reads the candidate, the per-alert context and owner
policy config. No DB, no LLM, no market fields (INV-002 is enforced
structurally by ``test_inv002_gate_input_has_no_market_fields``).

Authority order (spec §64): deterministic policy here outranks any LLM
output -- the model may propose and challenge, never overrule a rejection.
"""
from dataclasses import dataclass, field, replace
from typing import Callable

from app.config import settings

# --- vocabulary -----------------------------------------------------------

REJECTION_STATES = frozenset({
    "REJECT_ENTITY_AMBIGUOUS",
    "REJECT_UNKNOWN_COMPANY",
    "REJECT_DUPLICATE",
    "REJECT_GENERIC_EXPOSURE",
    "REJECT_WEAK_MECHANISM",
    "REJECT_NOT_EVENT_SPECIFIC",
    "REJECT_TOO_DISTANT",
    "REJECT_LOW_PRIORITY",
    "REJECT_LOW_MATERIALITY",
    "REJECT_NO_MATERIAL_IMPACT",
    "REJECT_INSUFFICIENT_EVIDENCE",
    "REJECT_CONTRADICTORY",
    "REJECT_UNVERIFIED",
    "REJECT_VALIDATOR_UNAVAILABLE",
})

DISPLAY_ELIGIBLE = "DISPLAY_ELIGIBLE"

# Display tiers. "secondary_deep_dive" is the serialized value; the legacy
# "secondary" string stays readable on old rows (never written anew).
TIER_PRIMARY = "primary"
TIER_DEEP_DIVE = "secondary_deep_dive"
TIER_EXCLUDED = "excluded"

# Evidence tiers (canonical policy table):
#   A/B        structured primary evidence records
#   C          VERIFIED_RELATIONSHIP backed by an independent artifact
#   SUBJECT    ARTICLE_SUBJECT -- primary-capable, C-equivalent
#   D          curated archetype / model-verified prior / legacy unverified
#   E          MODEL_INFERENCE -- never authorizes a published result
#   MARKET_OBS ARTICLE_MARKET_OBSERVATION -- "the stock fell 3%" is a market
#              fact, not fundamental evidence (INV-003)
KNOWN_EVIDENCE_TIERS = frozenset({"A", "B", "C", "D", "E", "SUBJECT", "MARKET_OBS"})
STRUCTURED_TIERS = frozenset({"A", "B"})
# "Tier >= C": what may carry a company-specific claim at all. ARTICLE_SUBJECT
# belongs here -- being the article's own subject IS company-specific evidence.
STRONG_TIERS = frozenset({"A", "B", "C", "SUBJECT"})
# Owner ruling (Task 4 review, I1): ARTICLE_SUBJECT is strong evidence about
# the company AT DISTANCE 1 ONLY. Two hops out, "the article was about them"
# says nothing about the transmission chain, so d2-primary and d3-deep-dive
# require a structured relationship record (A/B) or a verified relationship
# (C). SUBJECT at d2/d3 behaves like tier D.
RELATIONSHIP_TIERS = frozenset({"A", "B", "C"})
NON_AUTHORIZING_TIERS = frozenset({"E", "MARKET_OBS"})

# Transitional bridge from the legacy evidence-class vocabulary (Task 5
# replaces the producer with a real classifier; the gate keeps reading
# tiers either way).
EVIDENCE_CLASS_TO_TIER = {
    "ARTICLE_SUBJECT": "SUBJECT",
    "VERIFIED_RELATIONSHIP": "C",
    "CURATED_ARCHETYPE": "D",
    "MODEL_VERIFIED_PRIOR": "D",
    "LEGACY_UNVERIFIED": "D",
    "MODEL_INFERENCE": "E",
    "ARTICLE_MARKET_OBSERVATION": "MARKET_OBS",
}

ECONOMIC_EFFECTS = frozenset({
    "positive", "negative", "mixed", "uncertain", "no_material_impact",
})

ANALYSIS_QUALITIES = frozenset({"authoritative", "fallback", "degraded", "failed"})

COUNTERFACTUAL_VERDICTS = frozenset({"SUPPORTED", "NOT_SUPPORTED", "UNCERTAIN"})

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

NOTE_PRIMARY_CAP_OVERFLOW = "primary_cap_overflow"
NOTE_DUPLICATE = "duplicate_company"


# --- data ------------------------------------------------------------------

@dataclass(frozen=True)
class CandidateInput:
    """Everything the gate needs, resolved by the caller -- the gate itself
    never touches the DB or an LLM, which is what keeps it testable and
    incorruptible."""
    ticker: str
    entity_status: str            # resolved | ambiguous | unresolved
    company_profile_present: bool  # business_desc or exposure row for dimension
    mechanism: str
    rationale: str
    economic_effect: str          # canonical 5-way
    causal_distance: int
    materiality: float | None
    confidence: float | None
    independently_verified: bool
    verification_available: bool  # False when verification could not run at all
    evidence_class: str
    counterfactual: str           # SUPPORTED | NOT_SUPPORTED | UNCERTAIN
    analysis_quality: str         # authoritative | fallback | degraded | failed
    # Resolved-company identity for dedup: two tickers can name one company,
    # and the company is what the user sees twice. Empty falls back to the
    # ticker.
    company_key: str = ""
    # Derived from evidence_class when the caller has no classifier yet.
    evidence_tier: str = ""
    net_direction: str = ""
    positive_channels: list = field(default_factory=list)
    negative_channels: list = field(default_factory=list)
    # Fail-closed default: a caller that never computed the structural
    # counterfactual has not shown the claim roots in this event, and
    # "not computed" must never read as "rooted".
    trigger_shock_present: bool = False


@dataclass(frozen=True)
class GateContext:
    """Per-alert context + owner policy overrides. ``None`` on a policy
    field means "read the deployed configuration" -- tests and callers can
    pin a value without touching global settings."""
    seen_tickers: frozenset = frozenset()
    allow_low_materiality_deep_dive: bool | None = None
    allow_fallback_primary: bool | None = None
    max_primary_companies: int | None = None

    @property
    def low_materiality_deep_dive_allowed(self) -> bool:
        if self.allow_low_materiality_deep_dive is None:
            return bool(settings.impact_allow_low_materiality_deep_dive)
        return bool(self.allow_low_materiality_deep_dive)

    @property
    def fallback_primary_allowed(self) -> bool:
        if self.allow_fallback_primary is None:
            return bool(settings.impact_allow_fallback_primary)
        return bool(self.allow_fallback_primary)

    @property
    def primary_cap(self) -> int:
        if self.max_primary_companies is None:
            return int(settings.impact_max_primary_companies)
        return int(self.max_primary_companies)


@dataclass(frozen=True)
class GateDecision:
    """The gate's verdict. Consumers MUST key on `final_state` (and
    `display_tier`), never on the length or membership of `gates_passed`:
    that list is an audit trail of how far the walk got, and adding a gate
    to GATE_SEQUENCE changes its length for every decision. `notes` carries
    alert-level finalization detail (primary_cap_overflow, duplicate)."""
    final_state: str              # DISPLAY_ELIGIBLE or a REJECT_* state
    display_tier: str             # primary | secondary_deep_dive | excluded
    gates_passed: list
    rejection_reason: str | None
    materiality_grade: str        # HIGH | MEDIUM | LOW | UNKNOWN
    ticker: str = ""
    # Identity for alert-level dedup: the RESOLVED company (two tickers can
    # name one company). Falls back to the ticker when the caller has no
    # resolved id.
    dedup_key: str = ""
    materiality: float | None = None
    confidence: float | None = None
    notes: str | None = None


# --- helpers ---------------------------------------------------------------

def materiality_grade(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    if value >= _MATERIALITY_HIGH:
        return "HIGH"
    if value >= _MATERIALITY_MEDIUM:
        return "MEDIUM"
    return "LOW"


def evidence_tier_of(candidate: CandidateInput) -> str:
    """The candidate's declared tier, falling back to the legacy class map.
    An unmappable class yields "" -- which EVIDENCE_VALID rejects rather
    than guessing (fail closed)."""
    tier = (candidate.evidence_tier or "").strip().upper()
    if tier:
        return tier
    return EVIDENCE_CLASS_TO_TIER.get(candidate.evidence_class, "")


def _is_generic_rationale(rationale: str) -> bool:
    lowered = (rationale or "").lower()
    return any(phrase in lowered for phrase in _GENERIC_PHRASES)


_EFFECT_AS_DIRECTION = {
    "positive": "bullish", "negative": "bearish",
    "mixed": "neutral", "uncertain": "neutral", "no_material_impact": "neutral",
}


def _net_as_direction(net_direction: str) -> str:
    return net_direction if net_direction in ("bullish", "bearish") else "neutral"


# --- gate checks -----------------------------------------------------------
# Each check answers one question and returns either None (pass) or the
# rejection state that terminates the walk. They are pure functions of
# (candidate, context) so the ordering below is the ONLY control flow.

def _check_entity_valid(c: CandidateInput, ctx: GateContext) -> str | None:
    """The ticker resolves to exactly one real, tradeable company."""
    if c.entity_status == "ambiguous":
        return "REJECT_ENTITY_AMBIGUOUS"
    if c.entity_status != "resolved":
        return "REJECT_UNKNOWN_COMPANY"
    return None


def candidate_identity(candidate: CandidateInput) -> str:
    """What "the same company twice" means: the resolved company when the
    caller knows it, the ticker otherwise."""
    return candidate.company_key or candidate.ticker


def _check_duplicate_free(c: CandidateInput, ctx: GateContext) -> str | None:
    """The same company may appear once per alert. Batch-level dedup (which
    of two occurrences wins) lives in finalize_alert_decisions; this catches
    a caller that already accepted this company for this alert."""
    if candidate_identity(c) in ctx.seen_tickers or c.ticker in ctx.seen_tickers:
        return "REJECT_DUPLICATE"
    return None


def _check_business_model_valid(c: CandidateInput, ctx: GateContext) -> str | None:
    """The company profile must be able to support the claimed mechanism.
    With no business description and no exposure record, only structured
    primary evidence (tier A/B) can carry the claim."""
    if not c.company_profile_present and evidence_tier_of(c) not in STRUCTURED_TIERS:
        return "REJECT_INSUFFICIENT_EVIDENCE"
    return None


def _check_mechanism_valid(c: CandidateInput, ctx: GateContext) -> str | None:
    """A real, articulated causal channel; a missing or trivial mechanism is
    not an analysis."""
    if len((c.mechanism or "").strip()) < _MIN_MECHANISM_CHARS:
        return "REJECT_WEAK_MECHANISM"
    return None


def _check_company_specific_exposure_valid(c: CandidateInput, ctx: GateContext) -> str | None:
    """Generic sector prose only stands when the evidence itself is
    company-specific (tier A/B/C/SUBJECT). At tier D/E the prose IS the
    claim, and an interchangeable sector sentence cannot be one."""
    if _is_generic_rationale(c.rationale) and evidence_tier_of(c) in ("D", "E"):
        return "REJECT_GENERIC_EXPOSURE"
    return None


def _check_event_applicability_valid(c: CandidateInput, ctx: GateContext) -> str | None:
    """Structural counterfactual proxy (spec §14): the causal path must root
    in this event's own shock, otherwise the claim survives the event's
    removal and is a generic macro story."""
    if not c.trigger_shock_present:
        return "REJECT_NOT_EVENT_SPECIFIC"
    return None


def _check_causal_path_valid(c: CandidateInput, ctx: GateContext) -> str | None:
    """Distance policy (spec §13). d4+ is a third-order chain: excluded
    outright, no policy override (INV-013). d3 survives only as a deep dive
    and only with strong evidence AND high materiality."""
    if c.causal_distance >= 4:
        return "REJECT_TOO_DISTANT"
    if c.causal_distance == 3 and not (
            evidence_tier_of(c) in RELATIONSHIP_TIERS
            and materiality_grade(c.materiality) == "HIGH"):
        return "REJECT_LOW_PRIORITY"
    return None


def _check_materiality_valid(c: CandidateInput, ctx: GateContext) -> str | None:
    """NO_MATERIAL_IMPACT never displays. UNKNOWN materiality is not a
    small number, it is an unmeasured one -- it never displays either. LOW
    displays only as a deep dive and only under explicit owner policy."""
    if c.economic_effect == "no_material_impact":
        return "REJECT_NO_MATERIAL_IMPACT"
    grade = materiality_grade(c.materiality)
    if grade == "UNKNOWN":
        return "REJECT_LOW_MATERIALITY"
    if grade == "LOW" and not ctx.low_materiality_deep_dive_allowed:
        return "REJECT_LOW_MATERIALITY"
    return None


def _check_evidence_valid(c: CandidateInput, ctx: GateContext) -> str | None:
    """Tier E (model inference) and bare market observation never authorize
    a published fundamental result (INV-003). An unknown tier is a wiring
    bug: fail closed rather than guess. UNCERTAIN effects need tier >= C
    and at least MEDIUM materiality to be worth a deep dive at all."""
    tier = evidence_tier_of(c)
    if tier not in KNOWN_EVIDENCE_TIERS:
        return "REJECT_INSUFFICIENT_EVIDENCE"
    if tier in NON_AUTHORIZING_TIERS:
        return "REJECT_INSUFFICIENT_EVIDENCE"
    if c.economic_effect == "uncertain" and not (
            tier in STRONG_TIERS
            and materiality_grade(c.materiality) in ("HIGH", "MEDIUM")):
        return "REJECT_INSUFFICIENT_EVIDENCE"
    return None


def _check_contradiction_free(c: CandidateInput, ctx: GateContext) -> str | None:
    """Effect and net direction must tell one story; an unknown effect is
    itself a contradiction with the closed vocabulary."""
    effect_dir = _EFFECT_AS_DIRECTION.get(c.economic_effect)
    if effect_dir is None:
        return "REJECT_CONTRADICTORY"
    if c.net_direction and _net_as_direction(c.net_direction) != effect_dir:
        return "REJECT_CONTRADICTORY"
    return None


def _check_counterfactual_valid(c: CandidateInput, ctx: GateContext) -> str | None:
    """Semantic counterfactual verdict (Task 9 wires the verifier): would
    this claim be false if the event had not happened? NOT_SUPPORTED means
    the story survives the event's removal -- a generic macro claim. An
    unrecognized verdict is NOT the same finding: it means the check did not
    produce an answer, which is a validator failure, not evidence about the
    candidate. UNCERTAIN passes but can never be primary (graded below)."""
    verdict = (c.counterfactual or "").strip().upper()
    if verdict == "NOT_SUPPORTED":
        return "REJECT_NOT_EVENT_SPECIFIC"
    if verdict not in COUNTERFACTUAL_VERDICTS:
        return "REJECT_VALIDATOR_UNAVAILABLE"
    return None


def _check_quality_valid(c: CandidateInput, ctx: GateContext) -> str | None:
    """A failed (or unrecognized) analysis pipeline cannot authorize
    display: the gate could not actually be evaluated on real output."""
    quality = (c.analysis_quality or "").strip().lower()
    if quality not in ANALYSIS_QUALITIES or quality == "failed":
        return "REJECT_VALIDATOR_UNAVAILABLE"
    return None


def _check_verified(c: CandidateInput, ctx: GateContext) -> str | None:
    """Independent verification is mandatory, and availability is checked
    FIRST, unconditionally: when the verifier never ran, a True
    `independently_verified` flag is not a verdict, it is an upstream
    default (the narrow path's in-call self-check, a budget overrun that
    skipped verification entirely). Short-circuiting on the flag let that
    default authorize display -- fail-open at the one gate that exists to
    fail closed (INV-005/016). Unavailable verification keeps its own state
    so postmortems can separate "the verifier said no" from "the verifier
    never ran"."""
    if not c.verification_available:
        return "REJECT_VALIDATOR_UNAVAILABLE"
    if not c.independently_verified:
        return "REJECT_UNVERIFIED"
    return None


GATE_SEQUENCE: list[tuple[str, Callable[[CandidateInput, GateContext], str | None]]] = [
    ("ENTITY_VALID", _check_entity_valid),
    ("DUPLICATE_FREE", _check_duplicate_free),
    ("BUSINESS_MODEL_VALID", _check_business_model_valid),
    ("MECHANISM_VALID", _check_mechanism_valid),
    ("COMPANY_SPECIFIC_EXPOSURE_VALID", _check_company_specific_exposure_valid),
    ("EVENT_APPLICABILITY_VALID", _check_event_applicability_valid),
    ("CAUSAL_PATH_VALID", _check_causal_path_valid),
    ("MATERIALITY_VALID", _check_materiality_valid),
    ("EVIDENCE_VALID", _check_evidence_valid),
    ("CONTRADICTION_FREE", _check_contradiction_free),
    ("COUNTERFACTUAL_VALID", _check_counterfactual_valid),
    ("QUALITY_VALID", _check_quality_valid),
    ("VERIFIED", _check_verified),
]

GATE_NAMES = [name for name, _ in GATE_SEQUENCE]


# --- evaluation ------------------------------------------------------------

def evaluate_candidate(candidate: CandidateInput,
                       context: GateContext | None = None) -> GateDecision:
    """Walk GATE_SEQUENCE in order; the first check that returns a state
    terminates the walk. Nothing outside the sequence can reject."""
    ctx = context if context is not None else GateContext()
    grade = materiality_grade(candidate.materiality)
    passed: list = []

    for name, check in GATE_SEQUENCE:
        state = check(candidate, ctx)
        if state is not None:
            return GateDecision(
                final_state=state, display_tier=TIER_EXCLUDED,
                gates_passed=passed, rejection_reason=state,
                materiality_grade=grade, ticker=candidate.ticker,
                dedup_key=candidate_identity(candidate),
                materiality=candidate.materiality, confidence=candidate.confidence,
            )
        passed.append(name)

    return GateDecision(
        final_state=DISPLAY_ELIGIBLE, display_tier=_display_tier(candidate, ctx),
        gates_passed=passed, rejection_reason=None, materiality_grade=grade,
        ticker=candidate.ticker, dedup_key=candidate_identity(candidate),
        materiality=candidate.materiality, confidence=candidate.confidence,
    )


def _primary_authorized(candidate: CandidateInput, ctx: GateContext) -> bool:
    """Primary is the strongest claim the product makes; every doubt
    downgrades it (spec §13/§15/§19/§26)."""
    grade = materiality_grade(candidate.materiality)
    tier = evidence_tier_of(candidate)
    quality = (candidate.analysis_quality or "").strip().lower()

    if candidate.economic_effect == "uncertain":
        return False                                   # INV-012
    if grade == "LOW":
        return False
    if (candidate.counterfactual or "").strip().upper() == "UNCERTAIN":
        return False
    if quality == "degraded":
        return False
    if quality == "fallback" and not ctx.fallback_primary_allowed:
        return False
    if candidate.causal_distance >= 3:
        return False
    if candidate.causal_distance == 2:
        # Two hops out, "the article was about them" (SUBJECT) is not
        # evidence about the transmission chain -- only a relationship
        # record is (owner ruling, Task 4 review).
        return tier in RELATIONSHIP_TIERS and grade == "HIGH"
    if tier not in STRONG_TIERS:
        return False                                   # tier D is a deep dive
    return True


def _display_tier(candidate: CandidateInput, ctx: GateContext) -> str:
    """Tier grading runs only after every gate passed, so it can never
    resurrect a rejected candidate -- it only chooses how loudly a
    surviving one speaks."""
    return TIER_PRIMARY if _primary_authorized(candidate, ctx) else TIER_DEEP_DIVE


# --- alert-level finalization ---------------------------------------------

def _rank_key(decision: GateDecision) -> tuple:
    """Deterministic ranking: materiality, then confidence, then ticker.
    Lower sorts first (i.e. best first)."""
    return (-(decision.materiality or 0.0), -(decision.confidence or 0.0),
            decision.ticker)


def _decision_identity(decision: GateDecision) -> str:
    return decision.dedup_key or decision.ticker


def finalize_alert_decisions(decisions: list[GateDecision],
                             context: GateContext | None = None) -> list[GateDecision]:
    """Alert-scoped policy that a single candidate cannot decide alone:

    1. Dedup -- the same company twice in one alert keeps the higher
       materiality occurrence; the other becomes REJECT_DUPLICATE. Identity
       is the RESOLVED company (`dedup_key`), not the ticker string: two
       tickers naming one company are one row to the reader.
    2. Primary cap -- at most ``impact_max_primary_companies`` primaries per
       alert, ranked deterministically; the overflow is demoted to
       secondary_deep_dive with the note ``primary_cap_overflow`` (demoted,
       never deleted: INV-015).

    Input order is preserved so the caller can zip results back onto rows.
    """
    ctx = context if context is not None else GateContext()
    out = list(decisions)

    winner_by_company: dict[str, int] = {}
    for index, decision in enumerate(out):
        if decision.final_state != DISPLAY_ELIGIBLE:
            continue
        identity = _decision_identity(decision)
        previous = winner_by_company.get(identity)
        if previous is None:
            winner_by_company[identity] = index
            continue
        if _rank_key(out[index]) < _rank_key(out[previous]):
            keep, drop = index, previous
        else:
            keep, drop = previous, index
        winner_by_company[identity] = keep
        out[drop] = replace(
            out[drop], final_state="REJECT_DUPLICATE", display_tier=TIER_EXCLUDED,
            rejection_reason="REJECT_DUPLICATE", notes=NOTE_DUPLICATE,
        )

    cap = ctx.primary_cap
    if cap is not None and cap >= 0:
        primaries = [i for i, d in enumerate(out)
                     if d.final_state == DISPLAY_ELIGIBLE
                     and d.display_tier == TIER_PRIMARY]
        primaries.sort(key=lambda i: _rank_key(out[i]))
        for index in primaries[cap:]:
            out[index] = replace(out[index], display_tier=TIER_DEEP_DIVE,
                                 notes=NOTE_PRIMARY_CAP_OVERFLOW)
    return out
