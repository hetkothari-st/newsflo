"""TASK 4.1 -- the policy modifier registry.

`config/policy_modifiers.yaml` -> `PolicyRegistry` -> (only when an owner has
signed an entry) rows in `policy_modifier`.

THE SCAFFOLD RULE, which is the whole point of this module.

A registry entry has two states:

    SCAFFOLD   the entry names a real regime and says WHAT it needs -- which
               tag it acts on, which transfer function it is, which parameters
               are required, who must supply them. It has NO parameter values,
               no owner, and it can never be applied to anything.
    ACTIVE     a named human has supplied every required parameter, a source
               URL, an effective date and a review cadence.

Everything in the deployed file is SCAFFOLD, and `active_for` returns nothing
at all. That is not an unfinished implementation: producing a windfall levy
threshold or an administered gas ceiling from my own knowledge is precisely
what the master context's fabrication guard forbids, and a wrong one would be
invisible because it would make the output look MORE sophisticated. The gap
is recorded in DATA_GAPS.md §8 with an owner per entry.

`policy_modifier` therefore SHIPS EMPTY. `materialise` writes ACTIVE entries
only and refuses the rest -- there is no code path by which a scaffold row
reaches the table (`tests/phase4/test_no_fixture_data_reaches_production.py`).

PURE except for the YAML read and the SQL in `materialise` / `registry_from_db`.
No clock: every date comparison takes the caller's `as_of`.
"""
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

import json

import yaml
from sqlalchemy import text

from app.analysis.policy.transfer import (
    MODIFIER_TYPES, REQUIRED_PARAMETERS, TRANSFER_FUNCTIONS,
)

# backend/config/policy_modifiers.yaml
POLICY_REGISTRY_PATH = (
    Path(__file__).resolve().parents[3] / "config" / "policy_modifiers.yaml")

# The owner field of an entry nobody has taken responsibility for. The loader
# refuses to activate it, so this string is a structural refusal rather than a
# convention: it cannot be "forgotten" into production.
OWNER_PLACEHOLDER = "OWNER-REQUIRED"

STATUS_SCAFFOLD = "SCAFFOLD"
STATUS_ACTIVE = "ACTIVE"

# Spec §9's "maintain at minimum, for India". These are the modifier_ids the
# deployed file must scaffold; a test pins the set, so deleting one is a
# deliberate act rather than an omission.
MINIMUM_INDIA_REGISTRY = (
    "IN_SAED_WINDFALL_LEVY_CRUDE",
    "IN_SAED_WINDFALL_LEVY_PRODUCT_EXPORT",
    "IN_APM_GAS_CEILING",
    "IN_RETAIL_FUEL_REVISION_STATE",
    "IN_FUEL_EXCISE_AND_STATE_VAT",
    "IN_ATF_STATE_VAT",
    "IN_EXPORT_DUTY_STEEL",
    "IN_EXPORT_DUTY_RICE",
    "IN_EXPORT_DUTY_SUGAR",
    "IN_SUGAR_EXPORT_QUOTA",
    "IN_IMPORT_DUTY_EDIBLE_OIL",
    "IN_PLI_SCHEME",
    "IN_MSP_ANNOUNCEMENT",
    "IN_TELECOM_AGR_SPECTRUM",
    "IN_BANKING_RISK_WEIGHTS",
)


class PolicyRegistryError(ValueError):
    """A registry entry the loader will not accept at all -- as distinct from
    one it accepts and refuses to activate."""


