"""TASK 0.1 -- V4 stages become signal EMITTERS, without being rewritten.

The phase file is explicit: "Do not delete V4 analysis modules. Wrap them as
signal emitters." This module is the wrapper. It converts the entry dicts
`app.pipeline._v3_entries` already produces -- the last point in the V4
pipeline where every stage's output coexists (impact-graph engine, evidence
classifier, materiality grader, publication gate, verifier) -- into frozen
`Signal` objects. Not one V4 module is modified.

PURE. Standard library + `app.core` only: no DB, no clock (the caller
supplies `created_at`), no market data.

WHAT IS DELIBERATELY NOT READ FROM THE ENTRY (master context invariant 3):
`price_at_analysis`, `return_1m`, `return_3m`, `excess_move_pct`,
`measurement_status`. Market movement never influences a fundamental
verdict, so the adapter cannot see it -- pinned by
`tests/phase0/test_market_isolation.py`.

MAPPING TABLES BELOW ARE THE WHOLE TRUTH OF THE V4 -> V5 TRANSLATION. Every
one of them maps an unrecognised value to None (or drops the signal), never
to a plausible default.
"""
from datetime import datetime
from typing import Any, Mapping

import json

from app.core.signals import Signal, make_signal

# V4 §22 discovery vocabulary -> V5's four-value vocabulary. EXPOSURE_RULE,
# RIPPLE_DISCOVERY, ESCALATION, COMPLETENESS and CURATED have no V5 twin
# that is not a guess: a curated exposure rule is not a MENTION, and it is
# not necessarily SUPPLY_CHAIN either. They map to None -> the row is
# written with a NULL discovery_source and needs_reanalysis = true.
DISCOVERY_SOURCE_MAP = {
    "ARTICLE_MENTION": "MENTION",
    "MECHANISM_MAPPING": "MECHANISM",
}

DIRECTNESS_VALUES = ("DIRECT", "INDIRECT", "REMOTE")

# V4 evidence tier -> V5 evidence grade. SUBJECT (the article names the
# company as its subject) is a real artifact of middling strength, so C;
# MARKET_OBS (the argument is the stock's own move) is the weakest thing
# there is, so E -- it must never authorize anything.
EVIDENCE_TIER_TO_GRADE = {
    "A": "A", "B": "B", "C": "C", "D": "D", "E": "E",
    "SUBJECT": "C", "MARKET_OBS": "E",
}

# V4 evidence tier -> claim binding. A/B are structured, company-specific
# artifacts; C/D/SUBJECT are real but not company-binding; E and
# MARKET_OBS bind nothing at all.
EVIDENCE_TIER_TO_BINDING = {
    "A": "BOUND", "B": "BOUND",
    "C": "SECTOR_PROXY", "D": "SECTOR_PROXY", "SUBJECT": "SECTOR_PROXY",
    "E": "UNBOUND", "MARKET_OBS": "UNBOUND",
}

# V4 composite materiality grade -> V5 channel materiality. UNKNOWN maps to
# NONE, not to a middle value: "the grader could not grade it" is not
# "medium".
MATERIALITY_GRADE_MAP = {
    "HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW", "UNKNOWN": "NONE",
}

_EFFECT_DIRECTIONS = {
    "positive": ("POSITIVE",),
    "negative": ("NEGATIVE",),
    "mixed": ("POSITIVE", "NEGATIVE"),
}


def _slug(text: str) -> str:
    keep = [ch.lower() if ch.isalnum() else "_" for ch in str(text)[:48]]
    return "".join(keep).strip("_") or "unnamed"


def _channels_from_entry(entry: Mapping[str, Any]) -> list[tuple[str, str]]:
    """[(channel_id, direction)] for one entry.

    Prefers the model's own signed channel lists (`channels_json`, written
    by the V4 token-optimisation stage). Falls back to the single canonical
    `economic_effect`, which for `mixed` yields the TWO channels that word
    actually means -- collapsing it to one direction is the exact defect
    invariant 9 forbids.
    """
    raw = entry.get("channels_json")
    if raw:
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            parsed = {}
        channels = []
        for description in parsed.get("positive_channels") or []:
            channels.append((f"pos_{_slug(description)}", "POSITIVE"))
        for description in parsed.get("negative_channels") or []:
            channels.append((f"neg_{_slug(description)}", "NEGATIVE"))
        if channels:
            return channels

    effect = str(entry.get("economic_effect") or "")
    return [(f"effect_{direction.lower()}", direction)
            for direction in _EFFECT_DIRECTIONS.get(effect, ())]


