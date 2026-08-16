"""TASK 0.4 -- the publication gate as config-driven code (spec §7.4).

PURE. No LLM (`tests/phase0/test_gates_no_llm.py` ast-scans this file
against the repo's provider modules), no DB, no disk -- the YAML lives in
`config/gates.yaml` and is loaded by `app.core.config_loader` into the
frozen `GateConfig` passed in here. gates.py holds NO thresholds of its
own, so policy cannot drift between the file and the code.

THREE STRUCTURAL RULES, each an invariant from the master context:

  * PRIMARY and SECONDARY are evaluated by SEPARATE functions over the same
    draft. Failing PRIMARY does not demote to SECONDARY (invariant 5);
    `evaluate` runs the secondary walk from scratch and hands it none of the
    primary walk's conclusions.
  * A per-company draft is never given MACRO_CONTEXT (invariant 6). Macro is
    a mechanism-level statement and may never carry a company list, so a
    company that would only qualify as macro is REJECTED with that reason.
  * Below the sign-consistency floor a company publishes as MIXED or
    UNCERTAIN, never as a direction (invariants 8 and 9).

Every rule evaluated -- passed or failed -- is recorded in `gate_trace`.
"""
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

TIER_PRIMARY = "PRIMARY"
TIER_SECONDARY_RIPPLE = "SECONDARY_RIPPLE"
TIER_REJECTED = "REJECTED"

# Ordered least-worst first, so "at least MAJOR" is a comparison.
_SEVERITY_ORDER = ("WARN", "MAJOR", "BLOCKING")


@dataclass(frozen=True)
class TierPolicy:
    max_graph_distance: int
    materiality_buckets: tuple[str, ...]
    evidence_grades: tuple[str, ...]
    min_sign_consistency: float
    allowed_directness: tuple[str, ...] = ()
    directness_at_d1: tuple[str, ...] = ()
    medium_materiality_evidence_grades: tuple[str, ...] = ()
    low_materiality_evidence_grades: tuple[str, ...] = ()
    forbidden_weakest_link_statuses: tuple[str, ...] = ()
    allowed_empirical_status: tuple[str, ...] = ()
    max_objection_severity_sustained: str = "WARN"
    required_verifier_status: str | None = None
    min_adv_inr: float | None = None
    allowed_event_status: tuple[str, ...] = ()
    below_floor_allowed_effects: tuple[str, ...] = ()
    require_mechanism_id: bool = False
    unknown_verifier_status_passes: bool = True
    unknown_empirical_status_passes: bool = True
    unknown_liquidity_passes: bool = True
    unknown_event_status_passes: bool = True


@dataclass(frozen=True)
class HardBlockPolicy:
    required_entity_status: str
    min_shock_magnitude_confidence: float
    no_impact_buckets: tuple[str, ...]


@dataclass(frozen=True)
class GateConfig:
    version: str
    hard_blocks: HardBlockPolicy
    primary: TierPolicy
    secondary: TierPolicy


@dataclass(frozen=True)
class ImpactDraft:
    """Everything the gate evaluates, resolved by the reducer. The gate
    never looks anything up -- that is what keeps it pure and testable.

    `None` on an input means NOT KNOWN (never "zero", never "fine"). Each
    tier policy states explicitly what an unknown means for that tier, so a
    missing Phase 1-5 input can never become a silent pass.
    """
    entity_status: str
    entity_ambiguous: bool
    exposure_stale: bool
    materiality_bucket: str
    graph_distance: int | None
    directness: str | None
    evidence_grade: str | None
    weakest_link: str | None            # "claim_type:BINDING_STATUS" or None
    sign_consistency: float
    empirical_status: str | None
    objections: tuple[Mapping[str, Any], ...]
    unbound_claim_ids: tuple[str, ...]
    verifier_status: str | None
    adv_20d_inr: float | None
    event_status: str | None
    shock_magnitude_confidence: float | None
    mechanism_id: str | None
    net_effect: str


@dataclass(frozen=True)
class GateRule:
    name: str
    passed: bool
    detail: str = ""
    tier: str = ""          # "HARD" | "PRIMARY" | "SECONDARY"


@dataclass(frozen=True)
class GateResult:
    tier: str | None
    rejection_reason: str | None
    gate_trace: tuple[GateRule, ...] = field(default_factory=tuple)


def _sustained_at_least(objections: Sequence[Mapping], severity: str) -> bool:
    floor = _SEVERITY_ORDER.index(severity)
    return any(
        bool(o.get("sustained"))
        and _SEVERITY_ORDER.index(str(o.get("severity", "WARN"))) >= floor
        for o in objections)


