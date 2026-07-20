from app.analysis.schemas import EVENT_TYPES, AnalysisOutput, CompanyMention, SECTOR_DEFINITIONS, SECTORS, FactsResult, SectorFinding


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


def test_new_sectors_are_in_the_taxonomy():
    for sector in [
        "railways_transport", "construction_realestate", "defense", "agriculture",
        "consumer_durables", "media_entertainment", "chemicals", "textiles",
    ]:
        assert sector in SECTORS


def test_sectors_has_exactly_one_shared_other_bucket():
    assert SECTORS.count("other") == 1


def test_sector_definitions_covers_every_sector():
    for sector in SECTORS:
        assert f"- {sector}:" in SECTOR_DEFINITIONS


def test_facts_result_parses_required_fields():
    result = FactsResult(facts="Rupee fell 2% today.", category="macro_policy", event_type="currency_move")
    assert result.facts == "Rupee fell 2% today."
    assert result.category == "macro_policy"
    assert result.event_type == "currency_move"


def test_sector_finding_parent_sector_defaults_to_none():
    finding = SectorFinding(sector="banking", direction="bearish", mechanism="FX exposure hit.")
    assert finding.parent_sector is None


def test_sector_finding_accepts_parent_sector_for_cascade():
    finding = SectorFinding(sector="railways_transport", direction="bearish", mechanism="Import costs rise.", parent_sector="banking")
    assert finding.parent_sector == "banking"


def test_company_mention_defaults_impact_level_to_direct_when_absent():
    mention = CompanyMention(
        name="Reliance Industries", is_direct=True, direction="bullish",
        magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin", time_horizon="Short-Term",
    )
    assert mention.impact_level == "direct"
    assert mention.parent_ticker is None
