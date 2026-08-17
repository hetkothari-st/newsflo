"""TASK 4.2 -- application order.

    "Modifiers run AFTER channel computation and BEFORE net-effect
     resolution. Never LLM-applied. Deterministic ordering by
     `modifier_id`."  -- phase file Task 4.2

The phase file's own pseudocode, implemented literally:

    for mod in registry.active_for(channel.exposure_tag, as_of_date):
        if mod.requires_state and policy_state.is_unknown_or_stale(mod.state_key):
            channel.widen_uncertainty(config.unknown_regime_multiplier)
            channel.cap_evidence_grade("C")
            channel.add_note(f"regime state unknown: {mod.state_key}")
            continue
        channel = mod.transform(channel, policy_state)
        applied.append(mod.modifier_id)

THREE THINGS THIS MODULE REFUSES TO DO.

  1. IT NEVER ASSUMES A REGIME. An unknown or stale state widens the band by
     the configured multiplier and caps evidence at C. It does not fall back
     to "the last known state", which would be the same guess with a longer
     paper trail.
  2. IT NEVER APPLIES A MODIFIER ON A MISSING INPUT. A THRESHOLD_CAPTURE with
     no level to compare against, or a REGIONAL_MULTIPLIER with no geography
     mix, is UNRESOLVED -- recorded, widened and capped exactly like an
     unknown regime, never applied on an inferred level.
  3. IT NEVER DROPS ANYTHING SILENTLY. Applied, unknown-state, unresolved and
     not-triggered are four different outcomes and all four reach the payload,
     because "we modelled the levy and could not size it" and "there is no
     levy" are different sentences.

PURE. No I/O, no clock, no randomness, no model. Determinism is by
construction: channels are walked in `channel_id` order and modifiers in
`modifier_id` order, and `tests/phase4/test_policy_modifiers.py` offers the
same registry in both orders and compares the output.

TWO THINGS ABOUT THAT ORDERING THAT ARE EASY TO MISREAD (fix round 1, M-6/M-7).

  * `channel.channel_id` IS the exposure tag. `channels._build` sets
    `channel_id=exposure.exposure_tag`, which is why `registry.active_for` can
    be handed `channel.channel_id` directly. It also means TWO EXPOSURE ROWS
    ON THE SAME TAG produce two channels with the SAME `channel_id`, so the
    `sorted(..., key=channel_id)` below is not a total order over them. Python's
    sort is stable, so their relative order is the CALLER'S -- and that is
    harmless HERE because each channel is transformed independently and the
    output list is consumed by `simulate`, which sorts by `channel_id` itself
    and sums in that fixed order. It would stop being harmless the moment a
    modifier read state across channels, so: do not add cross-channel state to
    this loop without giving `ChannelResult` a genuinely unique id first.
  * MODIFIER ORDER DOES NOT CHANGE THE NUMBER, and not because multiplication
    commutes. Scaling modifiers contribute FACTORS that are all applied at the
    end (`ChannelResult.evaluate`), and STATE_DEPENDENT modifiers replace
    PARAMETERS in a map. The point estimate is computed once, from the final
    map and the final factor list. What order DOES decide is which of two
    STATE_DEPENDENT modifiers overriding the SAME parameter wins -- and that
    is settled by `modifier_id`, deterministically. Pinned by
    `test_a_parameter_override_and_a_scaling_modifier_commute`.
"""
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Sequence

from app.analysis.policy.registry import PolicyModifier, PolicyRegistry
from app.analysis.policy.state import PolicyStateStore
from app.analysis.policy.transfer import TRANSFER_FUNCTIONS, TransferInputMissing
from app.analysis.sensitivity.channels import (
    AppliedModifier, ChannelResult, weakest_grade_cap,
)
from app.analysis.sensitivity.config import MaterialityConfig, load_materiality_config
from app.analysis.sensitivity.params import ParamDist

# The evidence grade an unknown or unresolvable regime allows. Spec §9.3
# states it as a letter, not as a policy knob, so it is a constant here
# rather than a line in a YAML nobody would ever change.
UNKNOWN_REGIME_GRADE_CAP = "C"

