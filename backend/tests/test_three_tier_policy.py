"""Final blueprint §3/§4/§5/§6/§7/§11/§18: the publication gate grades into
THREE tiers, not two.

PRIMARY maximizes precision. SECONDARY_RIPPLE preserves governed analytical
breadth. MACRO_CONTEXT carries a validated d3 chain without pretending it is
a company-specific claim. And the symmetry that keeps the whole thing
honest: failing PRIMARY is not automatically REJECTED (§6), but clearing all
thirteen gates is not automatically PUBLISHED either.
"""
import pytest

from app.analysis.impact_graph.publication_gate import (
    CONFIDENCE_BANDS,
    DIRECTION_FROM_EFFECT,
    DISPLAYABLE_TIERS,
    ECONOMIC_EFFECTS,
    LEGACY_SECONDARY_SPELLINGS,
    NET_EFFECT_CONTRADICTION,
    POLICY_VERSION,
    TIER_DEEP_DIVE,
    TIER_MACRO_CONTEXT,
    TIER_SECONDARY_RIPPLE,
    CandidateInput,
    GateContext,
    confidence_band,
    derive_directness,
    evaluate_candidate,
    is_secondary_tier,
    validate_net_effect,
)
from app.config import settings


def _candidate(**overrides):
    """The same strong, fully-grounded d1 candidate test_publication_gate.py
    uses -- every gate green, primary by default."""
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
        causal_parent_type="economic_node",
        causal_parent_id="upstream_realization",
    )
    payload.update(overrides)
    return CandidateInput(**payload)


def _evaluate(**overrides):
    return evaluate_candidate(_candidate(**overrides), GateContext())


# --- vocabulary ------------------------------------------------------------

def test_policy_version_bumped_for_three_tier_grading():
    """A grading change can flip a cached decision's outcome, so the cache
    key must move with it -- an explicit invalidation, never a silent
    replay under the old rules."""
    assert POLICY_VERSION == "pol-2"


def test_tier_vocabulary_is_the_blueprint_vocabulary():
    assert TIER_SECONDARY_RIPPLE == "secondary_ripple"
    assert TIER_MACRO_CONTEXT == "macro_context"
    assert DISPLAYABLE_TIERS == ("primary", "secondary_ripple", "macro_context")
    # The deprecated alias must POINT AT the new spelling, not preserve the
    # old one: an untouched call site keeps compiling AND keeps writing one
    # value.
    assert TIER_DEEP_DIVE == TIER_SECONDARY_RIPPLE


@pytest.mark.parametrize("spelling", ("secondary_ripple",) + LEGACY_SECONDARY_SPELLINGS)
def test_is_secondary_tier_reads_every_legacy_spelling(spelling):
    """Persisted rows outlive renames. A consumer comparing against the
    current literal would silently stop seeing pre-migration rows."""
    assert is_secondary_tier(spelling) is True


@pytest.mark.parametrize("other", ["primary", "macro_context", "excluded", "", None])
def test_is_secondary_tier_rejects_everything_else(other):
    assert is_secondary_tier(other) is False


# --- tier grading ----------------------------------------------------------

def test_tier_d_direct_d1_lands_secondary_ripple_not_primary():
    """The blueprint's own ONGC example (§3): a relationship can be DIRECT
    at d1 and still cap at SECONDARY_RIPPLE because its EVIDENCE is curated
    domain knowledge, not a verified record. Directness, distance, evidence
    and tier are four separate dimensions (owner ruling R2)."""
    decision = _evaluate(evidence_class="CURATED_ARCHETYPE", evidence_tier="D",
                         materiality=0.75, economic_effect="positive",
                         counterfactual="SUPPORTED")
    assert decision.final_state == "DISPLAY_ELIGIBLE"
    assert decision.display_tier == "secondary_ripple"
    # ...and the registry, not the distance, is what says DIRECT.
    assert decision.causal_directness == "DIRECT"


