"""Budget exhaustion must never mark an unverified candidate verified
(provider-migration spec section 13 / self-audit Q11). The engine paths that
consult budget.exceeded set router.quality='budget_exhausted' and stop
expansion -- verification skips produce REJECT/unverified, never verified.

Also covers provider-specific COST semantics: Gemini's promptTokenCount
includes the cached slice, Anthropic's input_tokens excludes it. Pricing the
second with the first's arithmetic billed warm-cache input at $0 and never
billed cache writes at all.
"""
import pytest

from app.analysis.impact_graph.budget import (
    ArticleBudget, _estimate_cost, _estimate_cost_anthropic,
)


def test_exceeded_budget_flags_without_verifying():
    budget = ArticleBudget(article_id=1, max_input_override=10, max_output_override=10)
    budget.record("expand", input_tokens=1000, output_tokens=1000, model=None)
    assert budget.exceeded is True
    assert budget.expansion_exhausted is True


# --- provider cost semantics -------------------------------------------

def test_gemini_path_unchanged_still_subtracts_the_cached_slice():
    """Regression fence for the byte-identical Gemini path: promptTokenCount
    INCLUDES cachedContentTokenCount, so 1000 prompt tokens of which 800 were
    cached bills 200 at input rate + 800 at cache_read rate. gemini-3.6-flash
    has no cache_read price, so cached tokens fall back to the input rate --
    which for this model makes the total identical to pricing all 1000 as
    input. That fallback is the pre-existing, intended behaviour."""
    cost = _estimate_cost("gemini-3.6-flash", 1000, 100, 800)
    assert cost == pytest.approx(200 / 1e6 * 0.30 + 800 / 1e6 * 0.30 + 100 / 1e6 * 2.50)
    # And with a priced cache_read the discount is real (opus pricing borrowed
    # only to exercise the branch): 200 full + 800 discounted.
    cost_priced = _estimate_cost("claude-opus-5", 1000, 100, 800)
    assert cost_priced == pytest.approx(200 / 1e6 * 5.0 + 800 / 1e6 * 0.5 + 100 / 1e6 * 25.0)


def test_anthropic_path_bills_three_disjoint_input_buckets():
    """No subtraction anywhere: input at full rate, cache reads at the
    cache_read rate, cache writes at 1.25x input."""
    cost = _estimate_cost_anthropic("claude-opus-5", 500, 340, 3000, 200)
    expected = (500 / 1e6 * 5.0 + 3000 / 1e6 * 0.5
                + 200 / 1e6 * 6.25 + 340 / 1e6 * 25.0)
    assert cost == pytest.approx(expected)


def test_anthropic_warm_cache_never_prices_billed_input_at_zero():
    """The precise bug: under Gemini arithmetic, input=500 with cache_read=3000
    yields max(0, 500-3000)=0 full-priced tokens -- the billed input vanishes
    and the cache write is billed nowhere. The Anthropic path must charge
    strictly more than the Gemini path would for the same usage."""
    gemini_style = _estimate_cost("claude-opus-5", 500, 340, 3000)
    anthropic_style = _estimate_cost_anthropic("claude-opus-5", 500, 340, 3000, 200)
    assert gemini_style < anthropic_style
    # ...and the difference is exactly the unbilled input + the unbilled write.
    assert anthropic_style - gemini_style == pytest.approx(
        500 / 1e6 * 5.0 + 200 / 1e6 * 6.25)


def test_anthropic_unpriced_model_contributes_zero():
    assert _estimate_cost_anthropic("no-such-model", 500, 340, 3000, 200) == 0.0


def test_budget_record_semantics_switch_selects_the_right_arithmetic():
    gemini_budget = ArticleBudget(article_id=1)
    gemini_budget.record("s", input_tokens=1000, output_tokens=100,
                         cached_tokens=800, model="claude-opus-5")
    assert gemini_budget.estimated_cost_usd == pytest.approx(
        _estimate_cost("claude-opus-5", 1000, 100, 800))

    claude_budget = ArticleBudget(article_id=1)
    claude_budget.record("s", input_tokens=500, output_tokens=340,
                         cached_tokens=3000, cache_write_tokens=200,
                         model="claude-opus-5", semantics="anthropic")
    assert claude_budget.estimated_cost_usd == pytest.approx(
        _estimate_cost_anthropic("claude-opus-5", 500, 340, 3000, 200))
    # Token ledger is unchanged by the semantics flag: input stays the plain
    # sum of what the call reported (documented limitation, not a bug).
    assert claude_budget.input_tokens == 500
    assert claude_budget.cached_tokens == 3000
