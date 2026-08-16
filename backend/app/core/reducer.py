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
  * DAMPEN / AMPLIFY modifiers are RECORDED as applied but change no
    number. There is no coefficient in this repo to apply, and inventing a
    dampening factor is exactly the fabrication the master context forbids.
    Only BLOCK (channel stops being material) and REVERSE (direction flips)
    are structural enough to act on without data.
  * Anything the signals do not say stays None and sets `needs_reanalysis`.
    Nothing is guessed, ever.
"""
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import hashlib
import json

from app.core.claims import weakest_binding
from app.core.gates import (
    GateConfig, ImpactDraft, TIER_REJECTED, evaluate as evaluate_gate,
)
from app.core.signals import Signal, SignalKind

REDUCER_VERSION = "r5.0.0"

# Phase 0 uses a single horizon bucket. Phase 4 adds IMMEDIATE and
# STRUCTURAL; the record shape already carries a horizon MAP so that
# addition is not a schema change.
NEAR_TERM = "NEAR_TERM"

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
    """
    event_status: str | None = None            # CONFIRMED | OFFICIAL | RUMOUR
    shock_magnitude_confidence: float | None = None
    exposure_stale: bool = False


@dataclass(frozen=True)
class ReducerConfig:
    gate_config: GateConfig
    event_context: EventContext = EventContext()
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
        applied.append(modifier_id)

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
        direction_by_horizon={NEAR_TERM: {
            "direction": net_effect, "materiality": materiality_bucket}},
        headline_horizon=NEAR_TERM, net_effect=net_effect,
        sign_consistency=sign_consistency, channels=tuple(channels),
        policy_modifiers_applied=tuple(applied),
        materiality_bucket=materiality_bucket, mechanism_id=mechanism_id,
        evidence_grade=evidence_grade, weakest_link=weakest_link,
        claim_bindings=tuple(bindings), empirical_status=empirical_status,
        objections=tuple(objections), directness=directness,
        graph_distance=graph_distance, discovery_source=discovery_source,
        needs_reanalysis=needs_reanalysis,
    )

    if not entities or resolutions == {"UNRESOLVED"}:
        return _reject(base, "ENTITY_UNRESOLVED")
    if "AMBIGUOUS" in resolutions or len(tickers) > 1:
        return _reject(base, "ENTITY_AMBIGUOUS")

    # --- 7. publication gate ----------------------------------------------
    draft = ImpactDraft(
        entity_status=entity_status[0] if entity_status else "UNKNOWN",
        entity_ambiguous=False,
        exposure_stale=config.event_context.exposure_stale,
        materiality_bucket=materiality_bucket, graph_distance=graph_distance,
        directness=directness, evidence_grade=evidence_grade,
        weakest_link=weakest_link, sign_consistency=sign_consistency,
        empirical_status=empirical_status,
        objections=tuple(objections), unbound_claim_ids=unbound_claim_ids,
        verifier_status=verifier_status, adv_20d_inr=None,
        event_status=config.event_context.event_status,
        shock_magnitude_confidence=config.event_context.shock_magnitude_confidence,
        mechanism_id=mechanism_id, net_effect=net_effect)
    result = evaluate_gate(draft, config.gate_config)

    # --- 8. emit -----------------------------------------------------------
    return _stamped(CompanyImpact(
        publication_tier=result.tier or TIER_REJECTED,
        rejection_reason=result.rejection_reason,
        gate_trace=tuple({"rule": r.name, "passed": r.passed,
                          "detail": r.detail, "tier": r.tier}
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
            "direction_by_horizon": {
                horizon: dict(value)
                for horizon, value in impact.direction_by_horizon.items()},
            "headline_horizon": impact.headline_horizon,
            "net_effect": impact.net_effect,
            "sign_consistency": impact.sign_consistency,
            "materiality_bucket": impact.materiality_bucket,
            "mechanism_id": impact.mechanism_id,
            "channels": [dict(c) for c in impact.channels],
            "policy_modifiers_applied": list(impact.policy_modifiers_applied),
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
