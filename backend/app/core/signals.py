"""TASK 0.1 -- the signal bus.

Every analysis stage stops being a verdict-writer and becomes a
signal-emitter. A `Signal` is an immutable, per-stage OBSERVATION about one
company in one event; nothing here decides anything. The Canonical Reducer
(`app.core.reducer`) is the only code that turns signals into a verdict.

PURE MODULE. Standard library only -- see `app/core/__init__.py`.

Payload discipline: every kind has a closed schema, validated at
construction. A stage that wants to say something the schema cannot express
must extend the schema in a review, not smuggle a free-text field through:
an unvalidated payload is how "the model said so" becomes "the system
believes".

The reserved key `_fixture` is allowed in ANY payload and carries through
verbatim. Test fixtures set it to `true` (master context's fabrication
guard), which makes fixture-derived rows identifiable in the database
itself rather than only by convention.
"""
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping

import hashlib
import json


class SignalKind(StrEnum):
    CHANNEL = "CHANNEL"                    # an economic transmission channel
    MODIFIER = "MODIFIER"                  # policy/contract/hedge adjustment
    EVIDENCE_BINDING = "EVIDENCE_BINDING"
    OBJECTION = "OBJECTION"
    EMPIRICAL_CHECK = "EMPIRICAL_CHECK"
    ENTITY_RESOLUTION = "ENTITY_RESOLUTION"
    DISCOVERY = "DISCOVERY"


class SignalPayloadError(ValueError):
    """A payload that does not satisfy its kind's schema."""


# Controlled vocabularies. These are the ONLY values a payload may carry;
# anything else is refused rather than normalised (a silent normalisation is
# a guess).
DIRECTIONS = ("POSITIVE", "NEGATIVE")
MATERIALITY_BUCKETS = ("HIGH", "MEDIUM", "LOW", "NONE")
# V5 PHASE 4 (spec §8). Three horizons, always, computed independently. The
# order here is TIME order, not a ranking.
HORIZONS = ("IMMEDIATE", "NEAR_TERM", "STRUCTURAL")
BINDING_STATUSES = ("BOUND", "SECTOR_PROXY", "UNBOUND")
EVIDENCE_GRADES = ("A", "B", "C", "D", "E")
OBJECTION_SEVERITIES = ("BLOCKING", "MAJOR", "WARN")
# V5 PHASE 5 (spec §10.2). WEAK joins the vocabulary: "history is not
# significant either way" is a different fact from "there is no history", and
# collapsing the two would let a noisy sample look like an absent one. A
# widening, so no payload that was valid before Phase 5 becomes invalid.
EMPIRICAL_STATUSES = ("AGREE", "CONFLICT", "WEAK", "NO_DATA")
RESOLUTIONS = ("RESOLVED", "AMBIGUOUS", "UNRESOLVED")
ENTITY_STATUSES = ("ACTIVE", "SUSPENDED", "DELISTED", "UNKNOWN")
DISCOVERY_SOURCES = ("MENTION", "MECHANISM", "SUPPLY_CHAIN", "PEER_CLOSURE")
DIRECTNESS_VALUES = ("DIRECT", "INDIRECT", "REMOTE")

RESERVED_KEYS = ("_fixture",)


class Vocab(tuple):
    """Marks a schema entry as a CLOSED VOCABULARY (membership test) rather
    than a python type check. Explicit because the two are easy to confuse
    and confusing them silently disables validation."""


