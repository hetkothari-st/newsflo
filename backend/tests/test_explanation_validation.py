"""Task 13: post-generation closed-world validation for LLM explanation
text, the mechanism sanitizer that lets a strict-mode `why` survive a
flagged clause instead of being discarded whole, and the deterministic
divergence-interpretation template.
"""
from app.analysis.refinement import (
    _sanitize_mechanism,
    divergence_line,
    validate_closed_world,
)
from app.companies.matching.normalize import normalize_name
from app.models import Company, CompanyAlias


def _seed_company(db_session, name: str, ticker: str, alias: str | None = None) -> Company:
    company = Company(ticker=ticker, name=name, sector="oil_gas", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()
    db_session.add(CompanyAlias(
        company_id=company.id, alias=alias or name, alias_type="LEGAL",
        normalized=normalize_name(alias or name),
    ))
    db_session.commit()
    return company


# --- validate_closed_world: foreign-company rejection --------------------

def test_summary_naming_foreign_company_is_dropped(db_session):
    _seed_company(db_session, "Infosys", "INFY.NS")
    facts = "A domestic company announced a new manufacturing plant."
    text = "Infosys is expected to benefit from this policy shift."

    result = validate_closed_world(text, facts, allowed_company_names=set(), session=db_session)

    assert result is None


def test_summary_naming_a_tracked_company_is_kept(db_session):
    company = _seed_company(db_session, "Reliance Industries", "RELIANCE.NS")
    facts = "Reliance Industries announced a new refinery expansion."
    text = "Reliance Industries plans to expand its refining capacity."

    result = validate_closed_world(
        text, facts, allowed_company_names={company.name}, session=db_session,
    )

    assert result == text


def test_summary_naming_a_company_grounded_in_facts_but_untracked_is_kept(db_session):
    """A company mentioned in the source facts (but not one of the alert's
    own tracked companies) is grounded evidence, not a hallucination."""
    _seed_company(db_session, "Tata Motors", "TATAMOTORS.NS")
    facts = "Tata Motors also raised prices in response to the same input cost pressure."
    text = "Tata Motors raised prices as a result."

    result = validate_closed_world(text, facts, allowed_company_names=set(), session=db_session)

    assert result == text


def test_text_with_no_capitalized_company_like_phrase_passes_through(db_session):
    facts = "Crude oil prices rose sharply overnight."
    text = "Higher input costs squeeze margins across the sector."

    result = validate_closed_world(text, facts, allowed_company_names=set(), session=db_session)

    assert result == text


# --- validate_closed_world: percent grounding -----------------------------

def test_percent_not_present_in_facts_is_dropped(db_session):
    facts = "The company reported higher quarterly revenue."
    text = "Profit is said to have jumped 15% this quarter."

    result = validate_closed_world(text, facts, allowed_company_names=set(), session=db_session)

    assert result is None


def test_percent_present_in_facts_is_kept(db_session):
    facts = "The company reported a 12% rise in quarterly revenue."
    text = "Revenue rose 12% during the quarter."

    result = validate_closed_world(text, facts, allowed_company_names=set(), session=db_session)

    assert result == text


def test_empty_text_returns_none(db_session):
    assert validate_closed_world(None, "facts", set(), db_session) is None
    assert validate_closed_world("", "facts", set(), db_session) is None


# --- validate_closed_world: fail-open on DB error -------------------------

def test_validator_fails_open_on_db_error(caplog):
    class ExplodingSession:
        def query(self, *args, **kwargs):
            raise RuntimeError("db unavailable")

    facts = "Nothing relevant here."
    text = "Infosys reportedly benefits from this shift."

    with caplog.at_level("WARNING"):
        result = validate_closed_world(text, facts, allowed_company_names=set(), session=ExplodingSession())

    assert result == text
    assert "closed-world company validation unavailable" in caplog.text


# --- mechanism sanitizer ---------------------------------------------------

def test_mechanism_with_percent_is_sanitized_with_no_percent_surviving():
    mechanism = (
        "Margins are set to expand as raw material costs ease. "
        "Analysts had pencilled in a 40% jump in quarterly profit."
    )

    result = _sanitize_mechanism(mechanism)

    assert result is not None
    assert "%" not in result
    assert "Margins are set to expand as raw material costs ease." in result


def test_mechanism_entirely_about_a_percentage_sanitizes_to_none():
    mechanism = "Profit is expected to rise 40% this quarter."

    assert _sanitize_mechanism(mechanism) is None


def test_mechanism_salvages_a_clause_within_a_flagged_sentence():
    mechanism = "Costs rise sharply, adding roughly 40% to input prices, which squeezes near-term margins."

    result = _sanitize_mechanism(mechanism)

    assert result is not None
    assert "%" not in result
    assert "squeezes near-term margins" in result


def test_sanitize_mechanism_none_input_returns_none():
    assert _sanitize_mechanism(None) is None
    assert _sanitize_mechanism("") is None


# --- divergence_line: four sign combinations + flat/unknown --------------

def test_divergence_negative_effect_positive_reaction():
    assert divergence_line("negative", "positive") == (
        "Stock is currently moving up despite a negative fundamental exposure thesis."
    )


def test_divergence_positive_effect_negative_reaction():
    assert divergence_line("positive", "negative") == (
        "Stock is currently moving down despite a positive fundamental exposure thesis."
    )


def test_divergence_aligned_signs_return_none():
    assert divergence_line("positive", "positive") is None
    assert divergence_line("negative", "negative") is None


def test_divergence_mixed_or_uncertain_effect_returns_none():
    assert divergence_line("mixed", "positive") is None
    assert divergence_line("uncertain", "negative") is None
    assert divergence_line("no_material_impact", "positive") is None


def test_divergence_flat_or_unknown_reaction_returns_none():
    assert divergence_line("negative", "flat") is None
    assert divergence_line("positive", "unknown") is None
    assert divergence_line("negative", "unknown") is None
