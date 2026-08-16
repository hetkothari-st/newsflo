"""TASK 1.4 -- the review workflow. THE ONLY WRITER of `company_exposure`.

Deliberately IMPURE (it is the DB boundary) and deliberately the only place
in the codebase that opens a `review_session`. Everything else in the
process -- the extraction pipeline, the API, the scheduler, a one-off script
-- is refused by the database itself.

HOW THE GUARD WORKS (SQLite substitution for the Postgres reviewer role,
ruled binding by the controller; the DDL is in migration 0012's docstring):

    with review_session(session):          # CREATE TEMP TABLE _newsflo_…
        session.execute(insert_into_company_exposure)
    # temp table dropped -> the very next statement is refused again

`app/models.py`'s triggers check for that temp table on every INSERT and on
every UPDATE of a CLAIM column. `stale` is deliberately outside that guard:
it is derived, and the nightly job that maintains it holds no reviewer
privilege.

THE RULES, each enforced here rather than trusted:
  * approval requires a named reviewer;
  * a proposal that failed the verbatim gate can never be approved;
  * a missing `share_of_base` or `base_value_inr` blocks approval -- it is
    never defaulted to a plausible number;
  * `freshness_days` comes from config/freshness.yaml, and an exposure kind
    the policy does not name must be given one explicitly;
  * bulk approve is for DETERMINISTIC extractors only ('ingest:…'), never
    for an LLM proposal.

`session` here is anything with `.execute()` -- a SQLAlchemy Session or a
Connection -- so the standalone review UI can use the same functions over
`engine.begin()`.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

import logging
import uuid

from sqlalchemy import text

from app.ledger.db import commit_if_owned
from app.ledger.freshness import FreshnessNotConfigured, freshness_days_for
from app.ledger.vocabulary import (
    BASE_KINDS, EXPOSURE_KINDS, MEASUREMENTS, SOURCE_TYPES, VocabularyError,
    check, check_exposure_tag,
)

logger = logging.getLogger(__name__)

LEDGER_REVIEW_SESSION_TABLE = "_newsflo_ledger_review_session"

# Only a proposal made by a DETERMINISTIC extractor may be bulk approved
# (phase file Task 1.4). The prefix is the contract.
DETERMINISTIC_PREFIX = "ingest:"
LLM_PREFIX = "llm:"

# Columns the approval path writes. Explicit so a new column cannot start
# being written by accident.
_EXPOSURE_COLUMNS = (
    "exposure_id", "company_id", "segment_id", "exposure_kind", "exposure_tag",
    "share_of_base", "base_kind", "base_value_inr", "measurement",
    "source_type", "source_url", "source_page", "as_of_date", "freshness_days",
    "confidence", "created_by", "reviewed_by", "proposal_id",
)

# A reviewer may correct these and nothing else. Provenance (source_url,
# excerpt, created_by, document_sha256) is what the row IS -- editing it
# would make the audit trail describe a different claim.
EDITABLE_FIELDS = ("exposure_kind", "exposure_tag", "share_of_base", "base_kind",
                   "base_value_inr", "measurement", "source_page", "as_of_date",
                   "segment_id", "freshness_days", "confidence")


class LedgerReviewError(RuntimeError):
    """An approval or rejection that must not happen."""


@contextmanager
def review_session(session):
    """Grant THIS connection the reviewer capability, for the duration of the
    block. Nothing else in the codebase may call this."""
    session.execute(text(
        f"CREATE TEMP TABLE IF NOT EXISTS {LEDGER_REVIEW_SESSION_TABLE} "
        "(granted INTEGER)"))
    try:
        yield session
    finally:
        # Dropped in a `finally` so an exception cannot leave a connection
        # holding a write privilege it should not have.
        session.execute(text(f"DROP TABLE IF EXISTS temp.{LEDGER_REVIEW_SESSION_TABLE}"))


def _rows(result) -> list[dict]:
    return [dict(row) for row in result.mappings().all()]


# --- the queue -------------------------------------------------------------

def pending_queue(session, *, limit: int = 200) -> list[dict]:
    """PENDING_REVIEW proposals, most valuable first.

    Order is (market cap x extraction uncertainty), per the phase file: the
    biggest company whose extraction we are least sure about is the one worth
    a human minute. `companies.market_cap` is the cap proxy this repo has;
    a company with no recorded cap sorts LAST rather than being given an
    invented one (COALESCE to 0 is an ordering choice, not a value written
    anywhere)."""
    return _rows(session.execute(text(
        "SELECT p.*, c.ticker AS ticker, c.name AS company_name, "
        "       c.market_cap AS market_cap, "
        "       COALESCE(c.market_cap, 0) * (1.0 - COALESCE(p.extraction_confidence, 0)) "
        "         AS review_priority "
        "FROM exposure_proposal p JOIN companies c ON c.id = p.company_id "
        "WHERE p.status = 'PENDING_REVIEW' "
        "ORDER BY review_priority DESC, p.created_at ASC, p.proposal_id ASC "
        "LIMIT :limit"), {"limit": limit}))


def get_proposal(session, proposal_id: str) -> dict | None:
    rows = _rows(session.execute(text(
        "SELECT p.*, c.ticker AS ticker, c.name AS company_name "
        "FROM exposure_proposal p JOIN companies c ON c.id = p.company_id "
        "WHERE p.proposal_id = :id"), {"id": proposal_id}))
    return rows[0] if rows else None


# --- approval --------------------------------------------------------------

def _validated(proposal: Mapping[str, Any]) -> dict:
    """Everything the ledger row needs, or an error naming what is missing.
    Nothing here supplies a value the proposal did not carry."""
    missing = [field for field in ("share_of_base", "base_value_inr")
               if proposal.get(field) is None]
    if missing:
        raise LedgerReviewError(
            f"proposal {proposal.get('proposal_id')} has no {', '.join(missing)}. "
            "Missing is missing -- edit the proposal with the value from the "
            "filing, or reject it. It is never defaulted.")
    try:
        row = {
            "exposure_kind": check(proposal["exposure_kind"], EXPOSURE_KINDS,
                                   "exposure_kind"),
            "exposure_tag": check_exposure_tag(proposal["exposure_tag"]),
            "base_kind": check(proposal["base_kind"], BASE_KINDS, "base_kind"),
            "measurement": check(proposal["measurement"], MEASUREMENTS, "measurement"),
            "source_type": check(proposal["source_type"], SOURCE_TYPES, "source_type"),
        }
    except VocabularyError as exc:
        raise LedgerReviewError(str(exc)) from exc

    if not proposal.get("source_url"):
        raise LedgerReviewError("a ledger row without a source_url is not a ledger row")
    if proposal.get("as_of_date") is None:
        raise LedgerReviewError(
            "proposal has no as_of_date -- an undated disclosure cannot be aged")
    return row


def _freshness_days(proposal: Mapping[str, Any]) -> int:
    explicit = proposal.get("freshness_days")
    if explicit is not None:
        return int(explicit)
    try:
        return freshness_days_for(proposal["exposure_kind"])
    except FreshnessNotConfigured as exc:
        raise LedgerReviewError(str(exc)) from exc


def approve_proposal(session, proposal_id: str, *, reviewed_by: str,
                     edits: Mapping[str, Any] | None = None) -> str:
    """APPROVE / EDIT+APPROVE. Returns the new `exposure_id`.

    This is the ONLY function in the codebase that writes `company_exposure`.
    `created_by` on the ledger row keeps recording the extractor/model that
    PROPOSED it; `reviewed_by` records the human who accepted it. The two are
    never merged."""
    reviewer = (reviewed_by or "").strip()
    if not reviewer:
        raise LedgerReviewError("approval requires a named reviewer")

    proposal = get_proposal(session, proposal_id)
    if proposal is None:
        raise LedgerReviewError(f"no such proposal {proposal_id!r}")
    if proposal["status"] != "PENDING_REVIEW":
        raise LedgerReviewError(
            f"proposal {proposal_id} is {proposal['status']}, not PENDING_REVIEW. "
            "A proposal that failed the verbatim gate is never approvable.")

    edits = {k: v for k, v in (edits or {}).items() if v is not None}
    unknown = set(edits) - set(EDITABLE_FIELDS)
    if unknown:
        raise LedgerReviewError(
            f"not editable at review time: {sorted(unknown)} -- provenance is "
            "what the row IS, and editing it would describe a different claim")

    merged = dict(proposal, **edits)
    checked = _validated(merged)
    exposure_id = str(uuid.uuid4())
    row = {
        "exposure_id": exposure_id,
        "company_id": int(merged["company_id"]),
        "segment_id": merged.get("segment_id"),
        "share_of_base": float(merged["share_of_base"]),
        "base_value_inr": float(merged["base_value_inr"]),
        "source_url": merged["source_url"],
        "source_page": merged.get("source_page"),
        "as_of_date": merged["as_of_date"],
        "freshness_days": _freshness_days(merged),
        # The extractor's own confidence in the extraction. Not a claim about
        # the world, and not adjusted here.
        "confidence": float(merged.get("extraction_confidence") or 0.0),
        "created_by": merged["created_by"],
        "reviewed_by": reviewer,
        "proposal_id": proposal_id,
        **checked,
    }

    with review_session(session):
        session.execute(text(
            f"INSERT INTO company_exposure ({', '.join(_EXPOSURE_COLUMNS)}) VALUES "
            f"({', '.join(':' + c for c in _EXPOSURE_COLUMNS)})"), row)
        session.execute(text(
            "UPDATE exposure_proposal SET status = 'APPROVED', reviewed_by = :who, "
            "reviewed_at = :when, edited = :edited, exposure_id = :exposure_id "
            "WHERE proposal_id = :id"), {
                "who": reviewer, "when": datetime.now(timezone.utc),
                "edited": 1 if edits else 0, "exposure_id": exposure_id,
                "id": proposal_id})
    # COMMITTED OUTSIDE THE BLOCK, deliberately. A Session.commit() releases
    # the connection back to the pool, and a SQLite TEMP table lives on the
    # CONNECTION -- committing while the capability token still existed could
    # hand the next borrower of that connection the right to write the
    # ledger. Dropping first (inside the same transaction, and before any
    # commit) makes that impossible. The triggers fire at INSERT time, not at
    # commit time, so the write above is unaffected.
    commit_if_owned(session)
    logger.info("[ledger] %s approved proposal %s -> exposure %s",
                reviewer, proposal_id, exposure_id)
    return exposure_id


def reject_proposal(session, proposal_id: str, *, reviewed_by: str, reason: str) -> None:
    """REJECT. The reason is mandatory and the row is retained: master
    context invariant 12 -- rejected candidates stay visible."""
    reviewer = (reviewed_by or "").strip()
    if not reviewer:
        raise LedgerReviewError("rejection requires a named reviewer")
    if not (reason or "").strip():
        raise LedgerReviewError("rejection requires a reason")

    result = session.execute(text(
        "UPDATE exposure_proposal SET status = 'REJECTED', reviewed_by = :who, "
        "reviewed_at = :when, reject_reason = :reason "
        "WHERE proposal_id = :id AND status = 'PENDING_REVIEW'"), {
            "who": reviewer, "when": datetime.now(timezone.utc),
            "reason": reason.strip(), "id": proposal_id})
    if not result.rowcount:
        raise LedgerReviewError(
            f"proposal {proposal_id!r} is not PENDING_REVIEW (or does not exist)")
    commit_if_owned(session)


def bulk_approve(session, proposal_ids: Sequence[str], *, reviewed_by: str) -> list[str]:
    """Bulk approve, permitted ONLY for deterministic extractors.

    Checked BEFORE anything is written, so a mixed batch approves nothing --
    a partially applied bulk approve is how an LLM proposal slips into the
    ledger under cover of a batch of XBRL rows."""
    proposals = [get_proposal(session, pid) for pid in proposal_ids]
    for proposal_id, proposal in zip(proposal_ids, proposals):
        if proposal is None:
            raise LedgerReviewError(f"no such proposal {proposal_id!r}")
        created_by = str(proposal["created_by"])
        if not created_by.startswith(DETERMINISTIC_PREFIX):
            raise LedgerReviewError(
                f"proposal {proposal_id} was made by {created_by!r}. Bulk approve "
                "is for deterministic extractors (XBRL / segment note) only -- an "
                "LLM proposal is read one at a time, by a human, or not at all.")
    return [approve_proposal(session, pid, reviewed_by=reviewed_by)
            for pid in proposal_ids]


def approved_exposures(session, *, limit: int = 200) -> list[dict]:
    return _rows(session.execute(text(
        "SELECT e.*, c.ticker AS ticker FROM company_exposure e "
        "JOIN companies c ON c.id = e.company_id "
        "ORDER BY e.created_at DESC LIMIT :limit"), {"limit": limit}))


def reviewer_throughput(session) -> list[dict]:
    """Task 1.4's reviewer-throughput half of `extractor_quality`."""
    return _rows(session.execute(text(
        "SELECT reviewed_by AS reviewer, "
        "       count(*) AS reviewed, "
        "       sum(CASE WHEN status = 'APPROVED' THEN 1 ELSE 0 END) AS approved, "
        "       sum(CASE WHEN edited = 1 THEN 1 ELSE 0 END) AS edited "
        "FROM exposure_proposal WHERE reviewed_by IS NOT NULL "
        "GROUP BY reviewed_by ORDER BY reviewed DESC")))


def iter_editable_fields() -> Iterable[str]:
    return EDITABLE_FIELDS