STATUS_APPLIED = "APPLIED"
STATUS_UNKNOWN_STATE = "UNKNOWN_STATE"
STATUS_UNRESOLVED = "UNRESOLVED"
STATUS_NOT_TRIGGERED = "NOT_TRIGGERED"


@dataclass(frozen=True)
class ModifiedChannels:
    """What `apply_modifiers` returns: the channels, and an honest account of
    every modifier that was considered."""
    channels: tuple[ChannelResult, ...]
    applied: tuple[str, ...]
    unknown_state: tuple[str, ...]
    unresolved: tuple[str, ...]
    not_triggered: tuple[str, ...]
    stale_state_keys: tuple[str, ...]
    detail: tuple[Mapping[str, Any], ...]

    def as_payload(self) -> list[dict]:
        """The list that rides on the CHANNEL signal and becomes the UI's
        chips (Task 4.4)."""
        return [dict(entry) for entry in self.detail]


def _widen(dist: ParamDist, multiplier: float,
           config: MaterialityConfig) -> ParamDist:
    """Widen a parameter's band without moving its point.

    An unknown regime does not make a number wrong, it makes it less known --
    so the point estimate is untouched and only the belief around it grows.
    Clipped to the parameter's own domain bounds, because a pass-through of
    1.4 is not a wider belief, it is a meaningless one.
    """
    low = dist.point - (dist.point - dist.lo) * multiplier
    high = dist.point + (dist.hi - dist.point) * multiplier
    bounds = config.param_bounds.get(dist.name)
    if bounds is not None:
        low = min(max(low, bounds[0]), bounds[1])
        high = min(max(high, bounds[0]), bounds[1])
    return ParamDist(name=dist.name, point=dist.point, lo=low, hi=high,
                     dist=dist.dist, source=dist.source,
                     evidence_id=dist.evidence_id)


def _channel_context(channel: ChannelResult,
                     region_mix: Mapping[str, float] | None) -> dict:
    return {"level_before": channel.level_before,
            "level_after": channel.level_after,
            "delta_pct": channel.constants.get("delta_pct"),
            "region_mix": region_mix}


def _override_params(channel: ChannelResult, overrides: Mapping[str, Any],
                     modifier: PolicyModifier) -> dict:
    """Replace a channel parameter with an ADMINISTERED value.

    The override has no band: an administered zero is not an uncertain zero,
    it is what the notification says. Its `source` records where it came from
    -- the modifier id -- so the provenance of the number in the record is the
    notification rather than the disclosure it displaced.
    """
    params = dict(channel.params)
    for name, value in sorted(overrides.items()):
        if name not in params or value is None:
            continue
        point = float(value)
        params[name] = ParamDist(
            name=name, point=point, lo=point, hi=point,
            dist=params[name].dist, source="ADMINISTERED",
            evidence_id=modifier.modifier_id)
    return params


def _rebuilt(channel: ChannelResult, *, params=None, grade_cap=None,
             modifiers=None, notes=None) -> ChannelResult:
    """A new `ChannelResult` with the modifier's effects folded in, and its
    point estimate recomputed under them.

    FIX ROUND 1 (I-2). `param_sources` is DERIVED FROM `params` here rather
    than carried over. It used to be carried over, so a STATE_DEPENDENT
    override replaced a parameter with an ADMINISTERED value while the
    channel's own provenance map went on saying DISCLOSED_CALL -- a
    field-level contradiction inside one record, in exactly the field a reader
    consults to ask "where did this number come from", and the same class of
    defect this phase exists to make impossible. The two are now one
    projection of one map and cannot disagree.
    """
    params = params if params is not None else channel.params
    rebuilt = ChannelResult(**{
        **channel.__dict__,
        "params": params,
        "param_sources": {name: dist.source for name, dist in params.items()},
        "grade_cap": grade_cap if grade_cap is not None else channel.grade_cap,
        "modifiers": modifiers if modifiers is not None else channel.modifiers,
        "policy_notes": notes if notes is not None else channel.policy_notes,
    })
    point = rebuilt.evaluate({name: dist.point
                              for name, dist in rebuilt.params.items()})
    return ChannelResult(**{**rebuilt.__dict__, "delta_ebitda_inr": point})


