"""Boundary tests for the deterministic vague-rationale guard.

The false-positive direction is the dangerous one: this guard silently
deletes a company from a user-visible alert and nothing downstream can
recover it. So the NOT-flagged cases below carry at least as much weight as
the flagged ones -- every one of them is a rationale a real analyst would
write and that hedges somewhere in the sentence.
"""
from app.reasoning.vagueness import flag_vague_rationale


# -- flagged: hedge with nothing concrete behind it -----------------------

def test_flags_may_benefit_with_no_channel():
    result = flag_vague_rationale("IndiGo may benefit from the broader aerospace theme.")
    assert result.is_vague is True
    assert "may" in result.reason


def test_flags_could_see_with_only_sentiment():
    result = flag_vague_rationale("The company could see an impact as sentiment improves.")
    assert result.is_vague is True


def test_flags_bare_potentially():
    assert flag_vague_rationale("Potentially affected by this development.").is_vague is True


def test_flags_is_exposed_to_with_no_named_exposure():
    assert flag_vague_rationale("It is exposed to this news.").is_vague is True


def test_flags_broader_theme_language():
    result = flag_vague_rationale(
        "This name is likely to participate in the broader theme playing out here."
    )
    assert result.is_vague is True


def test_reason_names_the_hedge_that_triggered_it():
    result = flag_vague_rationale("The stock could react to this.")
    assert "'could'" in result.reason
    assert "concrete" in result.reason


# -- NOT flagged: hedge PLUS a concrete channel ---------------------------
# A false positive here deletes correct analysis. Hedging is normal analyst
# language; only a hedge with nothing behind it is the defect.

def test_keeps_hedged_rationale_that_names_a_cost_line():
    # The canonical boundary case from the spec.
    result = flag_vague_rationale(
        "Margins may compress because jet fuel is 30% of operating cost."
    )
    assert result.is_vague is False
    assert result.reason is None


def test_keeps_hedged_rationale_that_names_a_revenue_line():
    assert flag_vague_rationale(
        "Revenue could rise as the order book expands with new defence contracts."
    ).is_vague is False


def test_keeps_exposed_to_when_the_exposure_is_actually_named():
    assert flag_vague_rationale(
        "It is exposed to crude oil prices through its refining input costs."
    ).is_vague is False


def test_keeps_a_named_customer_relationship_however_hedged():
    assert flag_vague_rationale(
        "Deliveries to its largest customer may slip if certification is delayed."
    ).is_vague is False


def test_keeps_a_named_regulatory_exposure_however_hedged():
    assert flag_vague_rationale(
        "Approval of the variant could unlock the pending certification for its parts."
    ).is_vague is False


def test_keeps_a_hyphenated_channel_word():
    # \b matches across the hyphen -- "jet-fuel" must still read as concrete.
    assert flag_vague_rationale(
        "Sentiment may wobble, but concretely its jet-fuel bill falls."
    ).is_vague is False


def test_a_rationale_with_no_hedge_at_all_is_never_flagged():
    # Rule 1 short-circuits: no hedge, no judgement. This guard is about
    # hedging, not about quality in general.
    assert flag_vague_rationale(
        "Supplies titanium forgings for airframe structural assemblies."
    ).is_vague is False


def test_generic_prominence_without_a_hedge_is_left_to_the_llm_verifier():
    # Deliberate scope limit, not an oversight: "major player" is a
    # prominence claim, not a hedge, and inferring vagueness from it needs
    # judgement a regex does not have. VERIFICATION_FRAMING category 3 owns
    # this case.
    assert flag_vague_rationale("It is a major player in this sector.").is_vague is False


def test_empty_and_none_are_not_flagged():
    assert flag_vague_rationale("").is_vague is False
    assert flag_vague_rationale(None).is_vague is False


def test_is_a_pure_function_of_its_input():
    text = "It may be affected."
    assert flag_vague_rationale(text) == flag_vague_rationale(text)
