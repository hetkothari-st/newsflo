from app import config
from app.market.liquidity import compute_liquidity_tier


def test_high_tier_at_threshold():
    assert compute_liquidity_tier(config.LIQUIDITY_HIGH_AVG_TRADED_VALUE) == "HIGH"


def test_moderate_tier_between_thresholds():
    assert compute_liquidity_tier(config.LIQUIDITY_MODERATE_AVG_TRADED_VALUE) == "MODERATE"


def test_low_tier_below_moderate():
    assert compute_liquidity_tier(config.LIQUIDITY_MODERATE_AVG_TRADED_VALUE - 1) == "LOW"


def test_none_input_returns_none():
    # Omit rather than invent -- no traded-value data means no tag.
    assert compute_liquidity_tier(None) is None
