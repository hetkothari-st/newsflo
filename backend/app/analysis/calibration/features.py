"""TASK 5.3 -- the feature vector (spec §13.2).

    materiality_p50, band_width, sign_consistency, graph_distance, directness,
    evidence_grade, weakest_link_kind, n_bound_claims, param_proxy_fraction,
    empirical_status, empirical_n, empirical_p, objection counts by severity,
    event_status, shock_magnitude_confidence, surprise_score, sector_id,
    exposure_freshness_days

ALL DETERMINISTIC, NO LLM SCORE. Every entry is a number this system computed
or a category it assigned from a controlled vocabulary. There is no "the model
thought this was strong" input, which is the entire reason the old confidence
number was worthless.

UNKNOWN STAYS None. A feature nobody computed is not zero -- a zero band width
is a claim of perfect precision, and a zero graph distance is a claim of
identity. `vectorize` REFUSES an incomplete vector rather than imputing, so a
candidate the model has never seen the shape of cannot be scored by accident.

ORDINAL ENCODINGS ARE STATED HERE, ONCE. They are monotone in "how much this
should raise confidence", which is the only property an isotonic fit needs.
"""
from typing import Any, Mapping, Sequence

FEATURE_NAMES = (
    "materiality_p50", "band_width", "sign_consistency", "graph_distance",
    "directness", "evidence_grade", "weakest_link_kind", "n_bound_claims",
    "param_proxy_fraction", "empirical_status", "empirical_n", "empirical_p",
    "objection_count_blocking", "objection_count_major", "objection_count_warn",
    "event_status", "shock_magnitude_confidence", "surprise_score",
    "sector_id", "exposure_freshness_days",
)

# Higher = should support a stronger claim. CONFLICT is NEGATIVE on purpose:
# measured history disagreeing is worse than measured history being absent.
EMPIRICAL_STATUS_ORDINAL = {"AGREE": 2.0, "WEAK": 1.0, "NO_DATA": 0.0,
                            "CONFLICT": -1.0}
DIRECTNESS_ORDINAL = {"DIRECT": 3.0, "INDIRECT": 2.0, "REMOTE": 1.0}
EVIDENCE_GRADE_ORDINAL = {"A": 5.0, "B": 4.0, "C": 3.0, "D": 2.0, "E": 1.0}
BINDING_ORDINAL = {"BOUND": 3.0, "SECTOR_PROXY": 2.0, "UNBOUND": 1.0}
EVENT_STATUS_ORDINAL = {"OFFICIAL": 3.0, "CONFIRMED": 2.0, "RUMOUR": 1.0}


class FeatureUnavailable(ValueError):
    """A feature the model needs is not known for this candidate.

    Raised rather than imputed. An imputed feature is a fabricated input to a
    probability somebody will read as measured.
    """


def _band(impact: Any) -> Mapping[str, Any] | None:
    block = getattr(impact, "sensitivity", None)
    if not block:
        return None
    return (block.get("delta_ebitda_pct") or None)


def _param_proxy_fraction(impact: Any) -> float | None:
    """The share of ATTRIBUTED VARIANCE that rests on a sector-median
    parameter. None when no driver attribution exists."""
    block = getattr(impact, "sensitivity", None)
    drivers = (block or {}).get("driver_ranking") if block else None
    if not drivers:
        return None
    total = 0.0
    proxy = 0.0
    for driver in drivers:
        try:
            contribution = float(driver.get("contribution", 0.0))
        except (TypeError, ValueError):               # pragma: no cover
            continue
        total += contribution
        if str(driver.get("source")) == "SECTOR_PROXY":
            proxy += contribution
    return (proxy / total) if total > 0 else None


def _objection_counts(impact: Any) -> dict[str, float]:
    counts = {"BLOCKING": 0.0, "MAJOR": 0.0, "WARN": 0.0}
    for objection in getattr(impact, "objections", ()) or ():
        if not objection.get("sustained"):
            continue
        severity = str(objection.get("severity", "WARN"))
        if severity in counts:
            counts[severity] += 1.0
    return counts


def build_features(impact: Any, *, empirical: Any = None,
                   surprise_score: float | None = None,
                   sector_id: float | None = None,
                   exposure_freshness_days: float | None = None,
                   event_status: str | None = None,
                   shock_magnitude_confidence: float | None = None
                   ) -> Mapping[str, float | None]:
    """`{feature name: value or None}`, in the spec's order.

    Everything the canonical record knows is read off it. Everything it does
    not know (the event's status, the sector id, the surprise score, the
    exposure's age) is an argument, and stays None when the caller does not
    supply it.
    """
    band = _band(impact)
    counts = _objection_counts(impact)
    weakest = str(getattr(impact, "weakest_link", "") or "").rsplit(":", 1)[-1]
    bindings = getattr(impact, "claim_bindings", ()) or ()

    return {
        "materiality_p50": (None if not band else _float(band.get("p50"))),
        "band_width": (None if not band or band.get("p90") is None
                       or band.get("p10") is None
                       else float(band["p90"]) - float(band["p10"])),
        "sign_consistency": _float(getattr(impact, "sign_consistency", None)),
        "graph_distance": _float(getattr(impact, "graph_distance", None)),
        "directness": DIRECTNESS_ORDINAL.get(
            str(getattr(impact, "directness", "") or "")),
        "evidence_grade": EVIDENCE_GRADE_ORDINAL.get(
            str(getattr(impact, "evidence_grade", "") or "")),
        "weakest_link_kind": BINDING_ORDINAL.get(weakest),
        "n_bound_claims": float(sum(
            1 for b in bindings if str(b.get("binding_status")) == "BOUND")),
        "param_proxy_fraction": _param_proxy_fraction(impact),
        "empirical_status": EMPIRICAL_STATUS_ORDINAL.get(
            str(getattr(impact, "empirical_status", "") or "")),
        "empirical_n": _float(getattr(empirical, "n_events", None)),
        "empirical_p": _float(getattr(empirical, "p_value", None)),
        "objection_count_blocking": counts["BLOCKING"],
        "objection_count_major": counts["MAJOR"],
        "objection_count_warn": counts["WARN"],
        "event_status": EVENT_STATUS_ORDINAL.get(str(event_status or "")),
        "shock_magnitude_confidence": _float(shock_magnitude_confidence),
        "surprise_score": _float(surprise_score),
        "sector_id": _float(sector_id),
        "exposure_freshness_days": _float(exposure_freshness_days),
    }


def _float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):                   # pragma: no cover
        return None


def vectorize(features: Mapping[str, float | None],
              names: Sequence[str] = FEATURE_NAMES) -> tuple[float, ...]:
    """The ordered tuple a model consumes. REFUSES an incomplete vector."""
    missing = [name for name in names if features.get(name) is None]
    if missing:
        raise FeatureUnavailable(
            f"{len(missing)} feature(s) are not known for this candidate: "
            f"{missing}. They are not imputed -- a probability computed on an "
            "invented input is worse than no probability.")
    return tuple(float(features[name]) for name in names)