def _next_severity(max_allowed: str) -> str:
    """'no sustained objection of severity >= MAJOR', expressed from a config
    that names the worst severity still TOLERATED."""
    index = _SEVERITY_ORDER.index(max_allowed)
    return _SEVERITY_ORDER[min(index + 1, len(_SEVERITY_ORDER) - 1)]


# --- hard blocks -----------------------------------------------------------

def evaluate_hard_blocks(draft: ImpactDraft, config: GateConfig) -> GateResult:
    """§7.4's HARD BLOCKS, in order; the first failure decides. Returns a
    result whose `tier` is None when nothing blocks (i.e. "carry on"), never
    a tier of its own."""
    policy = config.hard_blocks
    checks = (
        ("entity_ambiguous", draft.entity_ambiguous, "ENTITY_AMBIGUOUS", ""),
        ("entity_status", draft.entity_status != policy.required_entity_status,
         "ENTITY_NOT_ACTIVE", str(draft.entity_status)),
        ("exposure_freshness", draft.exposure_stale, "EXPOSURE_STALE", ""),
        ("materiality_present",
         draft.materiality_bucket in policy.no_impact_buckets,
         "NO_MATERIAL_IMPACT", str(draft.materiality_bucket)),
        ("sustained_blocking_objection",
         _sustained_at_least(draft.objections, "BLOCKING"),
         "SUSTAINED_BLOCKING_OBJECTION", ""),
        ("unbound_claims", bool(draft.unbound_claim_ids), "UNBOUND_CLAIM",
         ",".join(draft.unbound_claim_ids)),
        # A shock we cannot size is a MACRO_CONTEXT statement at best, and
        # macro may never carry a company (invariant 6) -- so for a company
        # draft this is a REJECT, not a demotion.
        ("shock_magnitude_confidence",
         draft.shock_magnitude_confidence is not None
         and draft.shock_magnitude_confidence < policy.min_shock_magnitude_confidence,
         "MACRO_CONTEXT_HAS_NO_COMPANIES", str(draft.shock_magnitude_confidence)),
    )

    trace: list[GateRule] = []
    for name, blocked, reason, detail in checks:
        trace.append(GateRule(name, not blocked, detail, tier="HARD"))
        if blocked:
            return GateResult(TIER_REJECTED, reason, tuple(trace))
    return GateResult(None, None, tuple(trace))


# --- tier walks ------------------------------------------------------------

def _directness_rule(draft: ImpactDraft, policy: TierPolicy) -> GateRule:
    """§7.4 PRIMARY: `directness == DIRECT (d1)` or
    `(DIRECT|INDIRECT at d2 with materiality == HIGH)`. Distance and
    directness are SEPARATE inputs here -- neither is derived from the
    other (invariant 4)."""
    distance = draft.graph_distance
    if distance == 1:
        allowed = draft.directness in policy.directness_at_d1
    elif distance == 2:
        allowed = (draft.directness in policy.allowed_directness
                   and draft.materiality_bucket == "HIGH")
    else:
        allowed = False
    return GateRule("directness", allowed,
                    f"{draft.directness}@d{distance}/{draft.materiality_bucket}")


