"""TASK 4.1 / 4.2 -- `policy_state`, and when a regime stops being known.

    "If a company has an exposure tag that has ANY registered modifier for the
     current date and the modifier's state variable is UNKNOWN, the channel's
     uncertainty band is widened by the configured factor and evidence grade
     is capped at C. Unknown regime => humility, not silence."  -- spec §9.3

A state is NOT KNOWN in three distinct ways, and all three are treated the
same because all three mean the same thing to a reader:

  1. NOTHING IS RECORDED. No row for the key.
  2. THE ROW IS STALE. `as_of + freshness_days` is in the past. §9.3 makes
     this block PRIMARY as well (see `stale_keys`).
  3. THE ROW DOES NOT REACH THE HORIZON BEING EVALUATED. A freeze state
     measured with a 90-day freshness window says nothing about day 270, and
     carrying it forward to the structural horizon would be assuming a
     default regime at exactly the horizon where regimes change. This one is
     a CONTROLLER RULING rather than a line in the phase file; it is what
     makes the OMC structural horizon UNCERTAIN rather than an extrapolation
     of today's freeze, and it is recorded in the Phase 4 report.

The distinction between (2) and (3) matters for the gate: a STALE row is a
maintenance failure and blocks PRIMARY for the company; a row that simply
does not reach a far horizon is not anybody's failure, and it widens that
horizon without blocking the near one.

PURE except for the SQL read. No clock: `as_of` is always the caller's.
"""
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping

import json

from sqlalchemy import text

UNKNOWN_ABSENT = "ABSENT"
UNKNOWN_STALE = "STALE"
UNKNOWN_BEYOND_HORIZON = "BEYOND_HORIZON"


@dataclass(frozen=True)
class PolicyStateEntry:
    state_key: str
    state_value: Mapping[str, Any]
    as_of: date
    freshness_days: int
    source_url: str | None = None
    owner: str | None = None

    def is_stale(self, as_of: date) -> bool:
        return (as_of - self.as_of).days > int(self.freshness_days)

    def reaches(self, horizon_days: int) -> bool:
        """Whether this reading says anything about a point `horizon_days`
        forward. A 30-day reading does not describe day 270."""
        return int(horizon_days) <= int(self.freshness_days)

    @property
    def state(self) -> str | None:
        value = self.state_value.get("state")
        return str(value) if value is not None else None


def state_from_mapping(raw: Mapping[str, Any]) -> PolicyStateEntry:
    value = raw.get("state_value")
    if isinstance(value, str):
        value = json.loads(value or "{}")
    value = dict(value or {})
    value.pop("_fixture", None)
    as_of = raw["as_of"]
    return PolicyStateEntry(
        state_key=str(raw["state_key"]),
        state_value=value,
        as_of=as_of if isinstance(as_of, date) else date.fromisoformat(str(as_of)),
        freshness_days=int(raw["freshness_days"]),
        source_url=(str(raw["source_url"]) if raw.get("source_url") else None),
        owner=(str(raw["owner"]) if raw.get("owner") else None))


@dataclass(frozen=True)
class PolicyStateStore:
    entries: tuple[PolicyStateEntry, ...] = ()

    def get(self, state_key: str) -> PolicyStateEntry | None:
        for entry in self.entries:
            if entry.state_key == state_key:
                return entry
        return None

    def unknown_reason(self, state_key: str, *, as_of: date,
                       horizon_days: int) -> str | None:
        """Why this state is not usable at this horizon, or None when it is."""
        entry = self.get(state_key)
        if entry is None:
            return UNKNOWN_ABSENT
        if entry.is_stale(as_of):
            return UNKNOWN_STALE
        if not entry.reaches(horizon_days):
            return UNKNOWN_BEYOND_HORIZON
        return None

    def is_unknown_or_stale(self, state_key: str, *, as_of: date,
                            horizon_days: int) -> bool:
        return self.unknown_reason(
            state_key, as_of=as_of, horizon_days=horizon_days) is not None

    def state_of(self, state_key: str) -> str | None:
        entry = self.get(state_key)
        return entry.state if entry else None

    def stale_keys(self, state_keys, *, as_of: date) -> tuple[str, ...]:
        """The keys whose ROW EXISTS and is past its freshness window.

        This is the §9.3 input that blocks PRIMARY. A key with no row at all
        is deliberately NOT here: nobody promised to maintain a state nobody
        registered, and blocking PRIMARY on it would make every unregistered
        regime a publication failure.
        """
        out = []
        for key in sorted(set(state_keys)):
            entry = self.get(key)
            if entry is not None and entry.is_stale(as_of):
                out.append(key)
        return tuple(out)


def state_store_from_db(session) -> PolicyStateStore:
    """The tracked regime states as the DATABASE holds them.

    EMPTY in production: every state variable §9.3 names (whether OMC price
    revisions are currently permitted, the current SAED rate) is a reading
    somebody has to take and nobody has. An empty store means every
    STATE_DEPENDENT modifier is UNKNOWN, which widens and caps rather than
    assuming a regime -- the correct degradation, and the one the phase file
    asks for.
    """
    rows = session.execute(text(
        "SELECT state_key, state_value, as_of, freshness_days, source_url, owner "
        "FROM policy_state ORDER BY state_key")).mappings()
    return PolicyStateStore(tuple(state_from_mapping(dict(row)) for row in rows))
