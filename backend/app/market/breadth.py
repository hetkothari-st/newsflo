"""Breadth score (docs/NEWS_IMPACT_APP_SPEC.md §4.4): what fraction of an
event's linked stocks (direct + ripple) showed a meaningful excess move,
normalized 0-100. Pure function -- derived on read, never persisted."""
from app import config


def compute_breadth_score(
    excess_moves: list[float], meaningful_threshold_pct: float | None = None,
) -> int:
    """``excess_moves`` is every linked stock's excess_move_pct for one
    event (direct + ripple). A one-company earnings beat scores low
    breadth; a sector-wide event where most linked stocks moved
    meaningfully scores high (spec §4.4)."""
    threshold = (
        meaningful_threshold_pct
        if meaningful_threshold_pct is not None
        else config.BREADTH_MEANINGFUL_MOVE_PCT
    )
    if not excess_moves:
        return 0
    meaningful = sum(1 for m in excess_moves if abs(m) >= threshold)
    return round(meaningful / len(excess_moves) * 100)
