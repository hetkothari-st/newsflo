"""TASK 3.2 -- reading the exposure tag index.

`exposure_index` is a VIEW over `company_exposure` (migration 0013): rows
with a meaningful share, on companies nothing has been recorded against.
Discovery reads it and nothing else; it never reads `company_exposure`
directly, so the index's pruning rule cannot be bypassed by accident.

STALENESS. A materialized view needs a refresh and therefore has a staleness
of its own. A plain SQLite view does not -- it is always current. What CAN be
stale is the DATA: an exposure row measured against a filing that is two
years old. `index_staleness` reports that, which is the number an operator
actually needs.
"""
from dataclasses import dataclass
from datetime import date
from typing import Sequence

from sqlalchemy import text


@dataclass(frozen=True)
class IndexStaleness:
    rows: int
    max_age_days: int | None
    median_age_days: int | None
    stale_rows: int


def query_exposure_index(session, exposure_tag: str, *, min_share: float,
                         as_of: date | None = None) -> list[dict]:
    """Every indexed exposure to `exposure_tag` at or above `min_share`,
    strongest first.

    `as_of`, when given, additionally drops rows whose freshness window has
    closed. Staleness is evaluated from the DATES rather than the stored
    `stale` flag, so the answer does not depend on whether the nightly job
    ran (Phase 1's rule, unchanged).
    """
    sql = ("SELECT * FROM exposure_index "
           "WHERE exposure_tag = :tag AND share_of_base >= :min_share")
    parameters: dict = {"tag": exposure_tag, "min_share": float(min_share)}
    if as_of is not None:
        sql += (" AND julianday(:as_of) - julianday(as_of_date) "
                "<= freshness_days")
        parameters["as_of"] = as_of.isoformat()
    sql += " ORDER BY share_of_base DESC, company_id ASC"
    return [dict(row) for row in
            session.execute(text(sql), parameters).mappings().all()]


def query_exposure_index_many(session, exposure_tags: Sequence[str], *,
                              min_share: float,
                              as_of: date | None = None) -> list[dict]:
    """The same query over several tags at once, for the peer sweep."""
    tags = tuple(dict.fromkeys(exposure_tags))
    if not tags:
        return []
    placeholders = ", ".join(f":tag{i}" for i in range(len(tags)))
    sql = (f"SELECT * FROM exposure_index WHERE exposure_tag IN ({placeholders}) "
           "AND share_of_base >= :min_share")
    parameters: dict = {"min_share": float(min_share)}
    parameters.update({f"tag{i}": tag for i, tag in enumerate(tags)})
    if as_of is not None:
        sql += (" AND julianday(:as_of) - julianday(as_of_date) "
                "<= freshness_days")
        parameters["as_of"] = as_of.isoformat()
    sql += " ORDER BY share_of_base DESC, company_id ASC"
    return [dict(row) for row in
            session.execute(text(sql), parameters).mappings().all()]


def index_staleness(session, *, as_of: date) -> IndexStaleness | None:
    """How old is what discovery can see? `None` when the index is empty --
    an empty index has no age, and reporting 0 would read as "brand new"."""
    rows = [dict(row) for row in session.execute(text(
        "SELECT as_of_date, freshness_days FROM exposure_index"
    )).mappings().all()]
    if not rows:
        return None

    ages = sorted(
        (as_of - date.fromisoformat(str(row["as_of_date"]))).days for row in rows)
    stale = sum(
        1 for row in rows
        if (as_of - date.fromisoformat(str(row["as_of_date"]))).days
        > int(row["freshness_days"]))
    middle = len(ages) // 2
    median = (ages[middle] if len(ages) % 2
              else (ages[middle - 1] + ages[middle]) // 2)
    return IndexStaleness(rows=len(rows), max_age_days=ages[-1],
                          median_age_days=median, stale_rows=stale)
