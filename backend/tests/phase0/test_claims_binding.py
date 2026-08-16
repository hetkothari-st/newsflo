"""TASK 0.5 tests -- claim records and their binding rules (spec §11.1).

docs/v5/01_PHASE_0_canonical_truth.md TESTS/test_claims_binding.py:
  * PASS_THROUGH claim without company-named filing evidence => UNBOUND
  * company with any UNBOUND claim => gate returns REJECTED
"""
import pytest

from tests.phase0 import fixtures


def _claim(claim_type="PASS_THROUGH", company_id=9001, **overrides):
    from app.core.claims import Claim

    base = dict(
        claim_id="cl_test", event_id="fixture:crude-shock-1",
        company_id=company_id, claim_type=claim_type, fact_class="DERIVED",
        structured={"_fixture": True, "share_passed": 0.5},
        evidence_ids=("ev_1",), created_by="test",
    )
    base.update(overrides)
    return Claim(**base)


def _evidence(source_type="ANNUAL_REPORT", company_ids=(9001,), evidence_id="ev_1"):
    from app.core.claims import Evidence

    return Evidence(
        evidence_id=evidence_id, source_type=source_type,
        source_name="fixture source", source_date="2026-04-30",
        company_ids=tuple(company_ids), quoted_text="fixture quote",
        fact_text="fixture fact")


@pytest.mark.parametrize("claim_type", ["PASS_THROUGH", "HEDGE", "COMPETITIVE", "TIMING"])
def test_evidence_required_claim_without_company_named_filing_is_unbound(claim_type):
    from app.core.claims import binding_status

    # No evidence at all.
    assert binding_status(_claim(claim_type), []) == "UNBOUND"
    # Evidence from an accepted source that names a DIFFERENT company.
    assert binding_status(_claim(claim_type), [_evidence(company_ids=(9999,))]) == "UNBOUND"
    # Evidence naming the company but from a source type that is not a filing.
    assert binding_status(
        _claim(claim_type), [_evidence(source_type="NEWS_ARTICLE")]) == "UNBOUND"


@pytest.mark.parametrize("source_type", ["ANNUAL_REPORT", "QUARTERLY",
                                         "EARNINGS_CALL", "EXCHANGE_FILING"])
def test_evidence_required_claim_with_company_named_filing_is_bound(source_type):
    from app.core.claims import binding_status

    assert binding_status(
        _claim("PASS_THROUGH"), [_evidence(source_type=source_type)]) == "BOUND"


def test_ordinary_claim_with_sector_level_evidence_is_sector_proxy():
    from app.core.claims import binding_status

    status = binding_status(
        _claim("COST_EXPOSURE"), [_evidence(company_ids=(9999,))])
    assert status == "SECTOR_PROXY"


def test_ordinary_claim_with_no_evidence_at_all_is_unbound():
    from app.core.claims import binding_status

    assert binding_status(_claim("COST_EXPOSURE"), []) == "UNBOUND"


def test_an_unknown_claim_type_is_refused_rather_than_bound():
    from app.core.claims import ClaimVocabularyError

    with pytest.raises(ClaimVocabularyError):
        _claim("VIBES")


def test_a_numeral_in_a_claim_must_come_from_a_structured_field():
    """Spec §11.1: 'Any claim containing a numeral must trace to a stored
    numeric field. Numerals may not originate in generated text.'"""
    from app.core.claims import ClaimVocabularyError

    with pytest.raises(ClaimVocabularyError):
        _claim("COST_EXPOSURE", structured={"_fixture": True,
                                            "note": "about 28% of COGS"})


def test_company_with_an_unbound_claim_is_rejected_by_the_gate():
    from app.core.claims import binding_status
    from app.core.gates import ImpactDraft, evaluate

    config = fixtures.reducer_config().gate_config
    claim = _claim("PASS_THROUGH")
    assert binding_status(claim, []) == "UNBOUND"

    draft = ImpactDraft(
        entity_status="ACTIVE", entity_ambiguous=False, exposure_stale=False,
        materiality_bucket="HIGH", graph_distance=1, directness="DIRECT",
        evidence_grade="A", weakest_link=None, sign_consistency=1.0,
        empirical_status="NO_DATA", objections=(),
        unbound_claim_ids=(claim.claim_id,), verifier_status="PASS",
        adv_20d_inr=None, event_status="CONFIRMED",
        shock_magnitude_confidence=None, mechanism_id="crude_input_cost",
        net_effect="NEGATIVE")
    result = evaluate(draft, config)
    assert result.tier == "REJECTED"
    assert result.rejection_reason == "UNBOUND_CLAIM"


def test_the_reducer_rejects_a_company_whose_binding_signal_says_unbound():
    """End to end through the reducer, not only the gate: an
    EVIDENCE_BINDING signal carrying UNBOUND is a hard reject."""
    from app.core.reducer import reduce_company_impact
    from app.core.signals import make_signal

    signal_set = list(fixtures.signals(fixtures.PRIMARY_COMPANY_ID))
    signal_set.append(make_signal(
        event_id=fixtures.EVENT_ID, company_id=fixtures.PRIMARY_COMPANY_ID,
        stage="EVIDENCE", kind="EVIDENCE_BINDING",
        payload={"_fixture": True, "claim_id": "cl_unbound",
                 "claim_type": "HEDGE", "binding_status": "UNBOUND",
                 "evidence_grade": "E", "evidence_ids": []},
        created_by="fixture:evidence_classifier",
        analysis_version=fixtures.ANALYSIS_VERSION,
        created_at=fixtures.FIXTURE_CREATED_AT))

    impact = reduce_company_impact(signal_set, fixtures.reducer_config())
    assert impact.publication_tier == "REJECTED"
    assert impact.rejection_reason == "UNBOUND_CLAIM"


def test_weakest_link_names_the_weakest_binding():
    from app.core.reducer import reduce_company_impact

    config = fixtures.reducer_config()
    remote = reduce_company_impact(
        fixtures.signals(fixtures.REMOTE_COMPANY_ID), config)
    assert remote.weakest_link == "COST_EXPOSURE:SECTOR_PROXY"