def signals_from_entry(entry: Mapping[str, Any], *, event_id: str,
                       analysis_version: str, created_at: datetime,
                       entity_status: str = "UNKNOWN",
                       isin: str | None = None) -> list[Signal]:
    """One V4 entry dict -> the signals the reducer needs.

    `entity_status` and `isin` come from the resolved `Company` row, which
    the entry does not carry; the caller supplies them. Unsupplied means
    UNKNOWN, and the gate's hard block decides what that means.
    """
    company_id = entry.get("company_id")
    ticker = str(entry.get("ticker") or "")

    def emit(stage: str, kind: str, payload: dict, created_by: str) -> Signal:
        return make_signal(
            event_id=event_id, company_id=company_id, stage=stage, kind=kind,
            payload=payload, created_by=created_by,
            analysis_version=analysis_version, created_at=created_at)

    signals: list[Signal] = [emit(
        "ENTITY", "ENTITY_RESOLUTION", {
            "ticker": ticker, "isin": isin,
            "resolution": "RESOLVED" if company_id is not None else "UNRESOLVED",
            "entity_status": entity_status,
        }, "v4:entity_resolution")]

    directness = entry.get("causal_directness")
    signals.append(emit("DISCOVERY", "DISCOVERY", {
        "discovery_source": DISCOVERY_SOURCE_MAP.get(
            str(entry.get("discovery_source_vocab") or "")),
        "directness": directness if directness in DIRECTNESS_VALUES else None,
        "graph_distance": (entry.get("causal_distance")
                           if isinstance(entry.get("causal_distance"), int) else None),
    }, "v4:impact_graph_engine"))

    materiality = MATERIALITY_GRADE_MAP.get(
        str(entry.get("materiality_grade") or "").upper(), "NONE")
    mechanism_id = entry.get("causal_parent_id") or None
    for channel_id, direction in _channels_from_entry(entry):
        signals.append(emit("SENSITIVITY", "CHANNEL", {
            "channel_id": channel_id,
            "mechanism_id": str(mechanism_id) if mechanism_id else None,
            "horizon": "NEAR_TERM", "direction": direction,
            "materiality": materiality,
            "evidence_ids": [str(i) for i in (entry.get("evidence_ids") or [])],
        }, "v4:impact_graph_engine"))

    tier = str(entry.get("evidence_tier") or "").upper()
    if tier in EVIDENCE_TIER_TO_BINDING:
        signals.append(emit("EVIDENCE", "EVIDENCE_BINDING", {
            # V4 has no claim records; what its evidence classifier actually
            # backs is the MATERIALITY claim ("this company is materially
            # exposed"), never a pass-through or hedge claim -- those are
            # precisely the four types V5 refuses to assert without a
            # company-named filing, and V4 has no such binding to offer.
            "claim_id": f"v4:{ticker}:materiality",
            "claim_type": "MATERIALITY",
            "binding_status": EVIDENCE_TIER_TO_BINDING[tier],
            "evidence_grade": EVIDENCE_TIER_TO_GRADE.get(tier),
            "evidence_ids": [str(i) for i in (entry.get("evidence_ids") or [])],
        }, "v4:evidence_classifier"))

    gate_inputs = entry.get("gate_inputs") or {}
    if gate_inputs.get("verification_available"):
        verified = bool(gate_inputs.get("independently_verified"))
        signals.append(emit("VERIFIER", "OBJECTION", {
            "objection_id": f"v4:{ticker}:verification",
            "type": "NOT_INDEPENDENTLY_VERIFIED",
            "severity": "MAJOR", "sustained": not verified,
        }, "v4:verifier"))

    # There is no empirical calibration table in this repo (Phase 5 builds
    # it). NO_DATA is the literal truth, and §7.4 admits it explicitly --
    # this is a statement of absence, not a fabricated agreement.
    signals.append(emit("EMPIRICAL", "EMPIRICAL_CHECK",
                        {"status": "NO_DATA", "n_events": None},
                        "empirical:not_available"))
    return signals
