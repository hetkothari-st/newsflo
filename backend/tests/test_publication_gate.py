"""Company publication gate (spec 2026-08-12 §5/§13/§15, corrective-v4
Task 4, INV-002..006, INV-012/013): every candidate walks the same ordered
state machine, publication fails closed, and every rejection carries a
machine-readable reason from a closed vocabulary in which NO state is dead.

The gate is a pure function -- discovery breadth stays internal, the gate
alone decides display."""
import pytest

from app.analysis.impact_graph.publication_gate import (
    GATE_SEQUENCE,
    REJECTION_STATES,
    CandidateInput,
    GateContext,
    GateDecision,
    evaluate_candidate,
    finalize_alert_decisions,
    materiality_grade,
)
from app.config import settings


def _candidate(**overrides):
    """A strong, fully-grounded d1 candidate: every gate green, primary."""
    payload = dict(
        ticker="ONGC.NS",
        entity_status="resolved",
        company_profile_present=True,
        mechanism="crude realization: higher crude price lifts upstream revenue per barrel",
        rationale="upstream producer with unhedged crude realization exposure",
        economic_effect="positive",
        causal_distance=1,
        materiality=0.7,
        confidence=0.8,
        independently_verified=True,
        verification_available=True,
        evidence_class="VERIFIED_RELATIONSHIP",
        evidence_tier="C",
        counterfactual="SUPPORTED",
        analysis_quality="authoritative",
        positive_channels=["crude realization"],
        negative_channels=[],
        net_direction="bullish",
        trigger_shock_present=True,
    )
    payload.update(overrides)
    return CandidateInput(**payload)


def _ctx(**overrides):
    return GateContext(**overrides)


def _ok_decision(ticker, mat=0.7, conf=0.8, tier="primary"):
    return GateDecision(
        final_state="DISPLAY_ELIGIBLE", display_tier=tier, gates_passed=list(),
        rejection_reason=None, materiality_grade=materiality_grade(mat),
        ticker=ticker, materiality=mat, confidence=conf,
    )


# --- the sequence is the machine ------------------------------------------

def test_gate_sequence_is_executable_not_decorative():
    """INV-006 by construction: GATE_SEQUENCE is the execution order, so a
    fully-passing candidate's trail is exactly the declared sequence."""
    decision = evaluate_candidate(_candidate(), _ctx())
    assert decision.final_state == "DISPLAY_ELIGIBLE"
    assert decision.gates_passed == [name for name, _ in GATE_SEQUENCE]


def test_gate_sequence_entries_are_callables_in_declared_order():
    assert [name for name, _ in GATE_SEQUENCE] == [
        "ENTITY_VALID", "DUPLICATE_FREE", "BUSINESS_MODEL_VALID",
        "MECHANISM_VALID", "COMPANY_SPECIFIC_EXPOSURE_VALID",
        "EVENT_APPLICABILITY_VALID", "CAUSAL_PATH_VALID", "MATERIALITY_VALID",
        "EVIDENCE_VALID", "CONTRADICTION_FREE", "COUNTERFACTUAL_VALID",
        "QUALITY_VALID", "VERIFIED",
    ]
    assert all(callable(check) for _, check in GATE_SEQUENCE)


def test_gates_passed_records_progress_until_failure():
    decision = evaluate_candidate(_candidate(materiality=None), _ctx())
    assert "ENTITY_VALID" in decision.gates_passed
    assert "MECHANISM_VALID" in decision.gates_passed
    assert "MATERIALITY_VALID" not in decision.gates_passed


# --- happy path -----------------------------------------------------------

def test_strong_direct_candidate_is_primary():
    decision = evaluate_candidate(_candidate(), _ctx())
    assert decision.final_state == "DISPLAY_ELIGIBLE"
    assert decision.display_tier == "primary"
    assert decision.rejection_reason is None
    assert decision.notes is None


