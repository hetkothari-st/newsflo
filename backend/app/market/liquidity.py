"""Liquidity tier (spec v2 §4.6): derived from the stock's 20-day average
traded value (MarketMove.avg_traded_value), never stored as fixed truth
(spec §3.2). Critical for small/micro caps: low liquidity means moves are
amplified and exiting is hard -- a risk cue, not decoration (spec §6).
Thresholds live in app.config (spec §11)."""
from app import config


def compute_liquidity_tier(avg_traded_value: float | None) -> str | None:
    """LOW / MODERATE / HIGH from average traded value, or None when the
    input is unavailable (omit rather than invent -- the UI simply shows
    no liquidity tag for such a row)."""
    if avg_traded_value is None:
        return None
    if avg_traded_value >= config.LIQUIDITY_HIGH_AVG_TRADED_VALUE:
        return "HIGH"
    if avg_traded_value >= config.LIQUIDITY_MODERATE_AVG_TRADED_VALUE:
        return "MODERATE"
    return "LOW"
