"""Verdict tag (docs/NEWS_IMPACT_APP_SPEC.md §4.3). ``is_unconfirmed`` is a
judgment call (rumor/denial classification) supplied by the LLM refinement
layer (a later phase) -- this function only encodes the derivation logic
once that boolean exists; it never classifies text itself."""
from app import config


def compute_verdict(
    *, is_unconfirmed: bool, excess_move_pct: float | None, threshold_pct: float | None = None,
) -> str:
    if is_unconfirmed:
        return "UNCONFIRMED"
    threshold = threshold_pct if threshold_pct is not None else config.VERDICT_EXCESS_THRESHOLD_PCT
    if excess_move_pct is not None and abs(excess_move_pct) >= threshold:
        return "COMPANY_SPECIFIC"
    return "SECTOR_WIDE"
