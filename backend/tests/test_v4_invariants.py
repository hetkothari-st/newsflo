"""Appendix B invariants (spec 2026-08-12) not already pinned by the
phase suites. Each test names its INV id. The full coverage map:

INV-001/002 truth model      -> test_v4_strict_truth_model.py + here
INV-003/004/005/006/012/013/016 gate -> test_publication_gate.py
INV-007/008/009/010 sections -> test_v4_strict_sections.py
INV-014 closed world         -> test_v4_strict_sections.py (refine tests)
INV-015 no silent loss       -> test_v4_feed_truth.py
INV-019/020 audit            -> test_v4_strict_gate_wiring.py
INV-011/017/018 + structural INV-002 -> here
"""
import pytest

from app.config import settings


@pytest.fixture()
def strict_mode(monkeypatch):
    monkeypatch.setattr(settings, "impact_engine_v4_strict", True)


def test_inv002_gate_input_has_no_market_fields():
    """INV-002 structurally: the publication gate cannot consult market
    movement because its input type carries none. If someone adds an
    excess-move field to CandidateInput, this fails and forces the
    conversation."""
    from dataclasses import fields
    from app.analysis.impact_graph.publication_gate import CandidateInput

    names = {f.name for f in fields(CandidateInput)}
    forbidden = {"excess_move_pct", "raw_move_pct", "market_reaction",
                 "price", "move_pct", "reaction_direction"}
    assert not (names & forbidden)


def test_inv011_unresolvable_ticker_never_persisted(db_session, strict_mode):
    """INV-011: a ticker with no Company row is omitted at the adapter --
    an invented ticker cannot become a persisted AlertCompany."""
    from app.pipeline import _v3_entries
    from app.analysis.impact_graph.schemas import GraphCompany, ImpactGraphResult

    ghost = GraphCompany(
        ticker="GHOST.NS", name="Ghost Co", direction="bullish",
        impact_strength=0.9, confidence=0.9, materiality=0.9, causal_distance=1,
        time_horizon="Short-Term", parent_type="economic_node",
        parent_id="crude_price", mechanism="entirely fabricated exposure story",
        rationale="hallucinated", verified=True)
    result = ImpactGraphResult(category="commodity", event_type="crude_oil",
                               facts="f", companies=[ghost], edges=[])

    assert _v3_entries(db_session, result) == []


def test_inv017_018_prompt_contracts_forbid_invention():
    """INV-017/018: the high-value impact-graph prompts must carry the
    no-invention / abstention-allowed contract in their text."""
    from app.analysis.impact_graph import prompts

    selection_prompts = [
        prompts.MAPPING_PROMPT if hasattr(prompts, "MAPPING_PROMPT") else "",
        getattr(prompts, "VERIFY_COMPANIES_PROMPT", ""),
    ]
    combined = " ".join(p.lower() for p in selection_prompts if p)
    assert "never" in combined or "do not" in combined
    # The verifier must be empowered to reject (spec §30).
    assert "reject" in getattr(prompts, "VERIFY_COMPANIES_PROMPT", "").lower()


def test_scenario_omc_negative_and_airline_negative_pass_gate():
    """Spec regression scenarios #3/#4: OMC and airline candidates with
    real mechanisms and evidence clear the gate as primary NEGATIVE."""
    from app.analysis.impact_graph.publication_gate import (
        CandidateInput, evaluate_candidate,
    )

    for ticker, mechanism in (
        ("IOC.NS", "crude cost up compresses regulated marketing margins on fuels"),
        ("INDIGO.NS", "ATF is ~40% of operating cost; crude spike raises fuel bill"),
    ):
        decision = evaluate_candidate(CandidateInput(
            ticker=ticker, entity_resolved=True, mechanism=mechanism,
            rationale="company-specific cost exposure with limited near-term pass-through",
            economic_effect="negative", causal_distance=1, materiality=0.7,
            confidence=0.8, independently_verified=True,
            verification_available=True, evidence_class="VERIFIED_RELATIONSHIP",
            negative_channels=["fuel cost"], net_direction="bearish"))
        assert decision.final_state == "DISPLAY_ELIGIBLE"
        assert decision.display_tier == "primary"


def test_scenario_generic_nbfc_macro_ripple_rejected():
    """Spec scenario #9: 'oil up -> inflation -> NBFC affected' is a
    generic macro story -- rejected, machine-readable."""
    from app.analysis.impact_graph.publication_gate import (
        CandidateInput, evaluate_candidate,
    )

    decision = evaluate_candidate(CandidateInput(
        ticker="BAJFINANCE.NS", entity_resolved=True,
        mechanism="higher inflation could pressure consumer lending demand broadly",
        rationale="large company in the sector exposed to macro conditions",
        economic_effect="negative", causal_distance=3, materiality=0.4,
        confidence=0.5, independently_verified=True, verification_available=True,
        evidence_class="MODEL_INFERENCE", negative_channels=["demand"],
        net_direction="bearish"))

    assert decision.final_state == "REJECT_GENERIC_EXPOSURE"
    assert decision.display_tier == "excluded"