@dataclass(frozen=True)
class PolicyModifier:
    """One row of `policy_modifier`, as the transfer layer sees it."""
    modifier_id: str
    applies_to_tag: str | None
    jurisdiction: str
    modifier_type: str
    parameters: Mapping[str, Any]
    effective_from: date | None
    effective_to: date | None
    source_url: str | None
    owner: str | None
    review_interval_days: int | None
    last_reviewed_at: date | None
    status: str
    note: str = ""
    pending_tag: str | None = None

    # --- what it is waiting for ------------------------------------------
    @property
    def required_parameters(self) -> tuple[str, ...]:
        return REQUIRED_PARAMETERS[self.modifier_type]

    @property
    def missing_parameters(self) -> tuple[str, ...]:
        return tuple(name for name in self.required_parameters
                     if self.parameters.get(name) is None)

    @property
    def owner_field_required(self) -> bool:
        return not self.owner or self.owner == OWNER_PLACEHOLDER

    @property
    def requires_state(self) -> bool:
        return self.modifier_type == "STATE_DEPENDENT"

    @property
    def state_key(self) -> str | None:
        value = self.parameters.get("state_key")
        return str(value) if value else None

    def is_active(self, as_of: date) -> bool:
        """In force on `as_of`, AND complete enough to be applied at all."""
        if self.status != STATUS_ACTIVE or self.effective_from is None:
            return False
        if as_of < self.effective_from:
            return False
        return self.effective_to is None or as_of <= self.effective_to

    def is_overdue(self, as_of: date) -> bool:
        """Past its review cadence. An ACTIVE modifier nobody has looked at
        for longer than its own review interval is a policy claim about today
        made on an old reading."""
        if self.last_reviewed_at is None or self.review_interval_days is None:
            return True
        return (as_of - self.last_reviewed_at).days > int(self.review_interval_days)

    def as_chip(self, status: str, note: str = "") -> dict:
        """The UI record (Task 4.4): what was applied, of what type, from
        which notification, and whether it actually fired."""
        return {"modifier_id": self.modifier_id,
                "modifier_type": self.modifier_type,
                "source_url": self.source_url,
                "status": status,
                "note": note or self.note}


def _as_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def modifier_from_mapping(raw: Mapping[str, Any]) -> PolicyModifier:
    """One YAML / JSON / DB mapping -> one `PolicyModifier`, with its status
    DECIDED HERE rather than trusted from the file.

    An entry is ACTIVE only when every one of these is true. Any of them
    false and it loads as SCAFFOLD and can never be applied:

      * a named owner that is not the placeholder;
      * every parameter its transfer function requires, non-null;
      * a source URL, an effective date, a review interval and a review date.
    """
    modifier_id = str(raw.get("modifier_id") or raw.get("id") or "").strip()
    if not modifier_id:
        raise PolicyRegistryError("a registry entry with no modifier_id")

    modifier_type = str(raw.get("modifier_type") or raw.get("type") or "")
    if modifier_type not in TRANSFER_FUNCTIONS:
        raise PolicyRegistryError(
            f"{modifier_id}: modifier_type {modifier_type!r} has no transfer "
            f"function; the closed set is {MODIFIER_TYPES}")

    parameters = raw.get("parameters")
    if isinstance(parameters, str):
        parameters = json.loads(parameters or "{}")
    parameters = dict(parameters or {})
    parameters.pop("_fixture", None)

    owner = raw.get("owner")
    owner = str(owner) if owner else None
    entry = PolicyModifier(
        modifier_id=modifier_id,
        applies_to_tag=(str(raw["applies_to_tag"])
                        if raw.get("applies_to_tag") else None),
        jurisdiction=str(raw.get("jurisdiction") or "IN"),
        modifier_type=modifier_type,
        parameters=parameters,
        effective_from=_as_date(raw.get("effective_from")),
        effective_to=_as_date(raw.get("effective_to")),
        source_url=(str(raw["source_url"]) if raw.get("source_url") else None),
        owner=owner,
        review_interval_days=(int(raw["review_interval_days"])
                              if raw.get("review_interval_days") is not None else None),
        last_reviewed_at=_as_date(raw.get("last_reviewed_at")),
        status=STATUS_SCAFFOLD,
        note=str(raw.get("note") or ""),
        pending_tag=(str(raw["pending_tag"]) if raw.get("pending_tag") else None),
    )
    complete = (
        not entry.owner_field_required
        and not entry.missing_parameters
        and entry.applies_to_tag is not None
        and entry.source_url is not None
        and entry.effective_from is not None
        and entry.review_interval_days is not None
        and entry.last_reviewed_at is not None
    )
    return PolicyModifier(**{**entry.__dict__,
                            "status": STATUS_ACTIVE if complete else STATUS_SCAFFOLD})