def test_mixed_effect_is_valid_for_primary():
    """Spec §19/§42: MIXED is a real result, never forced binary."""
    decision = evaluate_candidate(_candidate(
        economic_effect="mixed", net_direction="mixed",
        positive_channels=["upstream realization"],
        negative_channels=["refining margin squeeze"],
    ), _ctx())
    assert decision.final_state == "DISPLAY_ELIGIBLE"
    assert decision.display_tier == "primary"


def test_medium_materiality_d1_strong_evidence_is_primary():
    decision = evaluate_candidate(_candidate(materiality=0.45), _ctx())
    assert decision.materiality_grade == "MEDIUM"
    assert decision.display_tier == "primary"


# --- entity ---------------------------------------------------------------

def test_unresolved_entity_rejected():
    decision = evaluate_candidate(_candidate(entity_status="unresolved"), _ctx())
    assert decision.final_state == "REJECT_UNKNOWN_COMPANY"
    assert decision.display_tier == "excluded"


def test_ambiguous_entity_rejected():
    """An ambiguous name is not a resolved company: two different states so
    the postmortem can tell "no such ticker" from "which one?"."""
    decision = evaluate_candidate(_candidate(entity_status="ambiguous"), _ctx())
    assert decision.final_state == "REJECT_ENTITY_AMBIGUOUS"
    assert decision.display_tier == "excluded"


def test_duplicate_ticker_in_context_rejected():
    decision = evaluate_candidate(
        _candidate(), _ctx(seen_tickers=frozenset({"ONGC.NS"})))
    assert decision.final_state == "REJECT_DUPLICATE"


# --- business model / mechanism -------------------------------------------

def test_no_company_profile_and_weak_evidence_is_insufficient():
    """Canonical table: no business description AND no exposure record means
    only structured primary evidence (tier A/B) can carry the claim."""
    decision = evaluate_candidate(
        _candidate(company_profile_present=False), _ctx())
    assert decision.final_state == "REJECT_INSUFFICIENT_EVIDENCE"
    assert "BUSINESS_MODEL_VALID" not in decision.gates_passed


def test_no_company_profile_survives_on_structured_evidence():
    decision = evaluate_candidate(
        _candidate(company_profile_present=False, evidence_tier="A"), _ctx())
    assert decision.final_state == "DISPLAY_ELIGIBLE"


def test_empty_mechanism_rejected():
    decision = evaluate_candidate(_candidate(mechanism=""), _ctx())
    assert decision.final_state == "REJECT_WEAK_MECHANISM"
    assert decision.display_tier == "excluded"


# --- company-specific exposure --------------------------------------------

def test_generic_sector_rationale_rejected_at_tier_e():
    """Spec §6/§28: 'same sector' arguments cannot authorize publication
    when the evidence is model inference only."""
    decision = evaluate_candidate(_candidate(
        rationale="large company in the same sector as the affected industry",
        evidence_class="MODEL_INFERENCE", evidence_tier="E",
    ), _ctx())
    assert decision.final_state == "REJECT_GENERIC_EXPOSURE"


def test_generic_sector_rationale_rejected_at_tier_d():
    """Policy change (corrective-v4): tier D no longer buys a pass on
    interchangeable sector prose -- only tier A/B/C/SUBJECT does."""
    decision = evaluate_candidate(_candidate(
        rationale="major player in the sector as a whole",
        evidence_class="CURATED_ARCHETYPE", evidence_tier="D",
    ), _ctx())
    assert decision.final_state == "REJECT_GENERIC_EXPOSURE"


def test_generic_rationale_tolerated_with_verified_relationship():
    """A verified company-specific relationship outweighs sloppy prose."""
    decision = evaluate_candidate(_candidate(
        rationale="major player in the sector",
        evidence_class="VERIFIED_RELATIONSHIP", evidence_tier="C",
    ), _ctx())
    assert decision.final_state == "DISPLAY_ELIGIBLE"


# --- event applicability / counterfactual ---------------------------------

def test_missing_trigger_shock_rejected_as_not_event_specific():
    """Spec §14 structural proxy: no traceable event shock -> the story is a
    generic macro narrative, not this event's impact."""
    decision = evaluate_candidate(_candidate(trigger_shock_present=False), _ctx())
    assert decision.final_state == "REJECT_NOT_EVENT_SPECIFIC"


