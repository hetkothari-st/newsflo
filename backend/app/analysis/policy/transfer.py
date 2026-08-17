"""TASK 4.1 -- the six transfer functions, as pure functions of floats.

Each takes the modifier's PARAMETERS (from the registry) and the CONTEXT the
channel supplies (the level of the exposed variable before and after the
shock, the size of the move, the company's geography mix) and returns a
MULTIPLIER on the channel's delta.

    modified_delta = raw_delta x factor

A multiplier rather than a subtraction, deliberately: `ChannelResult.evaluate`
applies it inside the closed form, so the Monte Carlo re-evaluates the WHOLE
distribution under the modifier instead of shifting a midpoint that was
computed without it. A levy that caps the upside must narrow the band too.

NOTHING HERE HAS A DEFAULT. A modifier whose parameter is missing, or whose
context the channel cannot supply, raises `TransferInputMissing` and the
caller widens and caps instead of guessing (`transforms.apply_modifiers`).
"Assume the levy threshold is somewhere around the current price" is exactly
the fabrication this phase exists to make impossible.

There is no numeric literal in this module beyond 0 and 1.
`tests/phase4/test_no_fixture_data_reaches_production.py` asserts it: a
capture fraction, a ceiling or a retained share compiled into this file would
be a policy parameter nobody sourced.
"""
from typing import Any, Callable, Mapping

# The six types spec §9.2 names. A seventh would need a transfer function
# here AND a registry entry; `registry.modifier_from_mapping` refuses a type
# this table does not know.
THRESHOLD_CAPTURE = "THRESHOLD_CAPTURE"
HARD_CAP = "HARD_CAP"
STATE_DEPENDENT = "STATE_DEPENDENT"
SUBSIDY_SHARE = "SUBSIDY_SHARE"
FORMULA_PRICING = "FORMULA_PRICING"
REGIONAL_MULTIPLIER = "REGIONAL_MULTIPLIER"

# What each type must be given before it can be applied. Surfaced by the
# registry so an operator can see WHICH number an entry is waiting for.
REQUIRED_PARAMETERS: Mapping[str, tuple[str, ...]] = {
    THRESHOLD_CAPTURE: ("threshold_level", "capture_fraction_above"),
    HARD_CAP: ("cap_level",),
    STATE_DEPENDENT: ("state_key", "when"),
    SUBSIDY_SHARE: ("retained_fraction",),
    FORMULA_PRICING: ("administered_delta_pct",),
    REGIONAL_MULTIPLIER: ("region_multipliers",),
}

# FIX ROUND 1 (M-3). Parameters that are a SHARE OF SOMETHING and therefore
# cannot leave [0, 1]. A `capture_fraction_above` of 1.2 does not mean a
# harsher levy, it means the transfer function returns a NEGATIVE factor and
# silently INVERTS the channel's sign -- a typo in a YAML would become a
# reversed impact call with no error anywhere. The registry refuses such an
# entry at load (`registry.modifier_from_mapping`), which is the earliest
# point at which the mistake is still cheap.
#
# Deliberately NOT bounded, and each for a stated reason:
#   threshold_level / cap_level     a LEVEL in the exposed variable's own
#                                   units. Bounds here would be inventing the
#                                   units.
#   administered_delta_pct          a relative move, legitimately negative and
#                                   legitimately greater than 1. The division
#                                   it feeds is guarded against a zero market
#                                   move in `formula_pricing`.
#   region_multipliers              multipliers, not shares.
FRACTION_PARAMETERS: Mapping[str, tuple[float, float]] = {
    "capture_fraction_above": (0.0, 1.0),
    "retained_fraction": (0.0, 1.0),
}


class TransferInputMissing(LookupError):
    """A parameter or a channel-side input this transfer function needs and
    nobody supplied. The modifier is UNRESOLVABLE; it is never applied on an
    assumed value."""


def _number(source: Mapping[str, Any], name: str, what: str) -> float:
    value = source.get(name)
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TransferInputMissing(
            f"{what} {name!r} is absent or is not a number; the modifier "
            f"cannot be applied and no value may be assumed for it")
    return float(value)


def _levels(context: Mapping[str, Any]) -> tuple[float, float]:
    """The level of the exposed variable before and after the shock.

    A threshold or a ceiling is a statement about a LEVEL (a price per barrel,
    a price per mmbtu), so a channel that only knows the percentage move
    cannot be measured against one. That is a missing input, not a reason to
    infer the level from the move.
    """
    return (_number(context, "level_before", "channel context"),
            _number(context, "level_after", "channel context"))


