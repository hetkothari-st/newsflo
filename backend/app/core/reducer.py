"""TASK 0.2 -- THE CANONICAL REDUCER (spec §7.2/§7.3).

The ONE code path permitted to produce a `CompanyImpact`. Pure: no I/O, no
network, no LLM, no clock, no randomness. The same signal set in ANY order
produces a byte-identical record -- pinned at 10_000 permutations by
`tests/phase0/test_reducer_purity.py`.

IMPLEMENTATION ORDER (phase file Task 0.2, followed literally):
  1. resolve entity            (ambiguity => REJECTED / ENTITY_AMBIGUOUS)
  2. collect channels          (single NEAR_TERM bucket in Phase 0)
  3. apply modifiers           (deterministic, sorted by modifier_id)
  4. resolve net effect
  5. grade evidence, compute weakest_link
  6. fold objections
  7. evaluate the publication gate
  8. emit CompanyImpact with decision_trace_id

PHASE 0 SCOPE, and what is deliberately NOT done here:

  * Materiality arrives from the existing V4 logic as a channel payload.
    Phase 2 replaces the source; the reducer's contract does not change.
    (PHASE 2, additive: when the CHANNEL signals carry a `sensitivity`
    block -- a computed band from `app.analysis.sensitivity` -- the computed
    bucket, sign consistency and net effect supersede the ordinal
    aggregation below. A signal set without that block is reduced exactly as
    it was before Phase 2 existed, which is every V4 signal set in
    production today. See `_apply_sensitivity`.)
  * DAMPEN / AMPLIFY modifiers are RECORDED as applied but change no
    number. There is no coefficient in this repo to apply, and inventing a
    dampening factor is exactly the fabrication the master context forbids.
    Only BLOCK (channel stops being material) and REVERSE (direction flips)
    are structural enough to act on without data.
  * Anything the signals do not say stays None and sets `needs_reanalysis`.
    Nothing is guessed, ever.
"""
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Sequence

import hashlib
import json

from app.core.claims import weakest_binding
from app.core.gates import (
    GateConfig, ImpactDraft, TIER_REJECTED, evaluate as evaluate_gate,
)
from app.core.signals import Signal, SignalKind

REDUCER_VERSION = "r5.0.0"

# V5 PHASE 4 (spec §8). THREE horizons, computed independently, all three
# persisted. The order is TIME order, not a ranking, and every canonical
# record carries all three keys whether or not a horizon was evaluated -- an
# absent key is exactly what a reader mistakes for agreement.
IMMEDIATE = "IMMEDIATE"
NEAR_TERM = "NEAR_TERM"
STRUCTURAL = "STRUCTURAL"
HORIZONS = (IMMEDIATE, NEAR_TERM, STRUCTURAL)

# A horizon nobody evaluated. Stated once so the shape cannot drift between
# the reducer, the writer and the renderer.
UNEVALUATED_HORIZON: Mapping[str, Any] = MappingProxyType({
    "direction": None, "materiality": None, "sign_consistency": None,
    "delta_ebitda_pct_p50": None, "evaluated": False,
})

NET_POSITIVE = "POSITIVE"
NET_NEGATIVE = "NEGATIVE"
NET_MIXED = "MIXED"
NET_UNCERTAIN = "UNCERTAIN"
NET_NO_MATERIAL_IMPACT = "NO_MATERIAL_IMPACT"

# Relative weight of a materiality bucket when measuring how consistently
# the channels point the same way. Ordinal only -- these are NOT magnitudes
# and never become one.
_MATERIALITY_WEIGHT = {"HIGH": 3.0, "MEDIUM": 2.0, "LOW": 1.0, "NONE": 0.0}
_MATERIALITY_RANK = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}
_GRADE_RANK = {"A": 5, "B": 4, "C": 3, "D": 2, "E": 1}


class ReducerInputError(ValueError):
    """A signal set that is not one company's view of one event."""


@dataclass(frozen=True)
class EventContext:
    """Event-level facts the reducer cannot read off a per-company signal.

    Supplied by the caller (`app.core.signal_adapters`, which reads them off
    the Alert). `None` means NOT KNOWN and the gate's `unknown_*` policies
    decide what that means -- it is never silently treated as favourable.
    `exposure_stale` is False because Phase 0 has no exposure ledger at all;
    nothing exists that could be stale (Phase 1 supplies the real answer).

    `policy_state_stale` (V5 Phase 4, spec §9.3) is False for the same
    reason: a company whose modifiers depend on no tracked regime cannot have
    a stale one. The sensitivity engine supplies the real answer and also puts
    it on every CHANNEL payload, so a caller that forgets to thread it here
    cannot un-block the company.
    """
    event_status: str | None = None            # CONFIRMED | OFFICIAL | RUMOUR
    shock_magnitude_confidence: float | None = None
    exposure_stale: bool = False
    policy_state_stale: bool = False