def test_counterfactual_not_supported_rejects():
    decision = evaluate_candidate(
        _candidate(counterfactual="NOT_SUPPORTED"), _ctx())
    assert decision.final_state == "REJECT_NOT_EVENT_SPECIFIC"
    assert decision.display_tier == "excluded"


def test_counterfactual_unknown_verdict_fails_closed():
    decision = evaluate_candidate(_candidate(counterfactual=""), _ctx())
    assert decision.final_state == "REJECT_NOT_EVENT_SPECIFIC"


def test_counterfactual_uncertain_blocks_primary():
    decision = evaluate_candidate(_candidate(counterfactual="UNCERTAIN"), _ctx())
    assert decision.final_state == "DISPLAY_ELIGIBLE"
    assert decision.display_tier != "primary"
    assert decision.display_tier == "secondary_deep_dive"


# --- causal distance ------------------------------------------------------

def test_distance_two_primary_requires_strong_evidence_and_materiality():
    ok = evaluate_candidate(_candidate(
        causal_distance=2, materiality=0.7, evidence_tier="C"), _ctx())
    assert ok.display_tier == "primary"

    weak_evidence = evaluate_candidate(_candidate(
        causal_distance=2, materiality=0.7,
        evidence_class="CURATED_ARCHETYPE", evidence_tier="D"), _ctx())
    assert weak_evidence.display_tier == "secondary_deep_dive"

    weak_materiality = evaluate_candidate(_candidate(
        causal_distance=2, materiality=0.4, evidence_tier="C"), _ctx())
    assert weak_materiality.display_tier == "secondary_deep_dive"


def test_distance_three_with_strong_evidence_is_deep_dive():
    decision = evaluate_candidate(_candidate(
        causal_distance=3, materiality=0.9, evidence_tier="C"), _ctx())
    assert decision.final_state == "DISPLAY_ELIGIBLE"
    assert decision.display_tier == "secondary_deep_dive"


def test_d3_without_strong_evidence_is_low_priority_reject():
    decision = evaluate_candidate(_candidate(
        causal_distance=3, evidence_class="CURATED_ARCHETYPE",
        evidence_tier="D"), _ctx())
    assert decision.final_state == "REJECT_LOW_PRIORITY"


def test_d3_without_high_materiality_is_low_priority_reject():
    decision = evaluate_candidate(_candidate(
        causal_distance=3, materiality=0.45, evidence_tier="C"), _ctx())
    assert decision.final_state == "REJECT_LOW_PRIORITY"


def test_distance_four_excluded():
    decision = evaluate_candidate(_candidate(causal_distance=4), _ctx())
    assert decision.final_state == "REJECT_TOO_DISTANT"


# --- materiality (spec §15) -----------------------------------------------

def test_unknown_materiality_excluded():
    decision = evaluate_candidate(_candidate(materiality=None), _ctx())
    assert decision.final_state == "REJECT_LOW_MATERIALITY"
    assert decision.materiality_grade == "UNKNOWN"
    assert decision.display_tier == "excluded"


def test_low_materiality_rejected_by_default_config():
    """Policy change (corrective-v4): technically-exposed-but-immaterial is
    excluded, not quietly published as secondary."""
    decision = evaluate_candidate(_candidate(materiality=0.2), _ctx())
    assert decision.final_state == "REJECT_LOW_MATERIALITY"
    assert decision.materiality_grade == "LOW"
    assert decision.display_tier == "excluded"


def test_low_materiality_deep_dive_only_with_explicit_policy(monkeypatch):
    monkeypatch.setattr(settings, "impact_allow_low_materiality_deep_dive", True)
    decision = evaluate_candidate(_candidate(materiality=0.2), _ctx())
    assert decision.final_state == "DISPLAY_ELIGIBLE"
    assert decision.display_tier == "secondary_deep_dive"


