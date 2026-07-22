"""Composite intensity score (docs/NEWS_IMPACT_APP_SPEC.md §4.2). Pure
functions only -- intensity is derived on read, never persisted as truth
(spec §3.2). Weights and band thresholds live in app.config, never
hardcoded here (spec §10)."""
from app import config


def normalize_score(value: float, peer_values: list[float]) -> float:
    """Min-max normalize |value| against the |peer_values| population to a
    0-100 score. ``peer_values`` must be the within-sector or within-event
    peer group (spec §4.2: "normalize within sector or event, not
    globally") -- never a global population. A degenerate group (single
    member, or every peer equal) returns 100 -- the value IS the max there
    is, no meaningful "less than" exists to compare it against.
    """
    peers = [abs(v) for v in peer_values]
    value = abs(value)
    lo, hi = min(peers), max(peers)
    if hi == lo:
        return 100.0
    return max(0.0, min(100.0, (value - lo) / (hi - lo) * 100))


def compute_intensity(
    *, excess_move_pct: float, excess_peer_group: list[float],
    volume_multiple: float, volume_peer_group: list[float],
    breadth_score: float, weights: dict[str, float] | None = None,
) -> dict:
    """Live-feed intensity (spec §4.2): 0.55*excess + 0.25*volume +
    0.20*breadth by default (app.config.INTENSITY_WEIGHTS_LIVE), overridable
    via ``weights`` for testing/retuning. Always returns the full component
    breakdown alongside the score -- the UI is required to show it, so this
    function must never return a bare number (spec §4.2, §10).
    """
    weights = weights or config.INTENSITY_WEIGHTS_LIVE
    excess_score = normalize_score(excess_move_pct, excess_peer_group)
    volume_score = normalize_score(volume_multiple, volume_peer_group)
    breadth_component = max(0.0, min(100.0, breadth_score))

    components = [
        {
            "label": "excess", "raw": excess_move_pct, "weight": weights["excess"],
            "contribution": excess_score * weights["excess"],
        },
        {
            "label": "volume", "raw": volume_multiple, "weight": weights["volume"],
            "contribution": volume_score * weights["volume"],
        },
        {
            "label": "breadth", "raw": breadth_score, "weight": weights["breadth"],
            "contribution": breadth_component * weights["breadth"],
        },
    ]
    score = round(sum(c["contribution"] for c in components))
    if score >= config.INTENSITY_BAND_HIGH:
        band = "High"
    elif score >= config.INTENSITY_BAND_MODERATE:
        band = "Moderate"
    else:
        band = "Low"
    return {"score": score, "band": band, "components": components}
