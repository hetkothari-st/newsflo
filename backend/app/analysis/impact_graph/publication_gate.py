"""Company publication gate (spec 2026-08-12 §5, corrective-v4 Task 4): the
single deterministic authority for what reaches the user-facing feed.

Discovery (sector pools, archetypes, ripple branches, completeness audits,
article subjects) proposes candidates; nothing it produces is publishable
by itself. Every candidate walks the same ordered state machine and either
becomes DISPLAY_ELIGIBLE with a tier (primary / secondary_ripple /
macro_context) or terminates in a machine-readable REJECT_* state.
Publication fails closed: a gate that cannot be evaluated rejects, it never
waves through.

Three tiers, not two (final blueprint §3/§5/§6/§7). PRIMARY maximizes
precision; SECONDARY_RIPPLE preserves governed analytical breadth for real
second-order companies; MACRO_CONTEXT carries validated broad economic
context at d3 without pretending it is a company-specific claim. The
symmetry that makes this honest runs both ways: failing PRIMARY does NOT
mean REJECTED (§6), and passing all thirteen gates does NOT guarantee
display -- a candidate that qualifies for no tier terminates in
``REJECT_BELOW_SECONDARY_POLICY`` with its full gate trail intact.

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
from dataclasses import asdict, dataclass, field, replace
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
    # Blueprint §6, the symmetric half of "failing PRIMARY is not
    # REJECTED": a candidate that walked all thirteen gates but qualifies
    # for no display tier. Distinct from every gate rejection above --
    # nothing about the candidate is invalid, it simply does not clear the
    # publication POLICY for any tier (today: an `uncertain` net effect,
    # which §4 sends to "reject from display").
    "REJECT_BELOW_SECONDARY_POLICY",
})

# Gate policy version (corrective-v4 Task 15): bumped whenever the gate's
# decision logic changes in a way that could flip a previously-cached
# analysis's outcome. Threaded into the v3 result cache key and the
# stage-cache fingerprint so a policy bump is an EXPLICIT invalidation,
# never a silent replay of a decision made under the old rules.
# pol-2 (final blueprint §3/§6/§7): two-way grading became three-way
# (primary / secondary_ripple / macro_context) and gates-passed-but-
# below-policy became a recorded rejection.
POLICY_VERSION = "pol-2"

DISPLAY_ELIGIBLE = "DISPLAY_ELIGIBLE"

# Display tiers (blueprint §3). "secondary_ripple" is the serialized value
# the gate writes now; "secondary_deep_dive" (corrective-v4) and "secondary"
# (pre-v4) stay READABLE on old rows and are never written anew. Compare
# tiers through `is_secondary_tier` rather than against a literal, so a
# consumer cannot silently stop seeing legacy rows.
TIER_PRIMARY = "primary"
TIER_SECONDARY_RIPPLE = "secondary_ripple"
TIER_MACRO_CONTEXT = "macro_context"
TIER_EXCLUDED = "excluded"
# Deprecated alias kept so untouched call sites keep importing one name and
# writing ONE value -- the alias moved, the spelling it produces did too.
TIER_DEEP_DIVE = TIER_SECONDARY_RIPPLE

LEGACY_SECONDARY_SPELLINGS = ("secondary_deep_dive", "secondary")
DISPLAYABLE_TIERS = (TIER_PRIMARY, TIER_SECONDARY_RIPPLE, TIER_MACRO_CONTEXT)


def is_secondary_tier(value: str | None) -> bool:
    """True for the current secondary spelling AND every legacy spelling a
    persisted row may still carry. The ONE place read-compat lives, so a
    consumer that migrates to it can never regress into a literal compare
    that drops pre-migration rows."""
    return (value or "") in (TIER_SECONDARY_RIPPLE,) + LEGACY_SECONDARY_SPELLINGS


def is_displayable_tier(value: str | None) -> bool:
    """Displayable = any tier the reader can actually see, legacy spellings
    included. `excluded` and unknown strings are not."""
    return (value or "") in DISPLAYABLE_TIERS or is_secondary_tier(value)

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
# What may carry a SECONDARY_RIPPLE / MACRO_CONTEXT claim (blueprint §17:
# "C/D may be sufficient for durable relationships"; "D may be acceptable
# for generic economic context"). SUBJECT rides with them because the
# canonical table above already declares it C-equivalent -- §17 enumerates
# A..E only and never demotes it, and dropping it here would silently make
# "the article was about them" at d2 UNPUBLISHABLE, which is a breadth
# regression this pass exists to prevent (§1).
SECONDARY_EVIDENCE_TIERS = frozenset({"A", "B", "C", "D", "SUBJECT"})

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

# The effects a customer-visible company row may carry (blueprint §4:
# "unresolved evidence/contradiction -> UNCERTAIN / reject from display";
# §19: NO_MATERIAL_IMPACT never renders). MIXED is a first-class RESULT,
# not a hedge -- refiner_marketing_margin is a DIRECT d1 mechanism whose
# honest effect is mixed, so nothing here may assume DIRECT implies a
# single-signed effect.
DISPLAYABLE_EFFECTS = frozenset({"positive", "negative", "mixed"})

ANALYSIS_QUALITIES = frozenset({"authoritative", "fallback", "degraded", "failed"})

COUNTERFACTUAL_VERDICTS = frozenset({"SUPPORTED", "NOT_SUPPORTED", "UNCERTAIN"})

# Causal directness (blueprint §3/§11) -- a SEPARATE dimension from causal
# distance. §11: "Do not derive DIRECT/INDIRECT solely from d1/d2."
DIRECTNESS_VALUES = ("DIRECT", "INDIRECT", "REMOTE")
DIRECTNESS_UNKNOWN = "INDIRECT"

# Confidence bands (blueprint §18). The band is the ONLY confidence the
# reader sees: "do not display HIGH when the evidence basis is weak", and
# "do not create fake numeric precision" (the 49-for-everyone score).
CONFIDENCE_BANDS = ("HIGH", "MEDIUM", "LOW", "UNKNOWN")

# Net-effect validator verdict (blueprint §4/§24). One reason string, not a
# free-text explanation: this is a machine-readable block, and the Oil India
# shape (company bearish, every validated channel bullish) is exactly what
# it names.
NET_EFFECT_CONTRADICTION = "NET_EFFECT_CONTRADICTION"

# THE canonical effect -> direction map (blueprint §4: one authoritative
# field, `economic_effect`; direction is DERIVED, never independent). Every
# consumer that needs a direction reads it from here -- a second table is
# how Oil India got a bearish company on top of bullish channels.
DIRECTION_FROM_EFFECT = {
    "positive": "bullish",
    "negative": "bearish",
    "mixed": "neutral",
    "uncertain": "neutral",
    "no_material_impact": "neutral",
}

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


def is_gated(alert_companies) -> bool:
    """True when ANY row in `alert_companies` carries v4 gate output --
    `gate_state` OR `display_tier` non-NULL (owner ruling, corrective-v4
    Task 12 review round 2 / I1+I4: the owner's structural-unreachability
    text is an OR of the two fields, not `gate_state` alone -- a row could
    in principle carry one without the other, and either one present means
    this alert went through gate-aware persistence).

    Takes the AlertCompany rows directly (an iterable), not an Alert object
    -- callers that already hold the exact list they care about (e.g.
    refine_alert's `alert_companies` argument) pass it straight through
    rather than relying on `alert.companies`' relationship state matching;
    a caller working from the Alert itself passes `alert.companies`.

    This is the SINGLE structural signal shared by every consumer that must
    make the legacy (ungated) rendering/analysis path unreachable once an
    alert is gated: `app.market.ripple_layers.compute_ripple_layers` (legacy
    3-tier section generator) and `app.analysis.refinement.refine_alert`
    (legacy why-text/section LLM calls). Deliberately reads only fields
    already on the ORM objects -- no DB query, no `settings.
    impact_engine_v4_strict` check: reachability is structural, not modal,
    so a flag flip after gated rows were persisted can never resurrect the
    legacy path for them. Lives here (not in app.market or app.analysis.
    refinement) so both can import it without a cycle -- this module only
    imports app.config at module scope, and neither of theirs imports it
    back.
    """
    return any(
        alert_company.gate_state is not None or alert_company.display_tier is not None
        for alert_company in alert_companies
    )


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
    # Composite grade (Task 8, app.analysis.impact_graph.materiality): the
    # caller-computed grade that already applied the exposure/evidence
    # caps. Empty string (the default) means the caller never computed one
    # -- every gate check falls back to `materiality_grade(materiality)`,
    # the naked-float grade, so old callers (benchmark harness, tests
    # written before Task 8) keep working unmodified.
    materiality_grade: str = ""
    net_direction: str = ""
    positive_channels: list = field(default_factory=list)
    negative_channels: list = field(default_factory=list)
    # Fail-closed default: a caller that never computed the structural
    # counterfactual has not shown the claim roots in this event, and
    # "not computed" must never read as "rooted".
    trigger_shock_present: bool = False
    # --- blueprint §3/§22: five SEPARATE dimensions --------------------
    # Causal directness, independent of causal_distance (§11). Empty means
    # "the caller did not classify it"; `derive_directness` then asks the
    # knowledge registry, and only falls back to distance when the registry
    # is silent too.
    causal_directness: str = ""
    # HOW this candidate was found (§22: stop overloading one `basis`
    # field). Discovery is not causality and is not evidence; keeping the
    # three apart is what stops "direct_mention" from reading as "direct
    # causal relationship".
    discovery_source: str = ""
    # The causal parent this candidate hangs off, in the persisted
    # vocabulary. Used ONLY to resolve directness (and, downstream, the
    # section taxonomy) from the knowledge registry -- never to grade.
    causal_parent_type: str = ""
    causal_parent_id: str = ""


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
    display_tier: str             # primary | secondary_ripple | macro_context | excluded
    gates_passed: list
    rejection_reason: str | None
    materiality_grade: str        # HIGH | MEDIUM | LOW | UNKNOWN
    ticker: str = ""
    # Blueprint §3/§11: the relationship's directness, carried alongside the
    # tier because they answer DIFFERENT questions -- "ONGC: DIRECT + d1 +
    # SECONDARY_RIPPLE" is a legal, meaningful verdict.
    causal_directness: str = DIRECTNESS_UNKNOWN
    # Blueprint §18: the only confidence the reader may be shown. Defaults
    # to UNKNOWN so a hand-built decision never claims a band it did not
    # earn (populated for real by evaluate_candidate).
    confidence_band: str = "UNKNOWN"
    # Identity for alert-level dedup: the RESOLVED company (two tickers can
    # name one company). Falls back to the ticker when the caller has no
    # resolved id.
    dedup_key: str = ""
    materiality: float | None = None
    confidence: float | None = None
    notes: str | None = None
    # Full CandidateInput.asdict() the gate walked (corrective-v4 Task 18,
    # spec sec54): the decision record's durable "here is EXACTLY what the
    # gate saw" field. A caller that builds a GateDecision by hand (tests,
    # the dedup-reuse copy path) gets the honest default {} rather than a
    # reconstruction -- this is populated ONLY by evaluate_candidate below.
    candidate_snapshot: dict = field(default_factory=dict)


# --- helpers ---------------------------------------------------------------

def materiality_grade(value: float | None) -> str:
    """The naked-float grade -- HIGH/MEDIUM/LOW/UNKNOWN from
    `materiality` alone, no exposure or evidence caps applied. Kept for
    backward compat (callers that pre-date Task 8, and as the fallback
    `_effective_grade` uses when a candidate carries no composite grade);
    the gate itself no longer calls this directly -- see `_effective_grade`
    and `app.analysis.impact_graph.materiality.materiality_grade` for the
    real composite."""
    if value is None:
        return "UNKNOWN"
    if value >= _MATERIALITY_HIGH:
        return "HIGH"
    if value >= _MATERIALITY_MEDIUM:
        return "MEDIUM"
    return "LOW"


def _effective_grade(candidate: CandidateInput) -> str:
    """The grade every gate check actually evaluates (Task 8): the
    caller-computed composite when supplied, falling back to the naked
    float for a candidate that never computed one. This is the ONE place
    that fallback lives, so no check can silently diverge from another on
    which grade it's looking at."""
    grade = (candidate.materiality_grade or "").strip().upper()
    return grade if grade else materiality_grade(candidate.materiality)


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


def _net_as_direction(net_direction: str) -> str:
    return net_direction if net_direction in ("bullish", "bearish") else "neutral"


def derive_directness(candidate) -> str:
    """The candidate's causal directness (blueprint §3/§11), resolved from
    the best information available, in that order:

    1. an EXPLICIT `causal_directness` the caller classified;
    2. the knowledge registry's own verdict for the mechanism this
       candidate hangs off (`causal_parent_id`) -- the registry IS the
       better information §11 demands, and it says crude->ONGC is DIRECT at
       d1 while crude->petchem->paints is INDIRECT at d2;
    3. only then, distance -- and only as a last resort, because §11's
       whole point is that DIRECT/INDIRECT is NOT a synonym for d1/d2.

    Duck-typed on purpose: a CandidateInput, a GraphCompany-shaped object
    or an AlertCompany row all answer the same three attributes.
    """
    explicit = str(getattr(candidate, "causal_directness", "") or "").strip().upper()
    if explicit in DIRECTNESS_VALUES:
        return explicit

    parent_type = str(getattr(candidate, "causal_parent_type", "") or "").strip().lower()
    parent_id = str(getattr(candidate, "causal_parent_id", "") or "").strip()
    # "" parent_type is tolerated (older callers carry the id alone); a
    # parent that is a sector/company/event node is NOT a mechanism and must
    # not be looked up as one.
    if parent_id and parent_type in ("", "economic_node", "commodity", "policy"):
        # Local import: the registry pulls in SQLAlchemy models, and this
        # module's purity contract (no DB at module scope, no import cycle
        # with app.market / app.pipeline) is worth one deferred import.
        # `mechanism_meta_for_node`, NOT `mechanism_meta`: the id on the row
        # is the PERSISTED one (`normalize_node_id(mechanism_id)`), and 9 of
        # the 42 registry keys change under that transform. A raw-keyed
        # lookup missed exactly those nine and dropped them, silently, to
        # the distance fallback below -- i.e. to the "DIRECT/INDIRECT is a
        # synonym for d1/d2" this whole function exists to refuse.
        from app.analysis.impact_graph.knowledge import mechanism_meta_for_node

        meta = mechanism_meta_for_node(parent_id)
        if meta is not None and meta.get("directness") in DIRECTNESS_VALUES:
            return meta["directness"]

    distance = getattr(candidate, "causal_distance", None)
    try:
        distance = int(distance)
    except (TypeError, ValueError):
        return DIRECTNESS_UNKNOWN
    if distance <= 1:
        return "DIRECT"
    if distance == 2:
        return "INDIRECT"
    return "REMOTE"


def confidence_band(candidate, decision_tier: str) -> str:
    """The reader-facing confidence band (blueprint §18), computed
    DETERMINISTICALLY from the contributors that actually exist -- evidence
    tier, materiality grade, counterfactual verdict, analysis quality and
    verification -- never from an LLM's self-reported number.

    Two rules are absolute:

    * HIGH is impossible on tier D/E evidence ("do not display HIGH when
      the evidence basis is weak"). A curated archetype is a hint.
    * A candidate that did not reach a displayable tier has no band to
      display: that is UNKNOWN, not LOW. LOW is a statement about a claim
      the reader can see.
    """
    if not is_displayable_tier(decision_tier):
        return "UNKNOWN"

    quality = (candidate.analysis_quality or "").strip().lower()
    if quality not in ANALYSIS_QUALITIES or quality == "failed":
        return "UNKNOWN"
    if not candidate.verification_available:
        return "UNKNOWN"                       # the verifier never ran

    grade = _effective_grade(candidate)
    if grade == "UNKNOWN":
        return "UNKNOWN"                       # unmeasured, not "small"

    tier = evidence_tier_of(candidate)
    verdict = (candidate.counterfactual or "").strip().upper()

    if (tier in STRONG_TIERS and grade == "HIGH"
            and verdict == "SUPPORTED" and quality == "authoritative"):
        return "HIGH"
    if (tier in SECONDARY_EVIDENCE_TIERS and grade in ("HIGH", "MEDIUM")
            and candidate.independently_verified):
        return "MEDIUM"
    return "LOW"


def validate_net_effect(economic_effect: str, channel_effects: list) -> str | None:
    """Blueprint §4/§24 deterministic net-effect validator: does the
    company's single authoritative `economic_effect` actually follow from
    its validated channels?

    Returns None when consistent, ``NET_EFFECT_CONTRADICTION`` otherwise.
    This is THE check that makes the Oil India shape (company NEGATIVE, one
    validated POSITIVE upstream-realization channel, positive UI result)
    structurally impossible.

    Rules, straight from §4:

    * positive -> at least one positive channel and NO material negative
    * negative -> the mirror image
    * mixed    -> at least one of each (a `mixed` CHANNEL supplies both:
                  refiner_marketing_margin genuinely cuts both ways, so it
                  counts as material on each side rather than being
                  laundered into whichever sign the company claimed)
    * uncertain / no_material_impact -> nothing to contradict; they are
      never displayable anyway (see DISPLAYABLE_EFFECTS), so the validator
      abstains instead of inventing a verdict about them.

    An unknown effect string is a contradiction with the closed vocabulary,
    not a pass.
    """
    effect = (economic_effect or "").strip().lower()
    channels = [(value or "").strip().lower() for value in (channel_effects or [])]
    positive = sum(1 for value in channels if value in ("positive", "mixed"))
    negative = sum(1 for value in channels if value in ("negative", "mixed"))

    if effect in ("uncertain", "no_material_impact"):
        return None
    if effect == "positive":
        return None if (positive >= 1 and negative == 0) else NET_EFFECT_CONTRADICTION
    if effect == "negative":
        return None if (negative >= 1 and positive == 0) else NET_EFFECT_CONTRADICTION
    if effect == "mixed":
        return None if (positive >= 1 and negative >= 1) else NET_EFFECT_CONTRADICTION
    return NET_EFFECT_CONTRADICTION


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
            and _effective_grade(c) == "HIGH"):
        return "REJECT_LOW_PRIORITY"
    return None