def apply_modifiers(channels: Sequence[ChannelResult], *, as_of_date: date,
                    policy_state: PolicyStateStore, registry: PolicyRegistry,
                    region_mix: Mapping[str, float] | None = None,
                    config: MaterialityConfig | None = None) -> ModifiedChannels:
    """Run every registered modifier that is in force on `as_of_date` over
    every channel whose exposure tag it names."""
    config = config or load_materiality_config()
    multiplier = config.unknown_modifier_band_multiplier

    out: list[ChannelResult] = []
    applied: list[str] = []
    unknown_state: list[str] = []
    unresolved: list[str] = []
    not_triggered: list[str] = []
    state_keys_seen: list[str] = []
    detail: dict[str, Mapping[str, Any]] = {}

    for channel in sorted(channels, key=lambda c: c.channel_id):
        params = dict(channel.params)
        grade_cap = channel.grade_cap
        acting: list[AppliedModifier] = []
        notes: list[str] = list(channel.policy_notes)

        for modifier in registry.active_for(channel.channel_id, as_of_date):
            if modifier.requires_state:
                key = modifier.state_key
                if key:
                    state_keys_seen.append(key)
                reason = (policy_state.unknown_reason(
                    key, as_of=as_of_date, horizon_days=channel.horizon_days)
                    if key else "ABSENT")
                if reason is not None:
                    note = (f"regime state unknown ({reason}): {key} "
                            f"[{modifier.modifier_id}]")
                    notes.append(note)
                    params = {name: _widen(dist, multiplier, config)
                              for name, dist in params.items()}
                    grade_cap = weakest_grade_cap(
                        (grade_cap, UNKNOWN_REGIME_GRADE_CAP))
                    unknown_state.append(modifier.modifier_id)
                    detail[modifier.modifier_id] = modifier.as_chip(
                        STATUS_UNKNOWN_STATE, note)
                    continue

                branch = (modifier.parameters.get("when") or {}).get(
                    policy_state.state_of(key))
                if not branch:
                    # The state is KNOWN and the modifier says nothing about
                    # it. Nothing fired, and nothing is uncertain -- but the
                    # user is still told the levy was considered.
                    not_triggered.append(modifier.modifier_id)
                    detail[modifier.modifier_id] = modifier.as_chip(
                        STATUS_NOT_TRIGGERED,
                        f"{key} = {policy_state.state_of(key)}")
                    continue
                params = _override_params(
                    ChannelResult(**{**channel.__dict__, "params": params}),
                    branch.get("param_overrides") or {}, modifier)

            try:
                factor = TRANSFER_FUNCTIONS[modifier.modifier_type](
                    modifier.parameters, _channel_context(channel, region_mix))
            except TransferInputMissing as exc:
                note = f"{modifier.modifier_id} could not be sized: {exc}"
                notes.append(note)
                params = {name: _widen(dist, multiplier, config)
                          for name, dist in params.items()}
                grade_cap = weakest_grade_cap((grade_cap, UNKNOWN_REGIME_GRADE_CAP))
                unresolved.append(modifier.modifier_id)
                detail[modifier.modifier_id] = modifier.as_chip(
                    STATUS_UNRESOLVED, str(exc))
                continue

            acting.append(AppliedModifier(
                modifier_id=modifier.modifier_id,
                modifier_type=modifier.modifier_type, factor=float(factor)))
            applied.append(modifier.modifier_id)
            detail[modifier.modifier_id] = modifier.as_chip(STATUS_APPLIED)

        if not acting and params == channel.params and grade_cap == channel.grade_cap \
                and tuple(notes) == channel.policy_notes:
            out.append(channel)
            continue
        out.append(_rebuilt(channel, params=params, grade_cap=grade_cap,
                            modifiers=tuple(acting), notes=tuple(notes)))

    return ModifiedChannels(
        channels=tuple(out),
        applied=tuple(sorted(set(applied))),
        unknown_state=tuple(sorted(set(unknown_state))),
        unresolved=tuple(sorted(set(unresolved))),
        not_triggered=tuple(sorted(set(not_triggered))),
        stale_state_keys=policy_state.stale_keys(state_keys_seen, as_of=as_of_date),
        detail=tuple(detail[key] for key in sorted(detail)))
