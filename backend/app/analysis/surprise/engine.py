"""TASK 5.4 -- the Surprise record (spec §14).

    consensus_gap_sigma, forward_curve_implied, novelty_score,
    dissemination_stage, first_seen_at, latency_ms_from_first_seen,
    information_value

WHAT AXIS C IS ALLOWED TO DO: rank a feed, badge an item ALREADY WIDELY
REPORTED, and raise the ALREADY_PRICED objection at WARN. Nothing else. It
never alters direction or materiality, and the import graph is what enforces
that (see the package docstring).

NONE MEANS MISSING. There is no consensus feed and no forward-curve feed in
this repo. `consensus_gap_sigma` and `forward_curve_implied` are computed only
when the caller supplies the inputs; otherwise they are None and the composite
RENORMALISES over what is known. Scoring a missing consensus as zero surprise
would quietly demote every event nobody has an estimate for.

CLOCKLESS. Every timestamp arrives as an argument, so a latency figure is a
measurement rather than an artefact of when the code ran.
"""
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from app.analysis.surprise.config import SurpriseConfig, load_surprise_config
from app.analysis.surprise.novelty import novelty_score

EARLY = "EARLY"
SPREADING = "SPREADING"
SATURATED = "SATURATED"

OBJECTION_TYPE = "ALREADY_PRICED"
OBJECTION_SEVERITY = "WARN"          # §12.1: visible, and publishes anyway


@dataclass(frozen=True)
class Surprise:
    consensus_gap_sigma: float | None    # (actual - consensus) / sigma
    forward_curve_implied: float | None  # fraction already in futures pre-event
    novelty_score: float                 # 1 - max cosine to prior 7d events
    dissemination_stage: str             # EARLY | SPREADING | SATURATED
    first_seen_at: datetime
    latency_ms_from_first_seen: int
    information_value: float             # config-weighted composite


def latency_ms(first_seen_at: datetime, published_at: datetime) -> int:
    """The product's core SLO input (§14), in milliseconds. Negative spans are
    clamped to zero rather than reported: a publish stamped before its own
    first-seen is a clock problem, not a negative latency."""
    delta = (published_at - first_seen_at).total_seconds()
    return int(max(delta, 0.0) * 1000)


def dissemination_stage(*, source_count: int,
                        minutes_since_first_seen: float,
                        config: SurpriseConfig | None = None) -> str:
    """Source count x time since first report (§14).

    EITHER axis can advance the stage: twenty outlets in five minutes is
    saturated, and so is one outlet nine hours ago. Requiring both would call a
    story that everybody ran instantly "early".
    """
    config = config or load_surprise_config()
    if (source_count >= config.saturated_min_sources
            or minutes_since_first_seen >= config.saturated_min_minutes):
        return SATURATED
    if (source_count >= config.spreading_min_sources
            or minutes_since_first_seen >= config.spreading_min_minutes):
        return SPREADING
    return EARLY


def already_widely_reported(stage: str) -> bool:
    """The badge. A pure function of the stage, so the badge and the field can
    never disagree."""
    return str(stage) == SATURATED


def consensus_gap_sigma(*, actual: float | None, expected: float | None,
                        sigma: float | None) -> float | None:
    """`(actual - consensus) / sigma`, or None when any input is missing.

    None is the answer for almost every event this system sees, and that is
    the honest one: nobody has supplied a consensus feed.
    """
    if actual is None or expected is None or sigma is None or float(sigma) == 0:
        return None
    return (float(actual) - float(expected)) / float(sigma)


def information_value(*, novelty: float, consensus_gap: float | None,
                      forward_curve: float | None, stage: str,
                      config: SurpriseConfig | None = None) -> float:
    """The config-weighted composite, renormalised over KNOWN components."""
    config = config or load_surprise_config()
    stage_value = {EARLY: 1.0, SPREADING: 0.5, SATURATED: 0.0}.get(str(stage), 0.0)

    components: list[tuple[str, float]] = [
        ("novelty", max(0.0, min(1.0, float(novelty)))),
        ("dissemination", stage_value),
    ]
    if consensus_gap is not None:
        components.append((
            "consensus_gap",
            min(abs(float(consensus_gap)) / config.consensus_sigma_cap, 1.0)))
    if forward_curve is not None:
        # Already in the curve => less information left in the event.
        components.append(
            ("forward_curve", max(0.0, min(1.0, 1.0 - float(forward_curve)))))

    total_weight = sum(config.weights.get(name, 0.0) for name, _ in components)
    if total_weight <= 0:                              # pragma: no cover
        return 0.0
    return sum(config.weights.get(name, 0.0) * value
               for name, value in components) / total_weight


def compute_surprise(*, event_text: str, prior_texts: Sequence[str] = (),
                     first_seen_at: datetime, published_at: datetime,
                     source_count: int = 1,
                     forward_curve_implied: float | None = None,
                     consensus_actual: float | None = None,
                     consensus_expected: float | None = None,
                     consensus_sigma: float | None = None,
                     config: SurpriseConfig | None = None) -> Surprise:
    """The whole record, from inputs the caller supplies."""
    config = config or load_surprise_config()
    elapsed_minutes = max((published_at - first_seen_at).total_seconds(), 0.0) / 60
    stage = dissemination_stage(source_count=source_count,
                                minutes_since_first_seen=elapsed_minutes,
                                config=config)
    novelty = novelty_score(event_text, prior_texts, config=config)
    gap = consensus_gap_sigma(actual=consensus_actual,
                              expected=consensus_expected,
                              sigma=consensus_sigma)
    return Surprise(
        consensus_gap_sigma=gap,
        forward_curve_implied=(None if forward_curve_implied is None
                               else float(forward_curve_implied)),
        novelty_score=novelty,
        dissemination_stage=stage,
        first_seen_at=first_seen_at,
        latency_ms_from_first_seen=latency_ms(first_seen_at, published_at),
        information_value=information_value(
            novelty=novelty, consensus_gap=gap,
            forward_curve=forward_curve_implied, stage=stage, config=config))


def already_priced_objection(surprise: Surprise, *, objection_id: str,
                             config: SurpriseConfig | None = None
                             ) -> Mapping[str, Any] | None:
    """The ALREADY_PRICED objection, at WARN.

    Raised ONLY on a known forward-curve reading. An unknown curve raises
    nothing: "we do not know whether this was priced" is not "this was
    priced", and an objection asserted on an absent input would be exactly the
    fabricated criticism the falsification stage is supposed to avoid.
    """
    config = config or load_surprise_config()
    implied = surprise.forward_curve_implied
    if implied is None or float(implied) < config.already_priced_forward_curve_min:
        return None
    return {
        "objection_id": objection_id,
        "type": OBJECTION_TYPE,
        "severity": OBJECTION_SEVERITY,
        "sustained": True,
    }


def serialize_surprise(surprise: Surprise) -> dict:
    """JSON-safe. Emitted alongside an event, never inside the fundamental
    block -- a surprise field next to a direction is how Axis C starts looking
    like an input to it."""
    payload = asdict(surprise)
    payload["first_seen_at"] = surprise.first_seen_at.isoformat()
    payload["already_widely_reported"] = already_widely_reported(
        surprise.dissemination_stage)
    return payload