def _check_materiality_valid(c: CandidateInput, ctx: GateContext) -> str | None:
    """NO_MATERIAL_IMPACT never displays. UNKNOWN materiality is not a
    small number, it is an unmeasured one -- it never displays either. LOW
    displays only as a deep dive and only under explicit owner policy."""
    if c.economic_effect == "no_material_impact":
        return "REJECT_NO_MATERIAL_IMPACT"
    grade = _effective_grade(c)
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
            and _effective_grade(c) in ("HIGH", "MEDIUM")):
        return "REJECT_INSUFFICIENT_EVIDENCE"
    return None


def _check_contradiction_free(c: CandidateInput, ctx: GateContext) -> str | None:
    """Effect and net direction must tell one story; an unknown effect is
    itself a contradiction with the closed vocabulary."""
    effect_dir = DIRECTION_FROM_EFFECT.get(c.economic_effect)
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
    grade = _effective_grade(candidate)
    directness = derive_directness(candidate)
    passed: list = []
    # dataclasses.asdict deep-copies -- safe to hand out without the
    # caller being able to mutate the CandidateInput back through it.
    snapshot = asdict(candidate)

    def _rejected(state: str) -> GateDecision:
        return GateDecision(
            final_state=state, display_tier=TIER_EXCLUDED,
            gates_passed=passed, rejection_reason=state,
            materiality_grade=grade, ticker=candidate.ticker,
            causal_directness=directness,
            confidence_band=confidence_band(candidate, TIER_EXCLUDED),
            dedup_key=candidate_identity(candidate),
            materiality=candidate.materiality, confidence=candidate.confidence,
            candidate_snapshot=snapshot,
        )

    for name, check in GATE_SEQUENCE:
        state = check(candidate, ctx)
        if state is not None:
            return _rejected(state)
        passed.append(name)

    tier = _display_tier(candidate, ctx)
    if tier == TIER_EXCLUDED:
        # Every gate passed and no tier policy accepts it. Blueprint §6 is
        # symmetric: failing PRIMARY does not mean REJECTED, and clearing
        # the gates does not mean PUBLISHED. The full 13-gate trail rides
        # along on `gates_passed` so a postmortem can see this was a POLICY
        # outcome, not a validity failure.
        return _rejected("REJECT_BELOW_SECONDARY_POLICY")

    return GateDecision(
        final_state=DISPLAY_ELIGIBLE, display_tier=tier,
        gates_passed=passed, rejection_reason=None, materiality_grade=grade,
        ticker=candidate.ticker, causal_directness=directness,
        confidence_band=confidence_band(candidate, tier),
        dedup_key=candidate_identity(candidate),
        materiality=candidate.materiality, confidence=candidate.confidence,
        candidate_snapshot=snapshot,
    )


