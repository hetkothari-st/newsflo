"""Company publication gate (spec 2026-08-12 §5/§13/§15, INV-002..006,
INV-012/013): every candidate walks the same deterministic state machine,
publication fails closed, and every rejection carries a machine-readable
reason. The gate is a pure function -- discovery breadth stays internal,
the gate alone decides display."""
import pytest

from app.analysis.impact_graph.publication_gate import (
    CandidateInput,
    evaluate_candidate,
)


def _candidate(**overrides):
    payload = dict(
        ticker="ONGC.NS",
        entity_resolved=True,
        mechanism="crude realization: higher crude price lifts upstream revenue per barrel",
        rationale="upstream producer with unhedged crude realization exposure",
        economic_effect="positive",
        causal_distance=1,
        materiality=0.7,
        confidence=0.8,
        independently_verified=True,
        verification_available=True,
        evidence_class="VERIFIED_RELATIONSHIP",
        positive_channels=["crude realization"],
        negative_channels=[],
        net_direction="bullish",
        trigger_shock_present=True,
    )
    payload.update(overrides)
    return CandidateInput(**payload)


# --- happy path -----------------------------------------------------------

def test_strong_direct_candidate_is_primary():
    decision = evaluate_candidate(_candidate())
    assert decision.final_state == "DISPLAY_ELIGIBLE"
    assert decision.display_tier == "primary"
    assert decision.rejection_reason is None
    assert "MATERIALITY_VALID" in decision.gates_passed
    assert "VERIFIED" in decision.gates_passed


def test_mixed_effect_is_valid_for_primary():
    """Spec §19/§42: MIXED is a real result, never forced binary."""
    decision = evaluate_candidate(_candidate(
        economic_effect="mixed", net_direction="mixed",
        positive_channels=["upstream realization"],
        negative_channels=["refining margin squeeze"],
    ))
    assert decision.final_state == "DISPLAY_ELIGIBLE"
    assert decision.display_tier == "primary"


# --- hard rejections (excluded, machine-readable reason) ------------------

def test_unresolved_entity_rejected():
    decision = evaluate_candidate(_candidate(entity_resolved=False))
    assert decision.final_state == "REJECT_UNKNOWN_COMPANY"
    assert decision.display_tier == "excluded"


def test_empty_mechanism_rejected():
    decision = evaluate_candidate(_candidate(mechanism=""))
    assert decision.final_state == "REJECT_WEAK_MECHANISM"
    assert decision.display_tier == "excluded"


def test_generic_sector_rationale_rejected_without_specific_evidence():
    """Spec §6/§28: 'same sector' arguments cannot authorize publication
    when the evidence class is model inference only."""
    decision = evaluate_candidate(_candidate(
        rationale="large company in the same sector as the affected industry",
        evidence_class="MODEL_INFERENCE",
    ))
    assert decision.final_state == "REJECT_GENERIC_EXPOSURE"
    assert decision.display_tier == "excluded"


def test_generic_rationale_tolerated_with_verified_relationship():
    """A verified company-specific relationship outweighs sloppy prose."""
    decision = evaluate_candidate(_candidate(
        rationale="major player in the sector",
        evidence_class="VERIFIED_RELATIONSHIP",
    ))
    assert decision.final_state == "DISPLAY_ELIGIBLE"


def test_missing_trigger_shock_rejected_as_not_event_specific():
    """Spec §14 counterfactual proxy: no traceable event shock -> the story
    is a generic macro narrative, not this event's impact."""
    decision = evaluate_candidate(_candidate(trigger_shock_present=False))
    assert decision.final_state == "REJECT_NOT_EVENT_SPECIFIC"
    assert decision.display_tier == "excluded"


def test_neutral_effect_not_displayed():
    """NO_MATERIAL_IMPACT never renders (spec §19)."""
    decision = evaluate_candidate(_candidate(
        economic_effect="no_material_impact", net_direction="neutral"))
    assert decision.final_state == "REJECT_NO_MATERIAL_IMPACT"
    assert decision.display_tier == "excluded"


def test_legacy_neutral_alias_normalizes_to_no_material_impact_before_gate():
    """"neutral" is a legacy/compat alias (corrective plan task 2) accepted
    at parse boundaries and mapped to "no_material_impact" -- a candidate
    built from a normalize_effect()-passed value must reject the same way
    a directly no_material_impact candidate does."""
    from app.analysis.impact_graph.schemas import normalize_effect

    decision = evaluate_candidate(_candidate(
        economic_effect=normalize_effect("neutral"), net_direction="neutral"))
    assert decision.final_state == "REJECT_NO_MATERIAL_IMPACT"
    assert decision.display_tier == "excluded"


def test_uncertain_effect_never_primary():
    """Spec §19 + INV-012: UNCERTAIN cannot appear as a primary result."""
    decision = evaluate_candidate(_candidate(
        economic_effect="uncertain", net_direction="uncertain"))
    assert decision.display_tier != "primary"