def test_tier_c_d1_high_grade_reaches_primary():
    decision = _evaluate(evidence_class="VERIFIED_RELATIONSHIP", evidence_tier="C",
                         materiality=0.75, counterfactual="SUPPORTED")
    assert decision.display_tier == "primary"


def test_d3_with_evidence_lands_macro_context():
    """§7: a validated d3 chain is macro context, never a primary company
    claim -- and never silently deleted either."""
    decision = _evaluate(causal_distance=3, evidence_tier="C", materiality=0.9,
                         counterfactual="SUPPORTED")
    assert decision.final_state == "DISPLAY_ELIGIBLE"
    assert decision.display_tier == "macro_context"


def test_d2_relationship_evidence_high_materiality_is_primary():
    assert _evaluate(causal_distance=2, evidence_tier="C",
                     materiality=0.8).display_tier == "primary"


def test_d2_tier_d_is_ripple_not_rejected():
    """§6's critical rule: failing PRIMARY does NOT mean REJECTED. This is
    the paint/tyre/cement shape the first corrective pass lost (§1)."""
    decision = _evaluate(causal_distance=2, evidence_tier="D",
                         evidence_class="CURATED_ARCHETYPE",
                         economic_effect="negative", net_direction="bearish",
                         materiality=0.55)
    assert decision.final_state == "DISPLAY_ELIGIBLE"
    assert decision.display_tier == "secondary_ripple"


def test_tier_d_never_reaches_primary_at_any_distance_or_materiality():
    """Owner ruling R2 / INV-004: curated domain knowledge is a hint. No
    materiality float and no distance buys it a primary slot."""
    for distance in (1, 2):
        for materiality in (0.6, 0.95):
            decision = _evaluate(causal_distance=distance, evidence_tier="D",
                                 evidence_class="CURATED_ARCHETYPE",
                                 materiality=materiality)
            assert decision.display_tier != "primary", (distance, materiality)


def test_article_subject_is_primary_capable_only_at_d1():
    """SUBJECT is C-equivalent evidence ABOUT THE COMPANY, which is a d1
    statement. At d2 it says nothing about the transmission chain -- but it
    still supports a ripple row (breadth is not the thing being cut)."""
    assert _evaluate(evidence_tier="SUBJECT").display_tier == "primary"
    demoted = _evaluate(causal_distance=2, evidence_tier="SUBJECT", materiality=0.9)
    assert demoted.display_tier == "secondary_ripple"


def test_mixed_effect_with_direct_directness_is_a_legal_primary():
    """Nothing in the tier logic may assume DIRECT implies a single-signed
    effect: refiner_marketing_margin is a DIRECT d1 mechanism whose honest
    registry effect is `mixed` (crude is BOTH feedstock cost and realization
    driver). Forcing it binary is the failure mode, not the fix."""
    decision = _evaluate(
        economic_effect="mixed", net_direction="mixed",
        causal_parent_id="refiner_marketing_margin",
        positive_channels=["refining spread"],
        negative_channels=["marketing margin"])
    assert decision.causal_directness == "DIRECT"
    assert decision.display_tier == "primary"


# --- below-policy rejection ------------------------------------------------

def test_gates_passed_but_below_secondary_policy_is_recorded_rejection():
    """The symmetric half of §6: clearing all thirteen gates does not
    guarantee display. An `uncertain` net effect is valid enough to walk the
    whole machine and still has nothing displayable to say (§4: "unresolved
    evidence/contradiction -> UNCERTAIN / reject from display")."""
    decision = _evaluate(economic_effect="uncertain", net_direction="uncertain")
    assert decision.final_state == "REJECT_BELOW_SECONDARY_POLICY"
    assert decision.display_tier == "excluded"
    assert decision.rejection_reason == "REJECT_BELOW_SECONDARY_POLICY"
    # The audit trail proves it was a POLICY outcome, not a validity
    # failure: every gate is on the record as passed.
    assert len(decision.gates_passed) == 13
    assert decision.gates_passed[-1] == "VERIFIED"