def _tier_rules(draft: ImpactDraft, policy: TierPolicy, tier: str) -> list[GateRule]:
    rules: list[GateRule] = [GateRule(
        "graph_distance",
        draft.graph_distance is not None
        and draft.graph_distance <= policy.max_graph_distance,
        f"d={draft.graph_distance} max={policy.max_graph_distance}")]

    if policy.allowed_directness:
        rules.append(_directness_rule(draft, policy))

    materiality_ok = draft.materiality_bucket in policy.materiality_buckets
    if not materiality_ok and draft.materiality_bucket == "MEDIUM":
        materiality_ok = draft.evidence_grade in policy.medium_materiality_evidence_grades
    if not materiality_ok and draft.materiality_bucket == "LOW":
        materiality_ok = draft.evidence_grade in policy.low_materiality_evidence_grades
    rules.append(GateRule("materiality", materiality_ok,
                          f"{draft.materiality_bucket}/{draft.evidence_grade}"))

    rules.append(GateRule("evidence_grade",
                          draft.evidence_grade in policy.evidence_grades,
                          str(draft.evidence_grade)))

    if policy.forbidden_weakest_link_statuses:
        status = (draft.weakest_link or "").rsplit(":", 1)[-1]
        rules.append(GateRule(
            "weakest_link",
            status not in policy.forbidden_weakest_link_statuses,
            str(draft.weakest_link)))

    # Below the floor a DIRECTIONAL claim fails; MIXED / UNCERTAIN are the
    # honest publications and pass when the policy allows them (invariants
    # 8 and 9).
    consistent = draft.sign_consistency >= policy.min_sign_consistency
    if not consistent and draft.net_effect in policy.below_floor_allowed_effects:
        consistent = True
    rules.append(GateRule(
        "sign_consistency", consistent,
        f"{draft.sign_consistency} floor={policy.min_sign_consistency} "
        f"net={draft.net_effect}"))

    if policy.allowed_empirical_status:
        empirical_ok = (policy.unknown_empirical_status_passes
                        if draft.empirical_status is None
                        else draft.empirical_status in policy.allowed_empirical_status)
        rules.append(GateRule("empirical", empirical_ok, str(draft.empirical_status)))

    rules.append(GateRule(
        "objections",
        not _sustained_at_least(
            draft.objections, _next_severity(policy.max_objection_severity_sustained)),
        f"max_sustained={policy.max_objection_severity_sustained}"))

    if policy.required_verifier_status is not None:
        verifier_ok = (policy.unknown_verifier_status_passes
                       if draft.verifier_status is None
                       else draft.verifier_status == policy.required_verifier_status)
        rules.append(GateRule("verifier", verifier_ok, str(draft.verifier_status)))

    if policy.min_adv_inr is not None:
        liquidity_ok = (policy.unknown_liquidity_passes
                        if draft.adv_20d_inr is None
                        else draft.adv_20d_inr >= policy.min_adv_inr)
        rules.append(GateRule("liquidity", liquidity_ok, str(draft.adv_20d_inr)))

    if policy.allowed_event_status:
        event_ok = (policy.unknown_event_status_passes
                    if draft.event_status is None
                    else draft.event_status in policy.allowed_event_status)
        rules.append(GateRule("event_status", event_ok, str(draft.event_status)))

    if policy.require_mechanism_id:            # invariant 7
        rules.append(GateRule("mechanism_id", bool(draft.mechanism_id),
                              str(draft.mechanism_id)))

    return [GateRule(r.name, r.passed, r.detail, tier=tier) for r in rules]


def _first_failure_reason(rules: Sequence[GateRule], tier: str) -> str | None:
    for rule in rules:
        if rule.passed:
            continue
        if rule.name == "mechanism_id":
            return "SECONDARY_REQUIRES_MECHANISM"
        if rule.name == "sign_consistency":
            return "SIGN_CONSISTENCY_BELOW_FLOOR"
        return f"{tier}_FAILED_{rule.name.upper()}"
    return None


def evaluate_primary(draft: ImpactDraft, config: GateConfig) -> GateResult:
    """The PRIMARY walk, on its own. A failure here names NO tier -- it is
    not an instruction to publish anything else."""
    rules = _tier_rules(draft, config.primary, "PRIMARY")
    if all(rule.passed for rule in rules):
        return GateResult(TIER_PRIMARY, None, tuple(rules))
    return GateResult(None, _first_failure_reason(rules, "PRIMARY"), tuple(rules))


def evaluate_secondary(draft: ImpactDraft, config: GateConfig) -> GateResult:
    """The SECONDARY_RIPPLE walk, evaluated INDEPENDENTLY over the same
    draft (invariant 5). It shares no state with the primary walk."""
    rules = _tier_rules(draft, config.secondary, "SECONDARY")
    if all(rule.passed for rule in rules):
        return GateResult(TIER_SECONDARY_RIPPLE, None, tuple(rules))
    return GateResult(None, _first_failure_reason(rules, "SECONDARY"), tuple(rules))


def evaluate(draft: ImpactDraft, config: GateConfig) -> GateResult:
    """Hard blocks, then the two independent tier walks, then REJECTED."""
    hard = evaluate_hard_blocks(draft, config)
    if hard.tier == TIER_REJECTED:
        return hard

    primary = evaluate_primary(draft, config)
    secondary = evaluate_secondary(draft, config)
    trace = hard.gate_trace + primary.gate_trace + secondary.gate_trace

    if primary.tier is not None:
        return GateResult(TIER_PRIMARY, None, trace)
    if secondary.tier is not None:
        return GateResult(TIER_SECONDARY_RIPPLE, None, trace)
    # Rejected. The reason names the SECONDARY failure: it is the weaker bar,
    # so it is the one that explains why nothing publishes at all.
    return GateResult(TIER_REJECTED, secondary.rejection_reason, trace)
