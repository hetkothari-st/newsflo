import pytest

from app.reasoning.confidence import (
    WEIGHT_DATA_FRESHNESS,
    WEIGHT_EVIDENCE_COMPLETENESS,
    WEIGHT_HISTORICAL_CALIBRATION,
    WEIGHT_REASONING_CONSISTENCY,
    WEIGHT_RULEBOOK_MATCH,
    WEIGHT_SOURCE_CREDIBILITY,
    _band,
    compute_confidence,
    source_credibility,
)


def test_weights_sum_to_one():
    total = (
        WEIGHT_HISTORICAL_CALIBRATION + WEIGHT_EVIDENCE_COMPLETENESS + WEIGHT_RULEBOOK_MATCH
        + WEIGHT_SOURCE_CREDIBILITY + WEIGHT_REASONING_CONSISTENCY + WEIGHT_DATA_FRESHNESS
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
    result = compute_confidence(
        calibration_sample_count=0, calibration_hit_rate=None,
        claim_count=3, evidence_ref_count=0, rule_matched=False,
        source_credibility=0.7, reasoning_consistent=True, article_age_hours=0,
    )
    assert result.score == 27
    assert result.band == "LOW"
    assert any("historical" in p.lower() for p in result.penalties)
    assert any("evidence" in p.lower() or "claim" in p.lower() for p in result.penalties)
    assert any("rulebook" in p.lower() or "rule" in p.lower() for p in result.penalties)


def test_strong_inputs_score_very_high():
    result = compute_confidence(
        calibration_sample_count=10, calibration_hit_rate=0.9,
        claim_count=2, evidence_ref_count=2, rule_matched=True,
        source_credibility=0.85, reasoning_consistent=True, article_age_hours=1,
    )
    assert result.score == 95
    assert result.band == "VERY_HIGH"
    assert any("calibration" in c.lower() for c in result.contributors)
    assert any("rule" in c.lower() for c in result.contributors)


def test_zero_claims_treated_as_fully_covered_not_penalized():
    result = compute_confidence(
        calibration_sample_count=0, calibration_hit_rate=None,
        claim_count=0, evidence_ref_count=0, rule_matched=False,
        source_credibility=0.7, reasoning_consistent=True, article_age_hours=0,
    )
    assert not any("evidence" in p.lower() and "claims" in p.lower() for p in result.penalties)


def test_reasoning_inconsistency_is_penalized():
    result = compute_confidence(
        calibration_sample_count=0, calibration_hit_rate=None,
        claim_count=0, evidence_ref_count=0, rule_matched=False,
        source_credibility=0.7, reasoning_consistent=False, article_age_hours=0,
    )
    assert any("inconsistent" in p.lower() for p in result.penalties)


def test_score_is_clamped_to_0_100_range():
    result = compute_confidence(
        calibration_sample_count=100, calibration_hit_rate=1.0,
        claim_count=1, evidence_ref_count=1, rule_matched=True,
        source_credibility=1.0, reasoning_consistent=True, article_age_hours=0,
    )
    assert 0 <= result.score <= 100


def test_source_credibility_known_and_default():
    assert source_credibility("economic_times") == pytest.approx(0.85)
    assert source_credibility("moneycontrol") == pytest.approx(0.8)
    assert source_credibility("business_standard") == pytest.approx(0.8)
    assert source_credibility("some_unknown_source") == pytest.approx(0.7)