def test_below_policy_rejection_is_not_reachable_for_a_directional_ripple():
    """The state must not become a catch-all: a plain MEDIUM-materiality
    d2 tier-D negative is exactly the ripple §1 demands be published."""
    assert _evaluate(causal_distance=2, evidence_tier="D",
                     evidence_class="CURATED_ARCHETYPE",
                     economic_effect="negative", net_direction="bearish",
                     materiality=0.45).final_state == "DISPLAY_ELIGIBLE"


def test_low_materiality_gates_reject_before_secondary():
    """Unchanged MATERIALITY_VALID gate: LOW is rejected outright by default
    policy, so the below-policy state never even gets asked."""
    decision = _evaluate(materiality=0.2)
    assert decision.final_state == "REJECT_LOW_MATERIALITY"
    assert "MATERIALITY_VALID" not in decision.gates_passed


def test_low_materiality_ripple_needs_explicit_owner_policy(monkeypatch):
    monkeypatch.setattr(settings, "impact_allow_low_materiality_deep_dive", True)
    decision = _evaluate(materiality=0.2)
    assert decision.final_state == "DISPLAY_ELIGIBLE"
    assert decision.display_tier == "secondary_ripple"


# --- directness (§11) ------------------------------------------------------

def test_directness_is_not_derived_from_distance_when_the_registry_knows():
    """§11 is explicit: "Do not derive DIRECT/INDIRECT solely from d1/d2."
    aviation_fuel_cost is a d2 mechanism the registry calls DIRECT -- the
    airline burns the shocked commodity itself."""
    decision = _evaluate(causal_parent_id="aviation_fuel_cost", causal_distance=2,
                         economic_effect="negative", net_direction="bearish",
                         evidence_tier="C", materiality=0.8)
    assert decision.causal_directness == "DIRECT"      # not INDIRECT-by-distance
    assert decision.display_tier == "primary"


def test_directness_registry_marks_a_derived_channel_indirect():
    assert derive_directness(_candidate(
        causal_parent_id="paints_input_cost", causal_distance=2)) == "INDIRECT"
    assert derive_directness(_candidate(
        causal_parent_id="vehicle_financier_stress", causal_distance=3)) == "REMOTE"


def test_explicit_directness_outranks_the_registry():
    assert derive_directness(_candidate(
        causal_directness="remote", causal_parent_id="upstream_realization")) == "REMOTE"


def test_directness_falls_back_to_distance_only_when_nothing_else_knows():
    assert derive_directness(_candidate(causal_parent_id="", causal_distance=1)) == "DIRECT"
    assert derive_directness(_candidate(causal_parent_id="", causal_distance=2)) == "INDIRECT"
    assert derive_directness(_candidate(causal_parent_id="", causal_distance=3)) == "REMOTE"
    # An unknown mechanism id must not be guessed at either.
    assert derive_directness(_candidate(
        causal_parent_id="not_a_mechanism_xyz", causal_distance=2)) == "INDIRECT"


def test_a_sector_or_company_parent_is_never_looked_up_as_a_mechanism():
    """The registry keys mechanisms; a company/sector parent that happens to
    collide with a mechanism id must not borrow its directness."""
    assert derive_directness(_candidate(
        causal_parent_type="company", causal_parent_id="upstream_realization",
        causal_distance=2)) == "INDIRECT"


# --- confidence bands (§18) ------------------------------------------------

def test_confidence_band_never_high_on_curated_evidence():
    """§18: "Do not display HIGH when the evidence basis is weak." A curated
    archetype cannot become a high-confidence claim by raising a float."""
    decision = _evaluate(evidence_class="CURATED_ARCHETYPE", evidence_tier="D",
                         materiality=0.95)
    assert decision.confidence_band in ("MEDIUM", "LOW")


def test_confidence_band_high_needs_every_contributor():
    assert _evaluate().confidence_band == "HIGH"
    # ...and each contributor alone can take it away.
    assert _evaluate(counterfactual="UNCERTAIN").confidence_band != "HIGH"
    assert _evaluate(analysis_quality="fallback").confidence_band != "HIGH"
    assert _evaluate(materiality=0.45).confidence_band != "HIGH"


