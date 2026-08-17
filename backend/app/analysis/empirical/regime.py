"""TASK 5.2 -- the REGIME_CHANGED annotation (spec §10.3).

    "If a human reviewer marks the conflict REGIME_CHANGED with a reason,
     PRIMARY becomes available for that shock class going forward,
     recorded with an expiry date."

Three properties, each enforced rather than promised:

  * A REASON is required. "History disagrees and I have decided to ignore it"
    is a claim about the world and it needs an argument attached.
  * AN AUTHOR is required. This annotation is what lets a company make a
    PRIMARY call against its own measured history; somebody owns that.
  * AN EXPIRY is required, and there is no "permanent" option. A regime claim
    nobody re-affirms is a regime claim nobody is maintaining -- the same rule
    Phase 4 applied to `policy_state`. Past `expires_on` the annotation is
    inert and the conflict caps the tier again.

The annotation NEVER changes the empirical status. The record keeps saying
CONFLICT, because that is what history said; what the annotation changes is
whether that conflict is allowed to block a PRIMARY call.
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import hashlib

from sqlalchemy import text


class RegimeChangeRefused(ValueError):
    """An annotation missing a reason, an author or an expiry."""


def shock_class(variable: str, sign: str) -> str:
    """The (company, shock_class) scope §10.3 names. One spelling, here."""
    return f"{variable}:{sign}"


@dataclass(frozen=True)
class RegimeChange:
    company_id: int
    shock_class: str
    reason: str
    reviewed_by: str
    effective_from: date
    expires_on: date
    review_id: str | None = None

    def is_active(self, as_of: date) -> bool:
        return self.effective_from <= as_of <= self.expires_on


def annotation_id_for(company_id: int, shock_class_value: str,
                      effective_from: date) -> str:
    digest = hashlib.sha256(
        f"{company_id}|{shock_class_value}|{effective_from.isoformat()}"
        .encode("utf-8")).hexdigest()
    return f"regime:{digest[:24]}"


def record_regime_change(session, *, company_id: int, shock_class: str,
                         reason: str, reviewed_by: str, effective_from: date,
                         expires_on: date | None, review_id: str | None = None,
                         created_at: datetime | None = None) -> str:
    """Write the annotation. Refuses an incomplete one rather than filling a
    gap with a default -- a defaulted expiry would be a maintenance promise
    nobody made."""
    if not str(reason or "").strip():
        raise RegimeChangeRefused(
            "a REGIME_CHANGED annotation needs a reason: it overrides measured "
            "history for this company")
    if not str(reviewed_by or "").strip():
        raise RegimeChangeRefused(
            "a REGIME_CHANGED annotation needs a named reviewer")
    if expires_on is None:
        raise RegimeChangeRefused(
            "a REGIME_CHANGED annotation needs an expiry date (§10.3). There "
            "is no permanent option: a regime claim nobody re-affirms is a "
            "regime claim nobody is maintaining")
    if expires_on < effective_from:
        raise RegimeChangeRefused(
            f"expires_on {expires_on} is before effective_from {effective_from}")

    annotation_id = annotation_id_for(company_id, shock_class, effective_from)
    session.execute(text(
        "INSERT INTO regime_change (annotation_id, company_id, shock_class, "
        "reason, reviewed_by, effective_from, expires_on, review_id, created_at) "
        "VALUES (:annotation_id, :company_id, :shock_class, :reason, "
        ":reviewed_by, :effective_from, :expires_on, :review_id, :created_at) "
        "ON CONFLICT (annotation_id) DO UPDATE SET "
        " reason = excluded.reason, reviewed_by = excluded.reviewed_by, "
        " expires_on = excluded.expires_on, review_id = excluded.review_id"), {
            "annotation_id": annotation_id, "company_id": company_id,
            "shock_class": shock_class, "reason": reason,
            "reviewed_by": reviewed_by,
            "effective_from": effective_from.isoformat(),
            "expires_on": expires_on.isoformat(), "review_id": review_id,
            "created_at": (created_at
                           or datetime.now(timezone.utc)).isoformat()})
    return annotation_id


def active_regime_change(session, *, company_id: int, shock_class: str,
                         as_of: date) -> RegimeChange | None:
    """The annotation in force on `as_of`, or None. An expired one is not
    returned -- it is inert, not merely old."""
    row: Any = session.execute(text(
        "SELECT company_id, shock_class, reason, reviewed_by, effective_from, "
        "expires_on, review_id FROM regime_change WHERE company_id = :company_id "
        "AND shock_class = :shock_class AND effective_from <= :as_of "
        "AND expires_on >= :as_of ORDER BY effective_from DESC"), {
            "company_id": company_id, "shock_class": shock_class,
            "as_of": as_of.isoformat()}).mappings().first()
    if row is None:
        return None
    return RegimeChange(
        company_id=int(row["company_id"]), shock_class=str(row["shock_class"]),
        reason=str(row["reason"]), reviewed_by=str(row["reviewed_by"]),
        effective_from=_as_date(row["effective_from"]),
        expires_on=_as_date(row["expires_on"]),
        review_id=(None if row["review_id"] is None else str(row["review_id"])))


def _as_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])