def test_unverified_candidate_cannot_display():
    """INV-005: verification failure cannot authorize display."""
    decision = evaluate_candidate(_candidate(independently_verified=False))
    assert decision.final_state == "REJECT_UNVERIFIED"
    assert decision.display_tier == "excluded"


def test_validator_unavailable_fails_closed():
    """Spec §5: a candidate must not become display-eligible when a
    required gate could not be evaluated (budget exhaustion, router down)."""
    decision = evaluate_candidate(_candidate(
        independently_verified=False, verification_available=False))
    assert decision.final_state == "REJECT_VALIDATOR_UNAVAILABLE"
    assert decision.display_tier == "excluded"


def test_contradictory_net_and_effect_rejected():
    """economic_effect and net_direction disagreeing is a data integrity
    failure, not a presentational nuance."""
    decision = evaluate_candidate(_candidate(
        economic_effect="positive", net_direction="bearish"))
    assert decision.final_state == "REJECT_CONTRADICTORY"
    assert decision.display_tier == "excluded"


# --- materiality grades (spec §15) ----------------------------------------

def test_unknown_materiality_excluded():
    decision = evaluate_candidate(_candidate(materiality=None))
    assert decision.final_state == "REJECT_LOW_MATERIALITY"
    assert decision.materiality_grade == "UNKNOWN"
    assert decision.display_tier == "excluded"


def test_low_materiality_demoted_to_secondary():
    """Technically exposed but immaterial (spec test #8, Blue Dart class):
    a defensible-but-thin candidate may survive as secondary, never
    primary."""
    decision = evaluate_candidate(_candidate(materiality=0.2))
    assert decision.materiality_grade == "LOW"
    assert decision.display_tier == "secondary"


# --- causal distance policy (spec §13, INV-013) ---------------------------

def test_distance_two_primary_requires_strong_evidence_and_materiality():
    ok = evaluate_candidate(_candidate(
        causal_distance=2, materiality=0.7,
        evidence_class="VERIFIED_RELATIONSHIP"))
    assert ok.display_tier == "primary"

    weak_evidence = evaluate_candidate(_candidate(
        causal_distance=2, materiality=0.7,
        evidence_class="CURATED_ARCHETYPE"))
    assert weak_evidence.display_tier == "secondary"

    weak_materiality = evaluate_candidate(_candidate(
        causal_distance=2, materiality=0.4,
        evidence_class="VERIFIED_RELATIONSHIP"))
    assert weak_materiality.display_tier == "secondary"


def test_distance_three_never_primary():
    decision = evaluate_candidate(_candidate(
        causal_distance=3, materiality=0.9,
        evidence_class="VERIFIED_RELATIONSHIP"))
    assert decision.display_tier == "secondary"


def test_distance_four_excluded():
    decision = evaluate_candidate(_candidate(causal_distance=4))
    assert decision.final_state == "REJECT_TOO_DISTANT"
    assert decision.display_tier == "excluded"


# --- evidence hierarchy (spec §8/§9/§10, INV-003/004) ---------------------

def test_model_inference_alone_never_primary():
    """Tier E cannot independently authorize a primary company."""
    decision = evaluate_candidate(_candidate(evidence_class="MODEL_INFERENCE"))
    assert decision.display_tier == "secondary"


def test_article_market_observation_never_authorizes():
    """INV-003 / spec test #7: 'the stock fell 3%' is a market observation,
    not fundamental evidence -- an article-mentioned loser must not become
    a fundamental casualty on that basis."""
    decision = evaluate_candidate(_candidate(
        evidence_class="ARTICLE_MARKET_OBSERVATION"))
    assert decision.display_tier != "primary"


def test_curated_archetype_primary_only_with_high_materiality():
    """INV-004: archetype membership alone cannot authorize; verified +
    HIGH materiality is the minimum for a Tier-D-evidenced primary row."""
    high = evaluate_candidate(_candidate(
        evidence_class="CURATED_ARCHETYPE", materiality=0.7))
    assert high.display_tier == "primary"

    medium = evaluate_candidate(_candidate(
        evidence_class="CURATED_ARCHETYPE", materiality=0.45))
    assert medium.display_tier == "secondary"


def test_article_subject_with_direct_facts_is_primary_capable():
    decision = evaluate_candidate(_candidate(evidence_class="ARTICLE_SUBJECT"))
    assert decision.display_tier == "primary"


# --- audit trail ----------------------------------------------------------

def test_every_rejection_reason_is_machine_readable():
    """INV-020: rejection states come from the closed vocabulary."""
    from app.analysis.impact_graph.publication_gate import REJECTION_STATES
    decision = evaluate_candidate(_candidate(entity_resolved=False))
    assert decision.final_state in REJECTION_STATES


def test_gates_passed_records_progress_until_failure():
    decision = evaluate_candidate(_candidate(materiality=None))
    assert "ENTITY_VALID" in decision.gates_passed
    assert "MECHANISM_VALID" in decision.gates_passed
    assert "MATERIALITY_VALID" not in decision.gates_passed
