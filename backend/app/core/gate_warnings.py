"""The partial-rollout alarm for the gate's `unknown_*` escapes.

WHY THIS EXISTS (V5 Phase 3, review round 1, I3).

`config/gates.yaml` states, per tier, what an ABSENT input means. Four of
those keys were set fail-CLOSED by Phase 0. Two -- `unknown_materiality_delta_
passes` and `unknown_sector_proxy_passes` -- are currently fail-OPEN, because
no computed band and no parameter provenance reach a draft on the V4-fed
canonical path and closing them would reject everything.

That is correct today and dangerous the moment it stops being true. The
hazard is not the flag, it is the PARTIAL rollout: once the sensitivity
engine feeds SOME drafts, a band-less draft clears the PRIMARY materiality
floor and the PRIMARY sector-proxy ban IN SILENCE, sitting in the same feed
as drafts that had to earn it, and nothing distinguishes them. A wrong
number is recoverable; a wrong number nobody can tell apart from a right one
is not.

So the escape is recorded on the rule (`GateRule.unknown_escape`) and this
module shouts about it -- at PRIMARY only. A ripple already admits weaker
evidence by design, and warning on every ripple would be noise that trains
people to ignore the warning that matters.

DELIBERATELY IMPURE, and deliberately NOT imported by `gates.py`: logging is
a side effect and the gate is pure (`tests/phase0/test_reducer_purity.py`).
This is the same separation `config_loader.py` and `impact_writer.py` have.
"""
import logging
from typing import Iterable, Mapping, Sequence

logger = logging.getLogger("newsflo.gate")

# Where the reader is sent. The flip is a numbered checklist item, not a
# paragraph somebody has to find.
CUTOVER_REFERENCE = "V5 SERVING CUTOVER CHECKLIST (DATA_GAPS.md)"

TIER_PRIMARY = "PRIMARY"


def _rule_view(rule) -> tuple[str, str, bool]:
    """Accept either a `GateRule` or the serialized dict the reducer persists
    on `company_impact.gate_trace`, so a live decision and a postmortem read
    the same way."""
    if isinstance(rule, Mapping):
        return (str(rule.get("rule", "")), str(rule.get("tier", "")),
                bool(rule.get("unknown_escape")))
    return (rule.name, rule.tier, bool(rule.unknown_escape))


def unknown_escapes(gate_trace: Iterable, *, tier: str = TIER_PRIMARY
                    ) -> tuple[str, ...]:
    """The names of the rules that passed ONLY because their unknown-input
    escape fired, at the given tier. Pure; no logging."""
    return tuple(name for name, rule_tier, escaped in map(_rule_view, gate_trace)
                 if escaped and rule_tier == tier)


def warn_on_unknown_escapes(gate_trace: Sequence, *, tier: str | None,
                            event_id: str, company_id: int | None = None
                            ) -> tuple[str, ...]:
    """Emit ONE structured WARNING when a PRIMARY publication rested on a
    rule nobody could evaluate. Returns the rule names (empty tuple = nothing
    to say), so a caller can assert on it without reading the log.

    Returns early for any tier other than PRIMARY -- including REJECTED,
    where an escape changed no outcome.
    """
    if tier != TIER_PRIMARY:
        return ()
    escaped = unknown_escapes(gate_trace, tier=TIER_PRIMARY)
    if not escaped:
        return ()

    logger.warning(
        "PRIMARY published on an unevaluated input: rule(s) %s passed only "
        "because the gate's unknown_*_passes escape fired. This is expected "
        "until the sensitivity engine feeds every draft, and is a silent "
        "quality hole during a PARTIAL rollout -- see %s.",
        ", ".join(escaped), CUTOVER_REFERENCE,
        extra={
            "gate_unknown_escape_rules": ",".join(escaped),
            "gate_tier": TIER_PRIMARY,
            "event_id": event_id,
            "company_id": company_id,
            "cutover_reference": CUTOVER_REFERENCE,
        })
    return escaped