def _primary_authorized(candidate: CandidateInput, ctx: GateContext) -> bool:
    """Primary is the strongest claim the product makes; every doubt
    downgrades it (blueprint §5, spec §13/§15/§19/§26)."""
    grade = _effective_grade(candidate)
    tier = evidence_tier_of(candidate)
    quality = (candidate.analysis_quality or "").strip().lower()

    if candidate.economic_effect not in DISPLAYABLE_EFFECTS:
        return False                                   # INV-012 (uncertain)
    if grade == "LOW":
        return False
    if (candidate.counterfactual or "").strip().upper() == "UNCERTAIN":
        return False                                   # §20
    if quality == "degraded":
        return False
    if quality == "fallback" and not ctx.fallback_primary_allowed:
        return False
    if candidate.causal_distance >= 3:
        return False                                   # §5: d3+ never primary
    # Owner ruling R2, spelled as ONE condition instead of two distance
    # branches that could drift apart: relationship-grade evidence (A/B/C)
    # authorizes primary at any allowed distance; ARTICLE_SUBJECT authorizes
    # it at d1 ONLY -- two hops out, "the article was about them" says
    # nothing about the transmission chain. D and E can never be primary at
    # any distance (§3's ONGC example: tier D caps at SECONDARY_RIPPLE).
    if not (tier in RELATIONSHIP_TIERS
            or (tier == "SUBJECT" and candidate.causal_distance == 1)):
        return False
    if candidate.causal_distance == 2 and grade != "HIGH":
        return False                                   # §5: d2 needs HIGH
    return True


