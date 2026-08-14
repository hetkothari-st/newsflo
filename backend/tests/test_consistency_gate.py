"""Blueprint §24 -- the deterministic consistency gate.

Pure functions over an alert-shaped dict, no DB and no LLM: the SAME check
runs before persistence (app.pipeline._persist_alert) and before serving
(feed serializers, T6). Every case here is a shape the system has actually
produced or could produce -- the Oil India contradiction (company NEGATIVE
sitting on a validated POSITIVE channel) is the one this file exists for.
"""
import pytest

from app.analysis.impact_graph.consistency import (
    ConsistencyError,
    check_alert_consistency,
)


def _company(**overrides):
    payload = dict(
        ticker="ONGC.NS", economic_effect="positive", direction="bullish",
        display_tier="primary", channel_effects=["positive"],
    )
    payload.update(overrides)
    return payload


def _alert(companies=None, **overrides):
    payload = dict(
        companies=companies if companies is not None else [_company()],
        headline_ticker=None, headline_tier_source=None,
    )
    payload.update(overrides)
    return payload


# --- consistent shapes pass -------------------------------------------------

def test_a_consistent_alert_reports_no_violations():
    assert check_alert_consistency(_alert()) == []


def test_an_alert_with_no_companies_is_consistent():
    assert check_alert_consistency(_alert(companies=[])) == []


def test_mixed_effect_with_both_channels_and_neutral_direction_passes():
    assert check_alert_consistency(_alert([_company(
        economic_effect="mixed", direction="neutral",
        channel_effects=["positive", "negative"])])) == []


def test_a_company_that_declared_no_channels_is_not_a_contradiction():
    """The net-effect validator treats an EMPTY channel list as a
    contradiction (nothing supports the claim). At the alert level that
    would fail every company the model never broke into channels at all --
    which is silence, not a contradiction. §24 validates the company's
    effect against its VALIDATED channels; with none on file there is
    nothing to validate against, so the check abstains."""
    assert check_alert_consistency(_alert([_company(channel_effects=[])])) == []
    assert check_alert_consistency(_alert([_company(channel_effects=None)])) == []


# --- the Oil India shape ----------------------------------------------------

def test_oil_india_shape_is_blocked():
    """Company NEGATIVE + bearish, every validated channel POSITIVE."""
    violations = check_alert_consistency(_alert([_company(
        ticker="OIL.NS", economic_effect="negative", direction="bearish",
        channel_effects=["positive"])]))

    assert len(violations) == 1
    assert "NET_EFFECT_CONTRADICTION" in violations[0]
    assert "OIL.NS" in violations[0]


def test_an_acknowledged_offsetting_channel_is_not_a_contradiction():
    """A claim SUPPORTED by its own channels that also lists an opposing
    one is an offsetting analysis, not a contradiction: §4 says "no
    MATERIAL negative", and channel materiality is not modelled (channels
    are plain sentences). Blocking this shape would refuse the system's own
    correct output -- e.g. a fertiliser producer that is net NEGATIVE while
    cheaper feedstock arrives with a lag."""
    assert check_alert_consistency(_alert([_company(
        channel_effects=["positive", "negative"])])) == []
    assert check_alert_consistency(_alert([_company(
        economic_effect="negative", direction="bearish",
        channel_effects=["negative", "positive"])])) == []


def test_a_mixed_claim_missing_one_side_is_still_blocked():
    """`mixed` is a claim ABOUT both sides existing, so a missing side is
    an unsupported claim rather than an offset."""
    violations = check_alert_consistency(_alert([_company(
        economic_effect="mixed", direction="neutral", channel_effects=["positive"])]))

    assert any("NET_EFFECT_CONTRADICTION" in v for v in violations)


def test_only_the_offending_company_is_named():
    violations = check_alert_consistency(_alert([
        _company(ticker="ONGC.NS"),
        _company(ticker="OIL.NS", economic_effect="negative", direction="bearish",
                 channel_effects=["positive"]),
    ]))

    assert len(violations) == 1
    assert "OIL.NS" in violations[0] and "ONGC.NS" not in violations[0]


# --- direction is DERIVED, never independent --------------------------------

def test_direction_contradicting_the_effect_is_blocked():
    violations = check_alert_consistency(_alert([_company(
        economic_effect="negative", direction="bullish", channel_effects=["negative"])]))

    assert any("DIRECTION_NOT_DERIVED" in v for v in violations)


def test_mixed_effect_rendered_bullish_is_blocked():
    violations = check_alert_consistency(_alert([_company(
        economic_effect="mixed", direction="bullish",
        channel_effects=["positive", "negative"])]))

    assert any("DIRECTION_NOT_DERIVED" in v for v in violations)