def test_no_material_impact_never_displayed():
    """NO_MATERIAL_IMPACT never renders (spec §19)."""
    decision = evaluate_candidate(_candidate(
        economic_effect="no_material_impact", net_direction="neutral"), _ctx())
    assert decision.final_state == "REJECT_NO_MATERIAL_IMPACT"


def test_legacy_neutral_alias_normalizes_to_no_material_impact_before_gate():
    """'neutral' is a legacy/compat alias (corrective plan task 2) accepted
    at parse boundaries and mapped to 'no_material_impact' -- a candidate
    built from a normalize_effect()-passed value must reject the same way a
    directly no_material_impact candidate does."""
    from app.analysis.impact_graph.schemas import normalize_effect

    decision = evaluate_candidate(_candidate(
        economic_effect=normalize_effect("neutral"), net_direction="neutral"), _ctx())
    assert decision.final_state == "REJECT_NO_MATERIAL_IMPACT"


# --- evidence hierarchy (spec §8/§9/§10, INV-003/004) ---------------------

def test_model_inference_alone_is_insufficient_evidence():
    """Policy change (corrective-v4): tier E no longer buys a secondary
    slot -- model inference alone authorizes nothing."""
    decision = evaluate_candidate(_candidate(
        evidence_class="MODEL_INFERENCE", evidence_tier="E"), _ctx())
    assert decision.final_state == "REJECT_INSUFFICIENT_EVIDENCE"
    assert decision.display_tier == "excluded"


def test_article_market_observation_never_authorizes():
    """INV-003 / spec test #7: 'the stock fell 3%' is a market observation,
    not fundamental evidence -- an article-mentioned loser must not become a
    fundamental casualty on that basis."""
    decision = evaluate_candidate(_candidate(
        evidence_class="ARTICLE_MARKET_OBSERVATION",
        evidence_tier="MARKET_OBS"), _ctx())
    assert decision.final_state == "REJECT_INSUFFICIENT_EVIDENCE"


def test_unknown_evidence_vocabulary_fails_closed():
    decision = evaluate_candidate(_candidate(
        evidence_class="VIBES", evidence_tier=""), _ctx())
    assert decision.final_state == "REJECT_INSUFFICIENT_EVIDENCE"


def test_curated_archetype_is_deep_dive_never_primary():
    """INV-004: archetype membership is a hint, never proof -- tier D can
    describe a company but cannot make it a primary claim."""
    high = evaluate_candidate(_candidate(
        evidence_class="CURATED_ARCHETYPE", evidence_tier="D",
        materiality=0.7), _ctx())
    assert high.final_state == "DISPLAY_ELIGIBLE"
    assert high.display_tier == "secondary_deep_dive"


def test_article_subject_with_direct_facts_is_primary_capable():
    decision = evaluate_candidate(_candidate(
        evidence_class="ARTICLE_SUBJECT", evidence_tier="SUBJECT"), _ctx())
    assert decision.display_tier == "primary"


def test_evidence_tier_derived_from_class_when_not_supplied():
    decision = evaluate_candidate(_candidate(
        evidence_class="MODEL_INFERENCE", evidence_tier=""), _ctx())
    assert decision.final_state == "REJECT_INSUFFICIENT_EVIDENCE"


# --- uncertain effect ------------------------------------------------------

def test_uncertain_effect_never_primary():
    """Spec §19 + INV-012: UNCERTAIN cannot appear as a primary result."""
    decision = evaluate_candidate(_candidate(
        economic_effect="uncertain", net_direction="uncertain"), _ctx())
    assert decision.final_state == "DISPLAY_ELIGIBLE"
    assert decision.display_tier == "secondary_deep_dive"


def test_uncertain_effect_with_weak_evidence_is_rejected():
    decision = evaluate_candidate(_candidate(
        economic_effect="uncertain", net_direction="uncertain",
        evidence_class="CURATED_ARCHETYPE", evidence_tier="D"), _ctx())
    assert decision.final_state == "REJECT_INSUFFICIENT_EVIDENCE"