def _secondary_authorized(candidate: CandidateInput, ctx: GateContext) -> bool:
    """SECONDARY_RIPPLE (blueprint §6): the governed breadth tier. Every
    gate has already passed when this runs, so causal validity, entity
    validity, evidence integrity, mechanism quality and event-specificity
    are settled -- what is left is the ripple POLICY itself.

    Note what is NOT here: analysis quality and an UNCERTAIN counterfactual
    block PRIMARY but not a ripple row (§6 asks only that the verifier
    accept the relationship, and NOT_SUPPORTED was already rejected at the
    gate). That asymmetry IS the feature -- §1 exists because the first
    corrective pass collapsed valid ripples into one generic bucket.
    """
    if candidate.economic_effect not in DISPLAYABLE_EFFECTS:
        return False                                   # §4: uncertain does not display
    if evidence_tier_of(candidate) not in SECONDARY_EVIDENCE_TIERS:
        return False
    if candidate.causal_distance > 2:
        return False                                   # d3 is macro, d4+ already gone
    grade = _effective_grade(candidate)
    if grade == "LOW":
        return ctx.low_materiality_deep_dive_allowed   # §19, explicit policy only
    return grade in ("HIGH", "MEDIUM")


def _macro_context_authorized(candidate: CandidateInput) -> bool:
    """MACRO_CONTEXT (blueprint §7): validated broad economic context at
    d3. The CAUSAL_PATH gate has already made d3 expensive (relationship
    evidence AND HIGH materiality) and d4+ impossible; this tier is where
    a surviving d3 lands so the reader gets the macro chain WITHOUT it
    being dressed up as a company-specific primary claim."""
    return (candidate.causal_distance == 3
            and candidate.economic_effect in DISPLAYABLE_EFFECTS
            and evidence_tier_of(candidate) in SECONDARY_EVIDENCE_TIERS
            and _effective_grade(candidate) in ("HIGH", "MEDIUM"))


