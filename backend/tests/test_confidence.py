import pytest

from app.reasoning.confidence import (
    WEIGHT_DATA_FRESHNESS,
    WEIGHT_EVIDENCE_COMPLETENESS,
    WEIGHT_RULEBOOK_MATCH,
    WEIGHT_SOURCE_CREDIBILITY,
    _band,
    compute_confidence,
    source_credibility,
)


def test_weights_sum_to_one():
    total = (
        WEIGHT_EVIDENCE_COMPLETENESS + WEIGHT_RULEBOOK_MATCH
        + WEIGHT_SOURCE_CREDIBILITY + WEIGHT_DATA_FRESHNESS
    )
    assert total == pytest.approx(1.0)


def test_band_boundaries():
    assert _band(0) == "LOW"
    assert _band(39) == "LOW"
    assert _band(40) == "MODERATE"
    assert _band(69) == "MODERATE"
    assert _band(70) == "HIGH"
    assert _band(89) == "HIGH"
    assert _band(90) == "VERY_HIGH"
    assert _band(100) == "VERY_HIGH"


def test_weak_inputs_score_low():
    # Genuinely weak: no evidence, no rule, stale article. Only the two
    # evidence-derived components are treated as inapplicable when refs are
    # absent -- freshness still bites for real, and inapplicable is not the
    # same as forgiving.
    result = compute_confidence(
        claim_count=3, evidence_ref_count=0, rule_matched=False,
        source_credibility=0.7, article_age_hours=160,
    )
    assert result.band == "LOW"
    assert any("evidence" in p.lower() or "claim" in p.lower() for p in result.penalties)
    assert any("rulebook" in p.lower() or "rule" in p.lower() for p in result.penalties)


def _typical(**overrides):
    """A typical production company: no rulebook in the company prompt (so
    no rule can match), fresh article, full evidence coverage."""
    kwargs = dict(
        claim_count=3, evidence_ref_count=3, rule_matched=False,
        source_credibility=0.85, article_age_hours=2,
    )
    kwargs.update(overrides)
    return compute_confidence(**kwargs)


def test_absent_evidence_refs_do_not_drop_a_company_under_the_pipeline_floor():
    """THE regression this guards, and it is a production-outage-class one.

    evidence_refs is an OPTIONAL tool-schema field (see app.analysis.cascade.
    _COMPANY_ITEM_REQUIRED -- dropped so the company prompt fits gpt-oss-20b's
    token ceiling). Scored naively, a company that supplies none takes a hard
    zero on the evidence AND rulebook components and lands under
    app.pipeline.CONFIDENCE_FLOOR (40) -- so _persist_alert silently deletes
    it. Every company, on every alert: the same zero-companies outage the
    prompt work exists to fix, arriving through the scorer instead.
    """
    from app.pipeline import CONFIDENCE_FLOOR

    assert _typical(evidence_ref_count=0).score >= CONFIDENCE_FLOOR


def test_omitting_optional_evidence_never_scores_better_than_supplying_it():
    """Optional fields may only ever help. Without this, a model is rewarded
    for omitting evidence_refs -- and a half-filled list (1 ref for 3 claims)
    would score BELOW an empty one, dropping the more forthcoming answer."""
    none_supplied = _typical(evidence_ref_count=0).score
    partial = _typical(evidence_ref_count=1).score
    full = _typical(evidence_ref_count=3).score

    assert partial >= none_supplied
    assert full >= partial


def test_a_matched_rulebook_rule_still_raises_the_score():
    """The inapplicable-when-absent handling must not flatten the rulebook
    signal for the callers that DO have one."""
    assert _typical(rule_matched=True).score > _typical(rule_matched=False).score


def test_strong_inputs_score_very_high():
    result = compute_confidence(
        claim_count=2, evidence_ref_count=2, rule_matched=True,
        source_credibility=0.85, article_age_hours=1,
    )
    assert result.score == 97
    assert result.band == "VERY_HIGH"
    assert any("evidence" in c.lower() for c in result.contributors)
    assert any("rule" in c.lower() for c in result.contributors)


def test_zero_claims_treated_as_fully_covered_not_penalized():
    result = compute_confidence(
        claim_count=0, evidence_ref_count=0, rule_matched=False,
        source_credibility=0.7, article_age_hours=0,
    )
    assert not any("evidence" in p.lower() and "claims" in p.lower() for p in result.penalties)


def test_score_is_clamped_to_0_100_range():
    result = compute_confidence(
        claim_count=1, evidence_ref_count=1, rule_matched=True,
        source_credibility=1.0, article_age_hours=0,
    )
    assert 0 <= result.score <= 100


def test_source_credibility_known_and_default():
    assert source_credibility("economic_times") == pytest.approx(0.85)
    assert source_credibility("moneycontrol") == pytest.approx(0.8)
    assert source_credibility("business_standard") == pytest.approx(0.8)
    assert source_credibility("some_unknown_source") == pytest.approx(0.7)


# The "no price/market inputs can ever reach this module" grep-provable
# guard lives in tests/test_price_fundamental_decoupling.py, alongside the
# rest of that policy's tests.