def test_uncertain_effect_with_low_materiality_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "impact_allow_low_materiality_deep_dive", True)
    decision = evaluate_candidate(_candidate(
        economic_effect="uncertain", net_direction="uncertain",
        materiality=0.2), _ctx())
    assert decision.final_state == "REJECT_INSUFFICIENT_EVIDENCE"


# --- contradiction --------------------------------------------------------

def test_contradictory_net_and_effect_rejected():
    """economic_effect and net_direction disagreeing is a data integrity
    failure, not a presentational nuance."""
    decision = evaluate_candidate(_candidate(
        economic_effect="positive", net_direction="bearish"), _ctx())
    assert decision.final_state == "REJECT_CONTRADICTORY"


def test_unknown_economic_effect_rejected():
    decision = evaluate_candidate(_candidate(
        economic_effect="slightly_spicy", net_direction=""), _ctx())
    assert decision.final_state == "REJECT_CONTRADICTORY"


# --- analysis quality -----------------------------------------------------

def test_failed_quality_rejects():
    decision = evaluate_candidate(_candidate(analysis_quality="failed"), _ctx())
    assert decision.final_state == "REJECT_VALIDATOR_UNAVAILABLE"


def test_unknown_quality_fails_closed():
    decision = evaluate_candidate(_candidate(analysis_quality="whatever"), _ctx())
    assert decision.final_state == "REJECT_VALIDATOR_UNAVAILABLE"


def test_degraded_quality_never_primary():
    decision = evaluate_candidate(_candidate(analysis_quality="degraded"), _ctx())
    assert decision.final_state == "DISPLAY_ELIGIBLE"
    assert decision.display_tier != "primary"


def test_fallback_quality_primary_requires_owner_policy(monkeypatch):
    decision = evaluate_candidate(_candidate(analysis_quality="fallback"), _ctx())
    assert decision.display_tier != "primary"

    monkeypatch.setattr(settings, "impact_allow_fallback_primary", True)
    upgraded = evaluate_candidate(_candidate(analysis_quality="fallback"), _ctx())
    assert upgraded.display_tier == "primary"


# --- verification ---------------------------------------------------------

def test_unverified_candidate_cannot_display():
    """INV-005: verification failure cannot authorize display."""
    decision = evaluate_candidate(_candidate(independently_verified=False), _ctx())
    assert decision.final_state == "REJECT_UNVERIFIED"


def test_validator_unavailable_fails_closed():
    """Spec §5: a candidate must not become display-eligible when a required
    gate could not be evaluated (budget exhaustion, router down)."""
    decision = evaluate_candidate(_candidate(
        independently_verified=False, verification_available=False), _ctx())
    assert decision.final_state == "REJECT_VALIDATOR_UNAVAILABLE"


# --- alert-level finalization ---------------------------------------------

def test_duplicate_second_occurrence_rejected():
    decisions = finalize_alert_decisions([
        _ok_decision("X.NS", mat=0.7), _ok_decision("X.NS", mat=0.5)])
    assert [d.final_state for d in decisions] == ["DISPLAY_ELIGIBLE", "REJECT_DUPLICATE"]
    assert decisions[1].display_tier == "excluded"


def test_duplicate_keeps_higher_materiality_regardless_of_order():
    decisions = finalize_alert_decisions([
        _ok_decision("X.NS", mat=0.4), _ok_decision("X.NS", mat=0.9)])
    assert [d.final_state for d in decisions] == ["REJECT_DUPLICATE", "DISPLAY_ELIGIBLE"]


def test_duplicate_dedup_leaves_distinct_companies_alone():
    decisions = finalize_alert_decisions([
        _ok_decision("X.NS", mat=0.7), _ok_decision("Y.NS", mat=0.6)])
    assert all(d.final_state == "DISPLAY_ELIGIBLE" for d in decisions)


