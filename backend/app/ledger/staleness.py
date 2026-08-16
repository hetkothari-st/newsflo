"""TASK 1.5 -- staleness.

An exposure is STALE when it is older than the freshness window its kind was
given at approval time (`company_exposure.freshness_days`, resolved from
config/freshness.yaml). A stale exposure may not back a PRIMARY claim: the
gate already carries `exposure_stale` as a hard block (app/core/gates.py),
and `company_exposure_is_stale` below is the function that finally supplies
it with a real answer instead of Phase 0's hard-coded False.

The flag is DERIVED, so the nightly job maintains it without holding the
reviewer capability -- the ledger's write guard is scoped to the claim
columns for exactly this reason.

Every function takes an explicit `as_of` date. Nothing here reads a clock:
the caller states the day it is asking about, and the answer is reproducible.
"""
from datetime import date, datetime, timezone
from typing import Sequence

from sqlalchemy import text

from app.ledger.db import commit_if_owned


def is_stale(as_of_date: date, freshness_days: int, as_of: date) -> bool:
    """The rule itself, as a pure function of three values."""
    return (as_of - as_of_date).days > int(freshness_days)


def flag_stale_exposures(session, *, as_of: date) -> int:
    """Set `stale` to what the rule says, for every row. Returns the number
    of rows whose flag CHANGED, so a second run reports 0 -- the job is
    idempotent and its output means "this many rows crossed the line".

    A row that was refreshed (a newer filing approved) is un-flagged by the
    same statement: staleness is a fact about a row's age, not a one-way
    door."""
    parameters = {"as_of": as_of.isoformat(), "checked": datetime.now(timezone.utc)}
    changed = session.execute(text(
        "UPDATE company_exposure SET stale = :stale_value, stale_checked_at = :checked "
        "WHERE stale <> :stale_value AND ("
        "  julianday(:as_of) - julianday(as_of_date) > freshness_days) = :stale_value"),
        dict(parameters, stale_value=1)).rowcount
    changed += session.execute(text(
        "UPDATE company_exposure SET stale = 0, stale_checked_at = :checked "
        "WHERE stale = 1 AND julianday(:as_of) - julianday(as_of_date) "
        "      <= freshness_days"), parameters).rowcount
    # Rows whose flag was already correct still get a fresh check timestamp,
    # so "when did we last look" is answerable for every row.
    session.execute(text(
        "UPDATE company_exposure SET stale_checked_at = :checked "
        "WHERE stale_checked_at IS NULL OR stale_checked_at < :checked"), parameters)
    commit_if_owned(session)
    return int(changed)


def company_exposure_is_stale(session, company_id: int, *, as_of: date,
                              exposure_tags: Sequence[str] | None = None) -> bool:
    """THE GATE INPUT (`ImpactDraft.exposure_stale`).

    True when at least one exposure that would back a claim about this
    company is past its freshness window. An EMPTY ledger returns False --
    the honest answer is "nothing here is stale", and abstention on an empty
    ledger comes from having no channel at all (see app/ledger/channels.py),
    never from a staleness flag we made up.

    Evaluated from the dates, not from the stored flag, so the answer cannot
    silently depend on whether the nightly job ran.
    """
    sql = ("SELECT count(*) FROM company_exposure "
           "WHERE company_id = :company_id "
           "  AND julianday(:as_of) - julianday(as_of_date) > freshness_days")
    parameters = {"company_id": int(company_id), "as_of": as_of.isoformat()}
    if exposure_tags is not None:
        tags = tuple(exposure_tags)
        if not tags:
            return False
        placeholders = ", ".join(f":tag{i}" for i in range(len(tags)))
        sql += f" AND exposure_tag IN ({placeholders})"
        parameters.update({f"tag{i}": tag for i, tag in enumerate(tags)})
    return bool(session.execute(text(sql), parameters).scalar())


def exposure_ages(session, *, as_of: date) -> list[int]:
    """Age in days of every exposure row, oldest last. Used by the coverage
    metrics; returns [] on an empty ledger rather than [0]."""
    rows = session.execute(text(
        "SELECT CAST(julianday(:as_of) - julianday(as_of_date) AS INTEGER) "
        "FROM company_exposure"), {"as_of": as_of.isoformat()}).all()
    return sorted(int(row[0]) for row in rows if row[0] is not None)