@dataclass(frozen=True)
class PolicyRegistry:
    entries: tuple[PolicyModifier, ...] = ()

    def active_for(self, exposure_tag: str,
                   as_of: date) -> tuple[PolicyModifier, ...]:
        """Every modifier in force on `as_of` for this tag, SORTED BY
        `modifier_id` -- the phase file's deterministic order, established
        here so no caller can accidentally depend on file order."""
        return tuple(sorted(
            (entry for entry in self.entries
             if entry.applies_to_tag == exposure_tag and entry.is_active(as_of)),
            key=lambda entry: entry.modifier_id))

    def by_id(self, modifier_id: str) -> PolicyModifier | None:
        for entry in self.entries:
            if entry.modifier_id == modifier_id:
                return entry
        return None

    def awaiting_parameters(self) -> tuple[PolicyModifier, ...]:
        """Every entry that cannot be applied because a number, an owner or a
        source is missing. This is the list DATA_GAPS.md §8 has to name."""
        return tuple(sorted(
            (entry for entry in self.entries if entry.status != STATUS_ACTIVE),
            key=lambda entry: entry.modifier_id))

    def overdue(self, as_of: date) -> tuple[PolicyModifier, ...]:
        return tuple(sorted(
            (entry for entry in self.entries
             if entry.status == STATUS_ACTIVE and entry.is_overdue(as_of)),
            key=lambda entry: entry.modifier_id))


def load_registry(path: Path | None = None) -> PolicyRegistry:
    return PolicyRegistry(_load_entries(path or POLICY_REGISTRY_PATH))


@lru_cache(maxsize=4)
def _load_entries(path: Path) -> tuple[PolicyModifier, ...]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return tuple(modifier_from_mapping(entry) for entry in (raw.get("modifiers") or []))


def registry_from_db(session, *, jurisdiction: str | None = None) -> PolicyRegistry:
    """The registry as the DATABASE holds it.

    This is what the sensitivity engine reads at runtime, and it is EMPTY in
    production. An empty registry is an identity transform, which is the
    correct degradation: no modifier is a statement that none is registered,
    never a statement that none applies.
    """
    sql = ("SELECT modifier_id, applies_to_tag, jurisdiction, modifier_type, "
           "parameters, effective_from, effective_to, source_url, owner, "
           "review_interval_days, last_reviewed_at FROM policy_modifier")
    parameters: dict = {}
    if jurisdiction is not None:
        sql += " WHERE jurisdiction = :jurisdiction"
        parameters["jurisdiction"] = jurisdiction
    sql += " ORDER BY modifier_id"
    rows = session.execute(text(sql), parameters).mappings()
    return PolicyRegistry(tuple(modifier_from_mapping(dict(row)) for row in rows))


def materialise(session, registry: PolicyRegistry) -> int:
    """Write the ACTIVE entries of a registry into `policy_modifier`.

    Returns the number of rows written. A SCAFFOLD entry is SKIPPED, not
    written with nulls: the table's contract is "these modifiers are in force
    and somebody owns them", and a row with a null threshold would be a
    modifier the application layer had to remember to distrust.
    """
    written = 0
    for entry in sorted(registry.entries, key=lambda e: e.modifier_id):
        if entry.status != STATUS_ACTIVE:
            continue
        session.execute(text(
            "INSERT OR REPLACE INTO policy_modifier (modifier_id, applies_to_tag, "
            "jurisdiction, modifier_type, parameters, effective_from, effective_to, "
            "source_url, owner, review_interval_days, last_reviewed_at) VALUES "
            "(:modifier_id, :applies_to_tag, :jurisdiction, :modifier_type, "
            ":parameters, :effective_from, :effective_to, :source_url, :owner, "
            ":review_interval_days, :last_reviewed_at)"), {
                "modifier_id": entry.modifier_id,
                "applies_to_tag": entry.applies_to_tag,
                "jurisdiction": entry.jurisdiction,
                "modifier_type": entry.modifier_type,
                "parameters": json.dumps(dict(entry.parameters), sort_keys=True),
                "effective_from": entry.effective_from.isoformat(),
                "effective_to": (entry.effective_to.isoformat()
                                 if entry.effective_to else None),
                "source_url": entry.source_url,
                "owner": entry.owner,
                "review_interval_days": entry.review_interval_days,
                "last_reviewed_at": entry.last_reviewed_at.isoformat(),
            })
        written += 1
    return written


def gap_report(registry: PolicyRegistry | None = None) -> Sequence[dict]:
    """One line per modifier awaiting real parameter values, for the DoD's
    "`DATA_GAPS.md` lists every modifier ... and names its owner"."""
    registry = registry or load_registry()
    return [{"modifier_id": entry.modifier_id,
             "modifier_type": entry.modifier_type,
             "applies_to_tag": entry.applies_to_tag or entry.pending_tag,
             "tag_status": "PENDING_VOCABULARY" if entry.applies_to_tag is None
                           else "IN_VOCABULARY",
             "missing_parameters": list(entry.missing_parameters),
             "owner": entry.owner or OWNER_PLACEHOLDER}
            for entry in registry.awaiting_parameters()]
