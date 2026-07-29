"""Composite intensity score (spec v2 §4.2) -- the six-signal blend:
excess, volume, delivery, materiality, vol_norm, fundamental. Pure
functions only -- intensity is derived on read, never persisted as truth
(spec §3.2). Weights and band thresholds live in app.config, never
hardcoded here (spec §11).

Live-feed tier has no fundamental signal, and older MarketMove rows may
lack delivery/materiality/vol_norm -- the weights of whichever signals ARE
present are renormalized to sum to 1 (spec §4.2), so a missing signal is
omitted honestly instead of silently scoring 0.
"""
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
    *,
    excess_move_pct: float,
    excess_peer_group: list[float],
    volume_multiple: float | None = None,
    volume_peer_group: list[float] | None = None,
    delivery_pct: float | None = None,
    materiality: float | None = None,
    materiality_peer_group: list[float] | None = None,
    vol_normalized: float | None = None,
    vol_norm_peer_group: list[float] | None = None,
    fundamental_score: float | None = None,
    weights: dict[str, float] | None = None,
) -> dict:
    """Six-signal composite intensity (spec v2 §4.2). Every signal other
    than excess is optional: a None signal's weight is renormalized away
    across the signals that are present, never counted as zero. Sub-scores
    normalize within the supplied peer group (sector/event scoped by the
    caller). delivery_pct is already 0-100 by definition; fundamental_score
    (ADVISORY tier only) is already 0-100 from the analyst layer.

    Always returns the full component breakdown alongside the score -- the
    UI is required to show it, so this function must never return a bare
    number (spec §4.2: "The score must never be a black box").
    """
    weights = weights or config.INTENSITY_WEIGHTS

    # (key, raw value for display, normalized 0-100 sub-score) -- only
    # signals that genuinely exist for this row.
    signals: list[tuple[str, float, float]] = [
        ("excess", excess_move_pct, normalize_score(excess_move_pct, excess_peer_group)),
    ]
    if volume_multiple is not None:
        signals.append((
            "volume", volume_multiple,
            normalize_score(volume_multiple, volume_peer_group or [volume_multiple]),
        ))
    if delivery_pct is not None:
        signals.append(("delivery", delivery_pct, max(0.0, min(100.0, delivery_pct))))
    if materiality is not None:
        signals.append((
            "materiality", materiality,
            normalize_score(materiality, materiality_peer_group or [materiality]),
        ))
    if vol_normalized is not None:
        signals.append((
            "vol_norm", vol_normalized,
            normalize_score(vol_normalized, vol_norm_peer_group or [vol_normalized]),
        ))
    if fundamental_score is not None:
        signals.append(("fundamental", fundamental_score, max(0.0, min(100.0, fundamental_score))))

    total_weight = sum(weights[key] for key, _raw, _score in signals)

    components = []
    for key, raw, sub_score in signals:
        weight = weights[key] / total_weight  # renormalized so present signals sum to 1
        components.append({
            "label": key,
            "raw": raw,
            "score": round(sub_score),
            "weight": round(weight, 3),
            "contribution": sub_score * weight,
        })
    score = round(sum(c["contribution"] for c in components))
    if score >= config.INTENSITY_BAND_HIGH:
        band = "High"
    elif score >= config.INTENSITY_BAND_MODERATE:
        band = "Moderate"
    else:
        band = "Low"
    return {"score": score, "band": band, "components": components}