def threshold_capture(parameters: Mapping[str, Any],
                      context: Mapping[str, Any]) -> float:
    """Above a level, a fraction of the channel transfers away (spec §9.2).

    The fraction of the MOVE that lies above the threshold is what the
    exchequer takes a share of -- not the whole move, and not the whole
    realisation. A move entirely below the threshold is untouched; a move
    entirely above it is captured in full at `capture_fraction_above`.

    Symmetric in direction: a FALL through the threshold is cushioned by the
    same arithmetic, because a levy that takes the upside also absorbs part of
    the downside.
    """
    threshold = _number(parameters, "threshold_level", "modifier parameter")
    capture = _number(parameters, "capture_fraction_above", "modifier parameter")
    before, after = _levels(context)
    low, high = (before, after) if before <= after else (after, before)
    span = high - low
    if span == 0:
        return 1.0
    above = high - max(low, threshold)
    share_above = min(max(above / span, 0.0), 1.0)
    return 1.0 - share_above * capture


def hard_cap(parameters: Mapping[str, Any], context: Mapping[str, Any]) -> float:
    """Channel magnitude clipped at an administered ceiling (spec §9.2).

    Only the part of the move that stays under the ceiling is realisable.
    """
    cap = _number(parameters, "cap_level", "modifier parameter")
    before, after = _levels(context)
    span = after - before
    if span == 0:
        return 1.0
    return (min(after, cap) - min(before, cap)) / span


def state_dependent(parameters: Mapping[str, Any],
                    context: Mapping[str, Any]) -> float:
    """Parameters overridden by a tracked policy state variable (spec §9.2).

    A STATE_DEPENDENT modifier does not scale the channel's output: it
    replaces one of the channel's PARAMETERS (§9.1's `pass_through_override`
    is the spec's own example), which `transforms.apply_modifiers` does before
    the point estimate is taken, so the band is drawn under the override too.
    Its scalar factor is therefore the identity, and it is in this table so
    that "every modifier type has a transfer function" stays true by
    inspection rather than by exception.
    """
    return 1.0


def subsidy_share(parameters: Mapping[str, Any],
                  context: Mapping[str, Any]) -> float:
    """Gain or loss split across parties (spec §9.2). The company keeps
    `retained_fraction` of the channel; the rest lands somewhere else."""
    return _number(parameters, "retained_fraction", "modifier parameter")


def formula_pricing(parameters: Mapping[str, Any],
                    context: Mapping[str, Any]) -> float:
    """Channel replaced by an administered formula (spec §9.2).

    Every §5.1 channel formula is LINEAR in `delta_pct`, so replacing the
    market move with the administered one is exactly a rescaling by their
    ratio. Stated here rather than assumed: if a §5.1 formula ever stops being
    linear in delta, this function stops being correct and must be rewritten
    rather than re-tuned.
    """
    administered = _number(parameters, "administered_delta_pct",
                           "modifier parameter")
    delta = _number(context, "delta_pct", "channel context")
    if delta == 0:
        raise TransferInputMissing(
            "the market move is zero, so there is no ratio by which to "
            "substitute an administered move")
    return administered / delta


def regional_multiplier(parameters: Mapping[str, Any],
                        context: Mapping[str, Any]) -> float:
    """Scaled by geography mix (spec §9.2).

    The mix is a fact about the COMPANY (which states it sells into), so it
    comes from the caller, not from the registry. Absent, the modifier is
    unresolvable -- an even split across states would be a fabricated
    geography.
    """
    multipliers = parameters.get("region_multipliers")
    if not isinstance(multipliers, Mapping) or not multipliers:
        raise TransferInputMissing(
            "modifier parameter 'region_multipliers' is absent or empty")
    mix = context.get("region_mix")
    if not isinstance(mix, Mapping) or not mix:
        raise TransferInputMissing(
            "no geography mix was supplied for this company, and an assumed "
            "one would be fabricated data")

    total = 0.0
    weighted = 0.0
    for region in sorted(mix):
        weight = _number(mix, region, "geography mix")
        if region not in multipliers:
            raise TransferInputMissing(
                f"the geography mix names {region!r} and the modifier has no "
                f"multiplier for it")
        weighted += weight * _number(multipliers, region, "modifier parameter")
        total += weight
    if total == 0:
        raise TransferInputMissing("the geography mix sums to zero")
    return weighted / total


TRANSFER_FUNCTIONS: Mapping[str, Callable[[Mapping[str, Any], Mapping[str, Any]], float]] = {
    THRESHOLD_CAPTURE: threshold_capture,
    HARD_CAP: hard_cap,
    STATE_DEPENDENT: state_dependent,
    SUBSIDY_SHARE: subsidy_share,
    FORMULA_PRICING: formula_pricing,
    REGIONAL_MULTIPLIER: regional_multiplier,
}

MODIFIER_TYPES = tuple(sorted(TRANSFER_FUNCTIONS))


def apply_factor(value: float, factors) -> float:
    """The channel's delta after every applied modifier, in the order the
    caller resolved them (which `transforms.apply_modifiers` sorts by
    `modifier_id`)."""
    for factor in factors:
        value = value * float(factor)
    return value