def test_an_absent_effect_abstains_rather_than_blocking():
    """`economic_effect` is nullable and the whole pre-v3 corpus carries
    none. Absent is silence -- there is nothing to derive a direction from
    and nothing to contradict -- unlike a PRESENT value outside the closed
    vocabulary, which is checked below."""
    assert check_alert_consistency(_alert([_company(
        economic_effect=None, direction="bullish", channel_effects=[])])) == []
    assert check_alert_consistency(_alert([_company(
        economic_effect="", direction="bullish", channel_effects=[])])) == []


def test_an_effect_outside_the_closed_vocabulary_is_blocked():
    violations = check_alert_consistency(_alert([_company(
        economic_effect="slightly_spicy", direction="bullish", channel_effects=[])]))

    assert any("UNKNOWN_ECONOMIC_EFFECT" in v for v in violations)


# --- tier vocabulary --------------------------------------------------------

@pytest.mark.parametrize("tier", ["primary", "secondary_ripple", "macro_context", "excluded"])
def test_canonical_tiers_are_accepted(tier):
    assert check_alert_consistency(_alert([_company(display_tier=tier)])) == []


@pytest.mark.parametrize("tier", ["secondary_deep_dive", "secondary"])
def test_legacy_secondary_spellings_stay_readable(tier):
    """Read-compat only: rows persisted before the rename must not be
    reported as violations by a gate that also runs pre-SERVE."""
    assert check_alert_consistency(_alert([_company(display_tier=tier)])) == []


def test_an_unknown_tier_is_blocked():
    violations = check_alert_consistency(_alert([_company(display_tier="headline")]))

    assert any("UNKNOWN_DISPLAY_TIER" in v for v in violations)


# --- headline subset rule (ruling R1) ---------------------------------------

def test_headline_company_must_be_a_primary_company():
    alert = _alert([
        _company(ticker="ONGC.NS", display_tier="primary"),
        _company(ticker="ASIANPAINT.NS", economic_effect="negative", direction="bearish",
                 display_tier="secondary_ripple", channel_effects=["negative"]),
    ], headline_ticker="ONGC.NS")

    assert check_alert_consistency(alert) == []


def test_headline_company_outside_the_primary_set_is_blocked():
    alert = _alert([
        _company(ticker="ONGC.NS", display_tier="primary"),
        _company(ticker="ASIANPAINT.NS", economic_effect="negative", direction="bearish",
                 display_tier="secondary_ripple", channel_effects=["negative"]),
    ], headline_ticker="ASIANPAINT.NS")

    violations = check_alert_consistency(alert)
    assert any("HEADLINE_NOT_IN_PRIMARY_SET" in v for v in violations)


def test_headline_may_be_a_secondary_company_when_there_is_no_primary():
    """Ruling R1: an indirect-only alert still needs a headline, and the
    secondary set is the honest source for it."""
    alert = _alert([
        _company(ticker="ASIANPAINT.NS", economic_effect="negative", direction="bearish",
                 display_tier="secondary_ripple", channel_effects=["negative"]),
    ], headline_ticker="ASIANPAINT.NS", headline_tier_source="secondary")

    assert check_alert_consistency(alert) == []


def test_headline_outside_the_secondary_set_is_blocked_when_there_is_no_primary():
    alert = _alert([
        _company(ticker="ASIANPAINT.NS", economic_effect="negative", direction="bearish",
                 display_tier="secondary_ripple", channel_effects=["negative"]),
        _company(ticker="INR.NS", display_tier="macro_context"),
    ], headline_ticker="INR.NS")

    violations = check_alert_consistency(alert)
    assert any("HEADLINE_NOT_IN_SECONDARY_SET" in v for v in violations)


def test_a_macro_only_alert_can_have_no_headline_at_all():
    alert = _alert([_company(ticker="INR.NS", display_tier="macro_context")])

    assert check_alert_consistency(alert) == []


def test_a_declared_headline_tier_source_must_match_reality():
    alert = _alert([
        _company(ticker="ONGC.NS", display_tier="primary"),
    ], headline_ticker="ONGC.NS", headline_tier_source="secondary")

    violations = check_alert_consistency(alert)
    assert any("HEADLINE_TIER_SOURCE_MISMATCH" in v for v in violations)


# --- purity + error type ----------------------------------------------------

def test_the_check_does_not_mutate_its_input():
    alert = _alert()
    before = repr(alert)
    check_alert_consistency(alert)
    assert repr(alert) == before


def test_consistency_error_carries_the_violations():
    error = ConsistencyError(["OIL.NS: NET_EFFECT_CONTRADICTION"])

    assert error.violations == ["OIL.NS: NET_EFFECT_CONTRADICTION"]
    assert "NET_EFFECT_CONTRADICTION" in str(error)
    assert isinstance(error, Exception)