@dataclass(frozen=True)
class SensitivityPolicy:
    """PHASE 2. The sign-consistency rule's thresholds, loaded from
    `config/materiality.yaml` by `app.core.config_loader` -- the single
    source of truth the sensitivity engine reads too.

    Every field is REQUIRED. There is deliberately no default: a threshold
    defaulted here would be a policy nobody chose, and it would silently
    disagree with the engine that produced the number.
    """
    directional_claim_min: float      # >= this -> a direction may be claimed
    secondary_min: float              # below this -> MIXED or UNCERTAIN
    mixed_requires_material_tail_pct: float


@dataclass(frozen=True)
class HorizonPolicy:
    """V5 PHASE 4. How a headline is chosen among the three horizons, loaded
    from `config/horizons.yaml` by `app.core.config_loader`.

    Every field is REQUIRED and there is deliberately no default: a weight
    defaulted here would be a ranking nobody chose, and it would silently
    disagree with the engine that produced the numbers being ranked.
    """
    materiality_weight: Mapping[str, float]
    tie_break: str

    def weight_for(self, bucket: str) -> float:
        try:
            return float(self.materiality_weight[str(bucket)])
        except KeyError as exc:
            raise ReducerInputError(
                f"no headline weight is configured for materiality bucket "
                f"{bucket!r}") from exc


@dataclass(frozen=True)
class ReducerConfig:
    gate_config: GateConfig
    event_context: EventContext = EventContext()
    # None means "no sensitivity policy configured". A signal set carrying a
    # computed band is then REFUSED rather than judged against thresholds
    # invented here (see `_apply_sensitivity`).
    sensitivity_policy: "SensitivityPolicy | None" = None
    # None means "no horizon policy configured". A signal set spanning more
    # than one horizon is then REFUSED rather than ranked by weights invented
    # here. A single-horizon set needs no ranking and does not require it.
    horizon_policy: "HorizonPolicy | None" = None
    # Seeded RNG, per the phase file's "no randomness except seeded RNG
    # passed in via config". Nothing in Phase 0 draws from it; it exists so
    # a later phase cannot smuggle in an unseeded source.
    rng_seed: int = 0


@dataclass(frozen=True)
class CompanyImpact:
    """The canonical record (spec §7.3). Four SEPARATE causal/publication
    fields -- `directness`, `graph_distance`, `discovery_source`,
    `publication_tier` -- never merged, never inferred from one another."""
    event_id: str
    company_id: int | None
    ticker: str | None
    isin: str | None
    analysis_version: str
    reducer_version: str
    gate_config_version: str

    # fundamental
    direction_by_horizon: Mapping[str, Mapping[str, Any]]
    headline_horizon: str
    net_effect: str
    sign_consistency: float
    channels: tuple[Mapping[str, Any], ...]
    policy_modifiers_applied: tuple[str, ...]
    # Modifiers whose target channel does not exist in this signal set. They
    # changed nothing, and saying otherwise would misdescribe the record.
    policy_modifiers_unmatched: tuple[str, ...]
    # V5 PHASE 4 (Task 4.4). Every policy modifier CONSIDERED, with its type,
    # its status, the notification it comes from and the horizons at which it
    # held that status -- the chips the UI renders. "We modelled the levy and
    # could not size it" and "there is no levy" are different sentences and
    # this is where they stop being the same silence.
    policy_modifiers_detail: tuple[Mapping[str, Any], ...]
    materiality_bucket: str
    mechanism_id: str | None

    # evidence
    evidence_grade: str | None
    weakest_link: str | None
    claim_bindings: tuple[Mapping[str, Any], ...]

    # empirical + adversary
    empirical_status: str | None
    objections: tuple[Mapping[str, Any], ...]

    # the four separation fields (Task 0.7)
    directness: str | None
    graph_distance: int | None
    discovery_source: str | None
    publication_tier: str

    needs_reanalysis: bool
    rejection_reason: str | None
    gate_trace: tuple[Mapping[str, Any], ...]
    decision_trace_id: str = ""
    # PHASE 2: the computed materiality band, its drivers and the estimator
    # that produced them, exactly as the sensitivity engine emitted it. None
    # for every signal set that carries no computed band.
    sensitivity: Mapping[str, Any] | None = None


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _one_of(signals: Sequence[Signal], attribute: str, label: str):
    values = {getattr(s, attribute) for s in signals}
    if len(values) != 1:
        raise ReducerInputError(
            f"a signal set must describe ONE {label}; got {sorted(map(str, values))}")
    return values.pop()


def _payloads(signals: Sequence[Signal], kind: SignalKind) -> list[Mapping]:
    return [s.payload for s in signals if s.kind == kind]