def test_confidence_band_is_unknown_when_the_pipeline_could_not_answer():
    """UNKNOWN is not a low score -- it is the absence of one. A rejected
    candidate has no displayed claim to be confident about."""
    assert _evaluate(analysis_quality="failed").confidence_band == "UNKNOWN"
    assert _evaluate(verification_available=False).confidence_band == "UNKNOWN"
    assert _evaluate(entity_status="unresolved").confidence_band == "UNKNOWN"


@pytest.mark.parametrize("tier", DISPLAYABLE_TIERS + LEGACY_SECONDARY_SPELLINGS)
def test_confidence_band_is_always_from_the_closed_vocabulary(tier):
    assert confidence_band(_candidate(), tier) in CONFIDENCE_BANDS


def test_confidence_band_is_deterministic():
    candidate = _candidate()
    assert confidence_band(candidate, "primary") == confidence_band(candidate, "primary")


# --- direction derivation (§4) ---------------------------------------------

def test_direction_from_effect_is_total():
    """One canonical truth: every member of the closed effect vocabulary
    maps to exactly one direction, so no consumer ever needs a second
    table (which is how Oil India got a bearish company on top of bullish
    channels)."""
    assert set(DIRECTION_FROM_EFFECT) == set(ECONOMIC_EFFECTS)
    for effect in ECONOMIC_EFFECTS:
        assert DIRECTION_FROM_EFFECT[effect] in ("bullish", "bearish", "neutral")


def test_direction_from_effect_never_invents_a_sign():
    assert DIRECTION_FROM_EFFECT["mixed"] == "neutral"
    assert DIRECTION_FROM_EFFECT["uncertain"] == "neutral"


# --- net-effect validator (§4/§24) -----------------------------------------

def test_net_effect_validator_blocks_oil_india_shape():
    """The literal defect: a company called NEGATIVE whose only validated
    channel is POSITIVE."""
    assert validate_net_effect("negative", ["positive"]) == NET_EFFECT_CONTRADICTION
    assert validate_net_effect("positive", ["positive"]) is None
    assert validate_net_effect("mixed", ["positive", "negative"]) is None
    assert validate_net_effect("mixed", ["positive"]) == NET_EFFECT_CONTRADICTION


def test_net_effect_validator_rejects_a_directional_claim_with_an_offset():
    assert validate_net_effect("positive", ["positive", "negative"]) == NET_EFFECT_CONTRADICTION
    assert validate_net_effect("negative", ["negative", "positive"]) == NET_EFFECT_CONTRADICTION


def test_net_effect_validator_rejects_a_directional_claim_with_no_channel():
    """§4: "no validated channel -> NO_MATERIAL_IMPACT / reject". A
    direction with nothing behind it is an assertion, not an analysis."""
    assert validate_net_effect("positive", []) == NET_EFFECT_CONTRADICTION
    assert validate_net_effect("negative", None) == NET_EFFECT_CONTRADICTION


def test_a_mixed_channel_is_material_on_both_sides():
    """refiner_marketing_margin's registry effect is `mixed`. A company
    riding only that channel cannot claim a clean direction from it."""
    assert validate_net_effect("mixed", ["mixed"]) is None
    assert validate_net_effect("positive", ["mixed"]) == NET_EFFECT_CONTRADICTION
    assert validate_net_effect("negative", ["mixed"]) == NET_EFFECT_CONTRADICTION


def test_net_effect_validator_abstains_on_non_displayable_effects():
    assert validate_net_effect("uncertain", []) is None
    assert validate_net_effect("no_material_impact", ["positive"]) is None


def test_net_effect_validator_fails_closed_on_an_unknown_effect():
    assert validate_net_effect("slightly_spicy", ["positive"]) == NET_EFFECT_CONTRADICTION
    assert validate_net_effect("", ["positive"]) == NET_EFFECT_CONTRADICTION


def test_net_effect_validator_ignores_immaterial_channels():
    assert validate_net_effect(
        "positive", ["positive", "no_material_impact", "uncertain"]) is None