def test_primary_cap_overflow_demotes_deterministically():
    decisions = finalize_alert_decisions(
        [_ok_decision(f"T{i:02d}.NS", mat=0.9 - i * 0.01) for i in range(12)])
    assert sum(d.display_tier == "primary" for d in decisions) == 10
    assert all(d.display_tier == "secondary_deep_dive"
               for d in decisions if d.notes == "primary_cap_overflow")
    # The two weakest lost primary, nothing was deleted (INV-015).
    demoted = [d.ticker for d in decisions if d.notes == "primary_cap_overflow"]
    assert sorted(demoted) == ["T10.NS", "T11.NS"]
    assert len(decisions) == 12


def test_primary_cap_respects_config(monkeypatch):
    monkeypatch.setattr(settings, "impact_max_primary_companies", 2)
    decisions = finalize_alert_decisions(
        [_ok_decision(f"T{i}.NS", mat=0.9 - i * 0.05) for i in range(5)])
    assert sum(d.display_tier == "primary" for d in decisions) == 2


def test_primary_cap_does_not_promote_deep_dives():
    decisions = finalize_alert_decisions([
        _ok_decision("A.NS", mat=0.9),
        _ok_decision("B.NS", mat=0.8, tier="secondary_deep_dive")])
    assert [d.display_tier for d in decisions] == ["primary", "secondary_deep_dive"]
    assert decisions[1].notes is None


# --- audit trail / closed vocabulary --------------------------------------

def test_every_rejection_reason_is_machine_readable():
    """INV-020: rejection states come from the closed vocabulary."""
    decision = evaluate_candidate(_candidate(entity_status="unresolved"), _ctx())
    assert decision.final_state in REJECTION_STATES


# One candidate construction per rejection state. If a state cannot be
# produced, it is dead vocabulary and this suite says so by name.
_REACHABILITY_CASES = {
    "REJECT_ENTITY_AMBIGUOUS": dict(entity_status="ambiguous"),
    "REJECT_UNKNOWN_COMPANY": dict(entity_status="unresolved"),
    "REJECT_GENERIC_EXPOSURE": dict(
        rationale="large company in the same sector", evidence_tier="E"),
    "REJECT_WEAK_MECHANISM": dict(mechanism="short"),
    "REJECT_NOT_EVENT_SPECIFIC": dict(trigger_shock_present=False),
    "REJECT_TOO_DISTANT": dict(causal_distance=4),
    "REJECT_LOW_PRIORITY": dict(causal_distance=3, evidence_tier="D"),
    "REJECT_LOW_MATERIALITY": dict(materiality=0.1),
    "REJECT_NO_MATERIAL_IMPACT": dict(
        economic_effect="no_material_impact", net_direction="neutral"),
    "REJECT_INSUFFICIENT_EVIDENCE": dict(evidence_tier="E"),
    "REJECT_CONTRADICTORY": dict(economic_effect="positive", net_direction="bearish"),
    "REJECT_UNVERIFIED": dict(independently_verified=False),
    "REJECT_VALIDATOR_UNAVAILABLE": dict(analysis_quality="failed"),
    "REJECT_DUPLICATE": None,   # context-driven, not candidate-driven
}


@pytest.mark.parametrize("state", sorted(REJECTION_STATES))
def test_every_rejection_state_reachable(state):
    assert state in _REACHABILITY_CASES, f"no reachability case for {state}"
    overrides = _REACHABILITY_CASES[state]
    if state == "REJECT_DUPLICATE":
        decision = evaluate_candidate(
            _candidate(), _ctx(seen_tickers=frozenset({"ONGC.NS"})))
    else:
        decision = evaluate_candidate(_candidate(**overrides), _ctx())
    assert decision.final_state == state
    assert decision.display_tier == "excluded"
    assert decision.rejection_reason == state


def test_no_rejection_state_is_dead_vocabulary():
    assert set(_REACHABILITY_CASES) == set(REJECTION_STATES)


# --- purity ---------------------------------------------------------------

def test_gate_is_pure_and_context_free_by_default():
    """Calling twice with the same input yields the same decision, and a
    decision never mutates its candidate."""
    candidate = _candidate()
    first = evaluate_candidate(candidate, _ctx())
    second = evaluate_candidate(candidate, _ctx())
    assert first == second