def _sensitivity_blocks(signals: Sequence[Signal]) -> dict[str, Mapping[str, Any]]:
    """`{horizon: computed materiality block}`.

    Every CHANNEL signal the sensitivity engine emits for a company AT ONE
    HORIZON carries the SAME block (it is a company-level result for that
    horizon), so seeing two different ones for the same horizon means two
    engines disagreed about the same company in the same event at the same
    horizon. That is refused rather than averaged: an average of two
    disagreeing bands is a number neither engine computed.

    Two different blocks at DIFFERENT horizons is not a disagreement -- it is
    the entire point of §8, and collapsing them is the V4 defect.
    """
    seen: dict[str, dict[str, Mapping[str, Any]]] = {}
    for payload in _payloads(signals, SignalKind.CHANNEL):
        block = payload.get("sensitivity")
        if not block:
            continue
        horizon = str(payload.get("horizon", NEAR_TERM))
        seen.setdefault(horizon, {})[_canonical(block)] = block
    out: dict[str, Mapping[str, Any]] = {}
    for horizon, blocks in seen.items():
        if len(blocks) > 1:
            raise ReducerInputError(
                f"two different sensitivity blocks for one company in one "
                f"event at horizon {horizon}; the reducer will not average "
                f"disagreeing bands")
        out[horizon] = next(iter(blocks.values()))
    return out


def _fold_net_effect(evaluated: Mapping[str, Mapping[str, Any]]) -> str:
    """Task 4.4: "conflicting material directions => MIXED".

    A horizon with no material impact contributes no direction. A horizon
    that is itself MIXED makes the whole record MIXED. Two horizons pointing
    opposite ways make the whole record MIXED. Nothing is ever averaged into
    a single direction, and MIXED is never collapsed back out of one
    (invariants 8 and 9).

    ONE evaluated horizon is not a fold. Its direction IS the record's net
    effect, verbatim -- including UNCERTAIN on an immaterial band, which is a
    statement about our knowledge and must not be rewritten into
    NO_MATERIAL_IMPACT, a statement about the world. (Pinned by Phase 2's
    `test_below_the_floor_without_material_magnitude_both_sides_is_uncertain_not_mixed`.)
    """
    if len(evaluated) == 1:
        return str(next(iter(evaluated.values()))["direction"])
    material = [entry for entry in evaluated.values()
                if str(entry["materiality"]) not in (NET_NO_MATERIAL_IMPACT, "NONE")]
    if not material:
        return (NET_NO_MATERIAL_IMPACT if evaluated else NET_UNCERTAIN)
    if any(str(entry["direction"]) == NET_MIXED for entry in material):
        return NET_MIXED
    signs = {str(entry["direction"]) for entry in material
             if str(entry["direction"]) in (NET_POSITIVE, NET_NEGATIVE)}
    if len(signs) > 1:
        return NET_MIXED
    if len(signs) == 1:
        return signs.pop()
    return NET_UNCERTAIN


def _select_headline(evaluated: Mapping[str, Mapping[str, Any]],
                     policy: "HorizonPolicy | None") -> str:
    """§8: the horizon with the largest `|delta_ebitda_pct_p50| x
    materiality_weight`, tie-broken toward NEAR_TERM."""
    if not evaluated:
        return NEAR_TERM
    if len(evaluated) == 1:
        return next(iter(evaluated))
    if policy is None:
        raise ReducerInputError(
            "this signal set spans more than one horizon and no horizon "
            "policy is configured; the reducer will not invent the weights "
            "it needs to choose a headline")
    scored = {}
    for horizon, entry in evaluated.items():
        magnitude = entry.get("delta_ebitda_pct_p50")
        scored[horizon] = (abs(float(magnitude)) if magnitude is not None else 0.0) \
            * policy.weight_for(str(entry["materiality"]))
    best = max(scored.values())
    tied = [h for h, value in scored.items() if value == best]
    if len(tied) == 1:
        return tied[0]
    if policy.tie_break in tied:
        return policy.tie_break
    return next(h for h in HORIZONS if h in tied)