# key -> (required, Vocab(...) | python type(s))
_SCHEMAS: dict[str, dict[str, tuple[bool, Any]]] = {
    SignalKind.CHANNEL: {
        "channel_id": (True, str),
        "mechanism_id": (False, (str, type(None))),
        "horizon": (True, Vocab(HORIZONS)),
        "direction": (True, Vocab(DIRECTIONS)),
        "materiality": (True, Vocab(MATERIALITY_BUCKETS)),
        "weight": (False, (int, float)),
        "evidence_ids": (False, list),
        # --- V5 PHASE 2 (sensitivity engine), all OPTIONAL ------------------
        # A V4-forwarded channel carries none of these and is validated
        # exactly as before. A channel COMPUTED by the sensitivity engine
        # carries the ledger row that authorises it, where each parameter
        # came from, its own contribution, and the company-level Monte Carlo
        # block the reducer's sign-consistency rule reads.
        "channel_type": (False, str),
        "exposure_id": (False, (str, type(None))),
        "param_sources": (False, dict),
        "delta_ebitda_pct_p50": (False, (int, float)),
        "exposure_stale": (False, bool),
        "sensitivity": (False, dict),
        # --- V5 PHASE 4 (policy modifiers), both OPTIONAL -------------------
        # Every policy modifier CONSIDERED for this company, with its status
        # (APPLIED / UNKNOWN_STATE / UNRESOLVED / NOT_TRIGGERED), its type and
        # the notification it comes from. Task 4.2 requires it to be surfaced,
        # so it travels with the number rather than being looked up later.
        "policy_modifiers": (False, list),
        # Whether a `policy_state` reading this company's modifiers depend on
        # is past its freshness window (§9.3 -- blocks PRIMARY).
        "policy_state_stale": (False, bool),
    },
    SignalKind.MODIFIER: {
        "modifier_id": (True, str),
        "effect": (True, Vocab(("DAMPEN", "AMPLIFY", "BLOCK", "REVERSE"))),
        "applies_to_channel_id": (False, (str, type(None))),
    },
    SignalKind.EVIDENCE_BINDING: {
        "claim_id": (True, str),
        "claim_type": (True, str),
        "binding_status": (True, Vocab(BINDING_STATUSES)),
        "evidence_grade": (False, Vocab(EVIDENCE_GRADES + (None,))),
        "evidence_ids": (False, list),
    },
    SignalKind.OBJECTION: {
        "objection_id": (True, str),
        "type": (True, str),
        "severity": (True, Vocab(OBJECTION_SEVERITIES)),
        "sustained": (True, bool),
    },
    SignalKind.EMPIRICAL_CHECK: {
        "status": (True, Vocab(EMPIRICAL_STATUSES)),
        "n_events": (False, (int, type(None))),
        # --- V5 PHASE 5 (spec §10), all OPTIONAL ---------------------------
        # The status travels WITH ITS SAMPLE. A payload carrying only
        # "CONFLICT" leaves the record unable to explain itself, and §10.3's
        # whole point is that the disagreement is a sentence you show the
        # user: "in 34 comparable historical shocks this name's 5-day
        # abnormal return was -1.4%".
        "shock_variable": (False, (str, type(None))),
        "shock_sign": (False, (str, type(None))),
        "horizon": (False, (str, type(None))),
        "median_car": (False, (int, float, type(None))),
        "p_value": (False, (int, float, type(None))),
        "sign_consistency": (False, (int, float, type(None))),
        "estimator_version": (False, (str, type(None))),
        # A human reviewer's REGIME_CHANGED annotation, still in force on the
        # analysis date. It does NOT change the status -- the record keeps
        # saying what history said -- it changes whether that conflict may
        # block a PRIMARY call (§10.3).
        "regime_changed": (False, bool),
        "regime_change_expires_on": (False, (str, type(None))),
    },
    SignalKind.ENTITY_RESOLUTION: {
        "ticker": (True, str),
        "isin": (False, (str, type(None))),
        "resolution": (True, Vocab(RESOLUTIONS)),
        "entity_status": (True, Vocab(ENTITY_STATUSES)),
    },
    SignalKind.DISCOVERY: {
        # Required to be PRESENT, allowed to be None: "the stage looked and
        # could not map it" is a fact worth recording, and Task 0.7 turns it
        # into NULL + needs_reanalysis rather than a guess.
        "discovery_source": (True, Vocab(DISCOVERY_SOURCES + (None,))),
        # Four SEPARATE fields (master context invariant 4): directness is
        # NOT derivable from graph_distance and vice versa. `None` means the
        # emitting stage did not classify it -- never a guessed default.
        "directness": (False, Vocab(DIRECTNESS_VALUES + (None,))),
        "graph_distance": (False, (int, type(None))),
    },
}


def validate_payload(kind: str, payload: Mapping) -> None:
    schema = _SCHEMAS.get(SignalKind(kind))
    if schema is None:                                  # pragma: no cover
        raise SignalPayloadError(f"no schema for signal kind {kind!r}")

    unknown = set(payload) - set(schema) - set(RESERVED_KEYS)
    if unknown:
        raise SignalPayloadError(
            f"{kind}: unknown payload key(s) {sorted(unknown)}; extend the "
            "schema in app/core/signals.py rather than passing free fields")

    for key, (required, allowed) in schema.items():
        if key not in payload:
            if required:
                raise SignalPayloadError(f"{kind}: missing required key {key!r}")
            continue
        value = payload[key]
        if isinstance(allowed, Vocab):
            if value not in allowed:
                raise SignalPayloadError(
                    f"{kind}.{key}: {value!r} is not in {tuple(allowed)}")
        elif not isinstance(value, allowed):
            raise SignalPayloadError(
                f"{kind}.{key}: expected {allowed}, got {type(value).__name__}")


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def signal_id_for(event_id: str, company_id: int | None, stage: str, kind: str,
                  payload: Mapping, created_by: str, analysis_version: str,
                  created_at: datetime) -> str:
    """CONTENT-ADDRESSED id. Two runs of the same analysis over the same
    article emit the same signals with the same ids, so re-appending them to
    the append-only table is a no-op instead of a duplicate. A random uuid4
    here would make every replay look like new evidence."""
    digest = hashlib.sha256(_canonical([
        event_id, company_id, stage, str(kind), payload, created_by,
        analysis_version, created_at.isoformat(),
    ]).encode("utf-8")).hexdigest()
    return f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


@dataclass(frozen=True)
class Signal:
    signal_id: str
    event_id: str
    company_id: int | None
    stage: str
    kind: SignalKind
    payload: Mapping           # read-only; JSON-serialisable; schema-validated
    created_by: str            # 'sensitivity_engine' | 'llm:claude-…' | 'human:naman'
    analysis_version: str
    created_at: datetime

    def sort_key(self) -> tuple:
        """Total order over a signal set. The reducer sorts by this before
        doing anything, which is what makes it order-independent."""
        return (str(self.kind), self.stage, self.created_by,
                _canonical(dict(self.payload)), self.signal_id)


def make_signal(*, event_id: str, company_id: int | None, stage: str,
                kind: str, payload: Mapping, created_by: str,
                analysis_version: str, created_at: datetime) -> Signal:
    validate_payload(kind, payload)
    frozen = MappingProxyType(dict(payload))
    return Signal(
        signal_id=signal_id_for(event_id, company_id, stage, kind, payload,
                                created_by, analysis_version, created_at),
        event_id=event_id, company_id=company_id, stage=stage,
        kind=SignalKind(kind), payload=frozen, created_by=created_by,
        analysis_version=analysis_version, created_at=created_at)
