"""STAGE B -- deterministic loaders for the structured tables.

`company_segment` and `company_financials` hold TRANSCRIBED filing lines, not
inferences: an Ind AS 108 segment note row, a P&L schedule line, a borrowings
split, a forex earnings/expenditure note. They are therefore written directly
by these loaders rather than through the proposal queue -- but under the same
law as everything else: NO SOURCE_URL, NO ROW.

What does NOT come through here is anything interpretive. An exposure (this
company is 28% exposed to naphtha) is a claim, not a transcription, and
always goes through `exposure_proposal` and human review -- including when a
deterministic parser produced it, which is why deterministic proposals are
merely BULK-approvable rather than auto-approved.

These loaders are never called on a schedule. An operator runs them against
a document they have acquired; nothing here fetches, guesses or fills.
"""
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import uuid

from sqlalchemy import text

from app.ledger.db import commit_if_owned


class LoaderError(ValueError):
    """A row that cannot be written honestly."""


_SEGMENT_COLUMNS = ("segment_id", "company_id", "segment_name", "revenue_inr",
                    "ebitda_inr", "revenue_share", "ebitda_share", "fiscal_year",
                    "source_url", "source_page", "as_of_date", "created_by",
                    "created_at")

_FINANCIAL_COLUMNS = ("company_id", "fiscal_period", "revenue_inr", "ebitda_inr",
                      "pat_inr", "cogs_inr", "raw_material_inr", "power_fuel_inr",
                      "freight_inr", "employee_inr", "gross_debt_inr",
                      "floating_debt_inr", "fx_earnings_inr", "fx_expenditure_inr",
                      "source_url", "as_of_date", "created_by")


def _require(row: Mapping[str, Any], fields: Sequence[str], what: str) -> None:
    missing = [field for field in fields
               if row.get(field) in (None, "")]
    if missing:
        raise LoaderError(
            f"{what} row is missing {', '.join(missing)} -- a ledger row that "
            "cannot be traced to a document is not a ledger row")


def load_segments(session, rows: Sequence[Mapping[str, Any]],
                  *, created_by: str = "ingest:segment_note_v0") -> int:
    """Ind AS 108 segment note lines -> `company_segment`."""
    written = 0
    for row in rows:
        _require(row, ("company_id", "segment_name", "fiscal_year", "source_url",
                       "as_of_date"), "company_segment")
        payload = {column: row.get(column) for column in _SEGMENT_COLUMNS}
        payload["segment_id"] = row.get("segment_id") or str(uuid.uuid4())
        payload["created_by"] = row.get("created_by") or created_by
        payload["created_at"] = datetime.now(timezone.utc)
        session.execute(text(
            f"INSERT INTO company_segment ({', '.join(_SEGMENT_COLUMNS)}) VALUES "
            f"({', '.join(':' + c for c in _SEGMENT_COLUMNS)})"), payload)
        written += 1
    commit_if_owned(session)
    return written


def load_financials(session, rows: Sequence[Mapping[str, Any]],
                    *, created_by: str = "ingest:xbrl_v0") -> int:
    """P&L / borrowings / forex lines -> `company_financials`.

    Upserts on (company_id, fiscal_period): a later, more complete filing
    replaces an earlier partial one. A column absent from the incoming row
    is left as it was -- never overwritten with NULL, and never invented."""
    written = 0
    for row in rows:
        _require(row, ("company_id", "fiscal_period", "source_url", "as_of_date"),
                 "company_financials")
        payload = {column: row.get(column) for column in _FINANCIAL_COLUMNS}
        payload["created_by"] = row.get("created_by") or created_by
        present = [c for c in _FINANCIAL_COLUMNS if payload.get(c) is not None]
        updates = ", ".join(f"{c} = excluded.{c}" for c in present
                            if c not in ("company_id", "fiscal_period"))
        session.execute(text(
            f"INSERT INTO company_financials ({', '.join(_FINANCIAL_COLUMNS)}) "
            f"VALUES ({', '.join(':' + c for c in _FINANCIAL_COLUMNS)}) "
            f"ON CONFLICT (company_id, fiscal_period) DO UPDATE SET {updates}"),
            payload)
        written += 1
    commit_if_owned(session)
    return written
