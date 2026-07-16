from app.analysis.schemas import EVENT_TYPES, AnalysisOutput, CompanyMention


def test_company_mention_defaults_for_new_evidence_fields():
    mention = CompanyMention(
        name="X", is_direct=True, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", time_horizon="Short-Term",
    )
    assert mention.confidence_score is None
    assert mention.reasons == []
    assert mention.evidence_refs == []
    assert mention.risks == []
    assert mention.assumptions == []
    assert mention.unknowns == []
    assert mention.alternative_hypothesis is None


def test_company_mention_still_accepts_an_explicit_confidence_score():
    # Backward compatibility: older stored data / tests that still pass an
    # int must keep validating.
    mention = CompanyMention(
        name="X", is_direct=True, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", time_horizon="Short-Term",
        confidence_score=85,
    )
    assert mention.confidence_score == 85


def test_analysis_output_event_type_defaults_to_none():
    output = AnalysisOutput(category="oil_energy", companies=[])
    assert output.event_type is None


def test_event_types_are_lowercase_with_underscores_only():
    for value in EVENT_TYPES:
        assert value == value.lower()
        assert " " not in value
    assert "other" in EVENT_TYPES