def _apply_sensitivity(block: Mapping[str, Any],
                       policy: SensitivityPolicy) -> tuple[str, float, str]:
    """The sign-consistency rule (spec §5.2, phase file Task 2.4).

        sc >= directional_claim_min   -> the sign of p50 is the direction
        secondary_min <= sc < that    -> UNCERTAIN (and, by the gate's own
                                         floor, never PRIMARY)
        sc <  secondary_min           -> MIXED when both tails are material,
                                         UNCERTAIN otherwise

    MIXED is a claim that BOTH sides are material. When they are not, the
    honest answer is that we do not know -- and neither is ever collapsed
    into a direction (invariants 8 and 9).
    """
    band = block.get("delta_ebitda_pct") or {}
    try:
        p10, p50, p90 = (float(band["p10"]), float(band["p50"]),
                         float(band["p90"]))
        consistency = float(block["sign_consistency"])
        bucket = str(block["bucket"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ReducerInputError(
            f"a sensitivity block must carry p10/p50/p90, sign_consistency "
            f"and bucket; missing {exc}") from exc

    if bucket not in (*_MATERIALITY_RANK, NET_NO_MATERIAL_IMPACT):
        raise ReducerInputError(f"unknown materiality bucket {bucket!r}")

    if consistency >= policy.directional_claim_min:
        net_effect = (NET_POSITIVE if p50 > 0 else
                      NET_NEGATIVE if p50 < 0 else NET_UNCERTAIN)
    elif consistency >= policy.secondary_min:
        net_effect = NET_UNCERTAIN
    else:
        tail = policy.mixed_requires_material_tail_pct
        both_sides_material = (p10 < 0 < p90 and abs(p10) >= tail
                               and abs(p90) >= tail)
        net_effect = NET_MIXED if both_sides_material else NET_UNCERTAIN

    return net_effect, round(consistency, 6), bucket


def cap_evidence_grade(grade: str | None, cap: str | None) -> str | None:
    """FIX ROUND 1 (C1). The WORST of a claim's evidence grade and the cap its
    parameters allow.

    "At most the cap" means at most in BADNESS: a cap of C turns an A into a
    C and leaves a D alone. A company with no graded binding at all whose
    parameters are sector medians is not ungraded -- it is at best the cap.
    """
    if cap is None:
        return grade
    if grade is None:
        return cap
    # _GRADE_RANK is higher-is-better, so the worst of the two is the min.
    # An unrecognised grade ranks 0 and therefore wins, which is fail-closed.
    return min((grade, cap), key=lambda g: _GRADE_RANK.get(g, 0))


def _band_magnitude(block: Mapping[str, Any] | None) -> float | None:
    """|p50| of the computed band, or None when there is no computed band.
    None means NOT KNOWN and the gate's own policy decides what that means --
    it is never rendered as 0.0, which would read as "no impact"."""
    if not block:
        return None
    try:
        return abs(float((block.get("delta_ebitda_pct") or {})["p50"]))
    except (KeyError, TypeError, ValueError):          # pragma: no cover
        return None


def _uses_sector_proxy(signals: Sequence[Signal]) -> bool | None:
    """True when ANY parameter behind ANY channel came from a sector median,
    False when the channels are computed and none did, None when no channel
    reports its parameter sources at all (every V4-forwarded channel)."""
    reported = False
    for payload in _payloads(signals, SignalKind.CHANNEL):
        sources = payload.get("param_sources")
        if not isinstance(sources, Mapping):
            continue
        reported = True
        if any(str(source) == "SECTOR_PROXY" for source in sources.values()):
            return True
    return False if reported else None


def _dominant_proxy_param(block: Mapping[str, Any]) -> str | None:
    """The parameter driving more than half of the attributed variance, when
    that parameter is a SECTOR_PROXY. None otherwise."""
    for driver in block.get("driver_ranking") or []:
        try:
            contribution = float(driver.get("contribution", 0.0))
        except (TypeError, ValueError):             # pragma: no cover
            continue
        if contribution > 0.5 and str(driver.get("source")) == "SECTOR_PROXY":
            return str(driver.get("param") or "parameter").split("(")[0]
    return None


def _reject(base: dict, reason: str, trace=()) -> CompanyImpact:
    impact = CompanyImpact(publication_tier=TIER_REJECTED, rejection_reason=reason,
                           gate_trace=trace, **base)
    return _stamped(impact)


def _stamped(impact: CompanyImpact) -> CompanyImpact:
    """decision_trace_id is a CONTENT HASH of the record, not a drawn id --
    the same decision always has the same trace id, and any change to the
    decision changes it."""
    payload = serialize_company_impact(impact)
    payload.pop("decision_trace_id", None)
    digest = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    return CompanyImpact(**{**impact.__dict__, "decision_trace_id": digest[:32]})


def reduce_company_impact(signals: Sequence[Signal],
                          config: ReducerConfig) -> CompanyImpact:
    """PURE. No I/O. No network. No LLM. No clock reads. No randomness
    except a seeded RNG passed in via config.
    Same input set (in any order) => byte-identical output."""
    if not signals:
        raise ReducerInputError("no signals")

    # Total order first: everything below reads this list, never the caller's.
    ordered = sorted(signals, key=lambda s: s.sort_key())
    event_id = _one_of(ordered, "event_id", "event")
    company_id = _one_of(ordered, "company_id", "company")
    analysis_version = _one_of(ordered, "analysis_version", "analysis_version")

    # --- 1. entity ---------------------------------------------------------
    entities = _payloads(ordered, SignalKind.ENTITY_RESOLUTION)
    tickers = sorted({str(e.get("ticker") or "") for e in entities})
    isins = sorted({str(e["isin"]) for e in entities if e.get("isin")})
    resolutions = {str(e.get("resolution")) for e in entities}
    entity_status = sorted({str(e.get("entity_status", "UNKNOWN")) for e in entities})

    # --- 2. channels -------------------------------------------------------
    channels = []
    for payload in _payloads(ordered, SignalKind.CHANNEL):
        channels.append({
            "channel_id": str(payload["channel_id"]),
            "mechanism_id": payload.get("mechanism_id"),
            "horizon": str(payload.get("horizon", NEAR_TERM)),
            "direction": str(payload["direction"]),
            "materiality": str(payload["materiality"]),
            "material": str(payload["materiality"]) != "NONE",
            "evidence_ids": sorted(payload.get("evidence_ids") or []),
            "modifiers_applied": [],
        })
    channels.sort(key=lambda c: c["channel_id"])

    # --- 3. modifiers, in deterministic order ------------------------------
    modifiers = sorted(_payloads(ordered, SignalKind.MODIFIER),
                       key=lambda m: str(m["modifier_id"]))
    applied: list[str] = []
    unmatched: list[str] = []
    for modifier in modifiers:
        modifier_id = str(modifier["modifier_id"])
        effect = str(modifier["effect"])
        target = modifier.get("applies_to_channel_id")
        touched = [c for c in channels
                   if target is None or c["channel_id"] == target]
        for channel in touched:
            channel["modifiers_applied"].append(modifier_id)
            if effect == "BLOCK":
                channel["material"] = False
            elif effect == "REVERSE":
                channel["direction"] = (
                    "NEGATIVE" if channel["direction"] == "POSITIVE" else "POSITIVE")
            # DAMPEN / AMPLIFY: recorded, not applied -- see the module
            # docstring. There is no coefficient to apply and one must not
            # be invented.
        # A modifier whose target channel does not exist touched NOTHING.
        # Listing it as applied is a small lie in exactly the field a
        # postmortem reads to explain a number, so it is recorded honestly
        # in its own list instead (fix round 1).
        (applied if touched else unmatched).append(modifier_id)

    # --- 3b. POLICY modifiers (V5 Phase 4) ---------------------------------
    #
    # These are a DIFFERENT thing from the MODIFIER signals above. A MODIFIER
    # signal is an ordinal instruction (BLOCK / REVERSE) that acts on the
    # reducer's own channel records; a POLICY modifier is a transfer function
    # that already acted on the NUMBER, upstream in the sensitivity engine.
    # The reducer's job here is only to carry the account of it into the
    # record, which is why nothing below changes a direction or a bucket.
    policy_detail: dict[tuple[str, str], dict] = {}
    for payload in _payloads(ordered, SignalKind.CHANNEL):
        horizon = str(payload.get("horizon", NEAR_TERM))
        for entry in payload.get("policy_modifiers") or []:
            key = (str(entry["modifier_id"]), str(entry.get("status", "APPLIED")))
            record = policy_detail.setdefault(key, {
                **{k: v for k, v in entry.items() if k != "horizons"},
                "horizons": []})
            if horizon not in record["horizons"]:
                record["horizons"].append(horizon)
    for record in policy_detail.values():
        record["horizons"].sort(key=lambda h: HORIZONS.index(h)
                                if h in HORIZONS else len(HORIZONS))
    policy_modifiers_detail = tuple(
        policy_detail[key] for key in sorted(policy_detail))
    applied.extend(modifier_id for modifier_id, status in sorted(policy_detail)
                   if status == "APPLIED")

    # --- 4. net effect -----------------------------------------------------
    material = [c for c in channels if c["material"]]
    positive_weight = sum(_MATERIALITY_WEIGHT[c["materiality"]]
                          for c in material if c["direction"] == "POSITIVE")
    negative_weight = sum(_MATERIALITY_WEIGHT[c["materiality"]]
                          for c in material if c["direction"] == "NEGATIVE")
    total_weight = positive_weight + negative_weight

    if not channels:
        net_effect = NET_UNCERTAIN
    elif not material:
        net_effect = NET_NO_MATERIAL_IMPACT
    elif positive_weight and negative_weight:
        net_effect = NET_MIXED
    elif positive_weight:
        net_effect = NET_POSITIVE
    else:
        net_effect = NET_NEGATIVE

    sign_consistency = (
        round(max(positive_weight, negative_weight) / total_weight, 6)
        if total_weight else 0.0)

    materiality_bucket = "NONE"
    for channel in material:
        if _MATERIALITY_RANK[channel["materiality"]] > _MATERIALITY_RANK[materiality_bucket]:
            materiality_bucket = channel["materiality"]
    if materiality_bucket == "NONE":
        materiality_bucket = "NO_MATERIAL_IMPACT"

    # --- 4b. a COMPUTED band supersedes the ordinal aggregation (Phase 2) --
    #         ...ONCE PER HORIZON (V5 Phase 4).
    #
    # Each horizon is judged by the same sign-consistency rule against its own
    # band, and the three answers are kept. The record's `net_effect` folds
    # them (conflicting material directions => MIXED) while the horizons
    # themselves stay exactly as computed -- which is the difference between
    # this and the V4 behaviour that produced three contradictory Oil India
    # records from one event.
    blocks = _sensitivity_blocks(ordered)
    evaluated: dict[str, dict[str, Any]] = {}
    if blocks:
        if config.sensitivity_policy is None:
            raise ReducerInputError(
                "a computed sensitivity band arrived but no sensitivity "
                "policy is configured; the reducer will not invent the "
                "sign-consistency thresholds it needs to judge it")
        for horizon in sorted(blocks, key=lambda h: HORIZONS.index(h)
                              if h in HORIZONS else len(HORIZONS)):
            block = blocks[horizon]
            direction, consistency, bucket = _apply_sensitivity(
                block, config.sensitivity_policy)
            evaluated[horizon] = {
                "direction": direction, "materiality": bucket,
                "sign_consistency": consistency,
                "delta_ebitda_pct_p50": (block.get("delta_ebitda_pct") or {}).get("p50"),
                "evaluated": True}
    else:
        # The V4-forwarded path: no computed band anywhere. The ordinal
        # aggregation above is the only answer there is, and it is recorded
        # against the horizon(s) the channels actually claim -- not against
        # all three, which would assert two evaluations nobody performed.
        for horizon in sorted({c["horizon"] for c in channels} or {NEAR_TERM},
                              key=lambda h: HORIZONS.index(h)
                              if h in HORIZONS else len(HORIZONS)):
            evaluated[horizon] = {
                "direction": net_effect, "materiality": materiality_bucket,
                "sign_consistency": sign_consistency,
                "delta_ebitda_pct_p50": None, "evaluated": True}

    headline_horizon = _select_headline(evaluated, config.horizon_policy)
    if blocks:
        net_effect = _fold_net_effect(evaluated)
        sign_consistency = float(evaluated[headline_horizon]["sign_consistency"])
        materiality_bucket = str(evaluated[headline_horizon]["materiality"])
    # The headline horizon's block is the one the record leads with, and the
    # one the evidence cap and the gate's materiality floor read. The other
    # two are never discarded -- they are in `direction_by_horizon`.
    sensitivity = blocks.get(headline_horizon) if blocks else None

    direction_by_horizon = {
        horizon: evaluated.get(horizon, dict(UNEVALUATED_HORIZON))
        for horizon in HORIZONS}

    mechanism_ids = sorted({str(c["mechanism_id"]) for c in material
                            if c.get("mechanism_id")})
    mechanism_id = mechanism_ids[0] if mechanism_ids else None

    # --- 5. evidence -------------------------------------------------------
    bindings = [{
        "claim_id": str(p["claim_id"]),
        "claim_type": str(p["claim_type"]),
        "binding_status": str(p["binding_status"]),
        "evidence_grade": p.get("evidence_grade"),
        "evidence_ids": sorted(p.get("evidence_ids") or []),
    } for p in _payloads(ordered, SignalKind.EVIDENCE_BINDING)]
    bindings.sort(key=lambda b: b["claim_id"])

    graded = [b["evidence_grade"] for b in bindings if b["evidence_grade"]]
    evidence_grade = (max(graded, key=lambda g: _GRADE_RANK.get(g, 0))
                      if graded else None)
    weakest_link = weakest_binding(
        (b["claim_type"], b["binding_status"]) for b in bindings)
    unbound_claim_ids = tuple(b["claim_id"] for b in bindings
                              if b["binding_status"] == "UNBOUND")

    # --- 5b. the parameter grade cap, ENFORCED (fix round 1, C1) -----------
    #
    # The sensitivity engine caps the evidence grade a channel may claim when
    # a parameter came from a sector median (C) or a modelled judgement (D).
    # Phase 2 computed that cap and nothing consumed it: an all-sector-proxy
    # company with an A-graded claim binding published PRIMARY.
    #
    # Both halves of the fix live here, at draft construction, because
    # `config/gates.yaml` and `app/core/gates.py` are owned by another phase
    # and the gate's existing rules already do the right thing once their
    # INPUTS are honest:
    #
    #   1. the evidence grade is capped to the worst of (claim grade, param
    #      cap). PRIMARY admits {A,B,C} and MEDIUM materiality needs {A,B},
    #      so a capped grade demotes exactly where it should;
    #   2. THE VOCABULARY BRIDGE. `forbidden_weakest_link_statuses` is
    #      written in the CLAIM-BINDING vocabulary, where "SECTOR_PROXY"
    #      means "the evidence is about the sector, not this company". A
    #      parameter taken from a sector median is the same statement about a
    #      different part of the chain, and the two spellings are homonyms,
    #      not synonyms -- so nothing bridged them. When the DOMINANT driver
    #      (>50% of attributed variance) is a SECTOR_PROXY parameter, the
    #      weakest link of this company's chain IS that parameter, and it is
    #      named as such: "<param>:SECTOR_PROXY". The existing gate rule then
    #      refuses it for PRIMARY, legitimately and readably in the trace.
    #
    # An UNBOUND claim binding is worse than a sector proxy and is never
    # overwritten: the record must keep describing its true weakest point.
    if sensitivity is not None:
        evidence_grade = cap_evidence_grade(
            evidence_grade, sensitivity.get("evidence_grade_cap"))
        proxy_param = _dominant_proxy_param(sensitivity)
        current_status = (weakest_link or "").rsplit(":", 1)[-1]
        if proxy_param and current_status != "UNBOUND":
            weakest_link = f"{proxy_param}:SECTOR_PROXY"

    # --- 6. objections -----------------------------------------------------
    objections = sorted(
        ({"objection_id": str(p["objection_id"]), "type": str(p["type"]),
          "severity": str(p["severity"]), "sustained": bool(p["sustained"])}
         for p in _payloads(ordered, SignalKind.OBJECTION)),
        key=lambda o: o["objection_id"])

    empirical = _payloads(ordered, SignalKind.EMPIRICAL_CHECK)
    empirical_status = str(empirical[0]["status"]) if empirical else None

    # The verifier ran iff it emitted a signal; it PASSED iff it sustained
    # nothing. "Did not run" stays None -- the gate decides what that means.
    verifier_signals = [s for s in ordered if s.stage.upper() == "VERIFIER"]
    verifier_status = None
    if verifier_signals:
        verifier_status = "FAIL" if any(
            s.kind == SignalKind.OBJECTION and s.payload.get("sustained")
            for s in verifier_signals) else "PASS"

    # --- discovery: the four separation fields -----------------------------
    discovery = _payloads(ordered, SignalKind.DISCOVERY)
    directness = discovery[0].get("directness") if discovery else None
    graph_distance = discovery[0].get("graph_distance") if discovery else None
    discovery_source = discovery[0].get("discovery_source") if discovery else None
    # Task 0.7: unmappable stays NULL and marks the row. Never guessed.
    needs_reanalysis = any(v is None for v in
                           (directness, graph_distance, discovery_source))

    base = dict(
        event_id=event_id, company_id=company_id,
        ticker=tickers[0] if tickers else None,
        isin=isins[0] if isins else None,
        analysis_version=analysis_version, reducer_version=REDUCER_VERSION,
        gate_config_version=config.gate_config.version,
        direction_by_horizon=direction_by_horizon,
        headline_horizon=headline_horizon, net_effect=net_effect,
        sign_consistency=sign_consistency, channels=tuple(channels),
        policy_modifiers_applied=tuple(sorted(set(applied))),
        policy_modifiers_unmatched=tuple(unmatched),
        policy_modifiers_detail=policy_modifiers_detail,
        materiality_bucket=materiality_bucket, mechanism_id=mechanism_id,
        evidence_grade=evidence_grade, weakest_link=weakest_link,
        claim_bindings=tuple(bindings), empirical_status=empirical_status,
        objections=tuple(objections), directness=directness,
        graph_distance=graph_distance, discovery_source=discovery_source,
        needs_reanalysis=needs_reanalysis, sensitivity=sensitivity,
    )

    # Staleness reaches the gate from two places (Phase 2 controller
    # addendum): the caller's event context, and the channels themselves.
    # Either is enough to hard-block -- a stale exposure must not be able to
    # back a claim because a caller forgot to thread a flag.
    exposure_stale = bool(config.event_context.exposure_stale) or any(
        bool(p.get("exposure_stale"))
        for p in _payloads(ordered, SignalKind.CHANNEL))

    # V5 PHASE 4 / spec §9.3, by the same two routes and for the same reason:
    # a company whose regime reading has gone stale must not reach PRIMARY,
    # and a caller who forgets to thread the event context must not be able
    # to un-block it.
    policy_state_stale = bool(config.event_context.policy_state_stale) or any(
        bool(p.get("policy_state_stale"))
        for p in _payloads(ordered, SignalKind.CHANNEL))

    if not entities or resolutions == {"UNRESOLVED"}:
        return _reject(base, "ENTITY_UNRESOLVED")
    if "AMBIGUOUS" in resolutions or len(tickers) > 1:
        return _reject(base, "ENTITY_AMBIGUOUS")

    # --- 7. publication gate ----------------------------------------------
    draft_fields: dict[str, Any] = dict(
        entity_status=entity_status[0] if entity_status else "UNKNOWN",
        entity_ambiguous=False,
        exposure_stale=exposure_stale,
        materiality_bucket=materiality_bucket, graph_distance=graph_distance,
        directness=directness, evidence_grade=evidence_grade,
        weakest_link=weakest_link, sign_consistency=sign_consistency,
        empirical_status=empirical_status,
        objections=tuple(objections), unbound_claim_ids=unbound_claim_ids,
        verifier_status=verifier_status, adv_20d_inr=None,
        event_status=config.event_context.event_status,
        shock_magnitude_confidence=config.event_context.shock_magnitude_confidence,
        mechanism_id=mechanism_id, net_effect=net_effect)

    # Gate inputs a LATER phase's gate may ask for. They are supplied only
    # when that phase's `ImpactDraft` actually declares them, so this reducer
    # keeps working against either version of the gate while the two phases
    # land -- and the moment the field exists, it is filled with the computed
    # answer instead of defaulting to "unknown".
    #
    #   delta_ebitda_pct_abs -- the magnitude the gate's materiality floor
    #                           compares against, |p50| of the computed band;
    #   uses_sector_proxy    -- whether ANY parameter behind ANY channel came
    #                           from a sector median. This is the same fact
    #                           the weakest-link bridge above expresses in the
    #                           claim vocabulary; here it is stated in its
    #                           own terms, which is better.
    optional_draft_fields = {
        "delta_ebitda_pct_abs": _band_magnitude(sensitivity),
        "uses_sector_proxy": _uses_sector_proxy(ordered),
        # V5 PHASE 4: whether a tracked regime reading behind this company's
        # modifiers is past its freshness window (§9.3).
        "policy_state_stale": policy_state_stale,
    }
    for name, value in optional_draft_fields.items():
        if name in ImpactDraft.__dataclass_fields__:
            draft_fields[name] = value

    draft = ImpactDraft(**draft_fields)
    result = evaluate_gate(draft, config.gate_config)

    # --- 8. emit -----------------------------------------------------------
    return _stamped(CompanyImpact(
        publication_tier=result.tier or TIER_REJECTED,
        rejection_reason=result.rejection_reason,
        gate_trace=tuple({"rule": r.name, "passed": r.passed,
                          "detail": r.detail, "tier": r.tier,
                          # V5 Phase 3 (review round 1, I3): a rule that
                          # passed only because its unknown-input escape
                          # fired must be distinguishable IN THE PERSISTED
                          # RECORD, or a postmortem cannot tell which
                          # published rows leant on one. See
                          # app/core/gate_warnings.py.
                          "unknown_escape": r.unknown_escape}
                         for r in result.gate_trace),
        **base))


def serialize_company_impact(impact: CompanyImpact) -> dict:
    """JSON-safe, deterministic. The four separation fields are emitted as
    four DISTINCT top-level keys (`tests/phase0/test_field_separation.py`);
    nothing here ever joins two of them into one string."""
    return {
        "event_id": impact.event_id,
        "company_id": impact.company_id,
        "ticker": impact.ticker,
        "isin": impact.isin,
        "analysis_version": impact.analysis_version,
        "reducer_version": impact.reducer_version,
        "gate_config_version": impact.gate_config_version,
        "fundamental": {
            # V5 PHASE 4: ALL THREE HORIZONS, ALWAYS, in time order. A horizon
            # nobody evaluated is present and says so; it is never an absent
            # key, because an absent key is what a reader mistakes for
            # agreement with the headline. `headline_horizon` says which one
            # the UI leads with -- it does not say which one is true.
            "direction_by_horizon": {
                horizon: dict(impact.direction_by_horizon.get(
                    horizon, UNEVALUATED_HORIZON))
                for horizon in HORIZONS},
            "headline_horizon": impact.headline_horizon,
            "net_effect": impact.net_effect,
            "sign_consistency": impact.sign_consistency,
            "materiality_bucket": impact.materiality_bucket,
            "mechanism_id": impact.mechanism_id,
            "channels": [dict(c) for c in impact.channels],
            "policy_modifiers_applied": list(impact.policy_modifiers_applied),
            "policy_modifiers_unmatched": list(impact.policy_modifiers_unmatched),
            # Task 4.4: rendered as visible chips with links to the source
            # notification. Emitted whole -- an id with no type and no source
            # is a chip nobody can check.
            "policy_modifiers": [dict(entry)
                                 for entry in impact.policy_modifiers_detail],
            # PHASE 2 (Task 2.5): the computed band, its bucket, its sign
            # consistency and its top drivers -- emitted whole or not at all,
            # because a p50 without its band is exactly what this phase
            # exists to stop shipping.
            **({"materiality": dict(impact.sensitivity)}
               if impact.sensitivity else {}),
        },
        "evidence": {
            "grade": impact.evidence_grade,
            "weakest_link": impact.weakest_link,
            "claim_bindings": [dict(b) for b in impact.claim_bindings],
        },
        "empirical": {"status": impact.empirical_status},
        "objections": [dict(o) for o in impact.objections],
        # --- four separate fields, four separate keys ---------------------
        "directness": impact.directness,
        "graph_distance": impact.graph_distance,
        "discovery_source": impact.discovery_source,
        "publication_tier": impact.publication_tier,
        "needs_reanalysis": impact.needs_reanalysis,
        "rejection_reason": impact.rejection_reason,
        "gate_trace": [dict(r) for r in impact.gate_trace],
        "decision_trace_id": impact.decision_trace_id,
    }