def _display_tier(candidate: CandidateInput, ctx: GateContext) -> str:
    """Tier grading runs only after every gate passed, so it can never
    resurrect a rejected candidate -- it only chooses how loudly a
    surviving one speaks, or that it does not speak at all.

    Cascade, strongest first. TIER_EXCLUDED here is NOT a gate failure: it
    is "gates passed, no tier policy accepts it", which evaluate_candidate
    records as REJECT_BELOW_SECONDARY_POLICY."""
    if _primary_authorized(candidate, ctx):
        return TIER_PRIMARY
    if _secondary_authorized(candidate, ctx):
        return TIER_SECONDARY_RIPPLE
    if _macro_context_authorized(candidate):
        return TIER_MACRO_CONTEXT
    return TIER_EXCLUDED


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
       secondary_ripple with the note ``primary_cap_overflow`` (demoted,
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
            # Nothing is displayed, so there is no band to display (§18).
            confidence_band="UNKNOWN",
        )

    cap = ctx.primary_cap
    if cap is not None and cap >= 0:
        primaries = [i for i, d in enumerate(out)
                     if d.final_state == DISPLAY_ELIGIBLE
                     and d.display_tier == TIER_PRIMARY]
        primaries.sort(key=lambda i: _rank_key(out[i]))
        for index in primaries[cap:]:
            out[index] = replace(out[index], display_tier=TIER_SECONDARY_RIPPLE,
                                 notes=NOTE_PRIMARY_CAP_OVERFLOW)
    return out
