"""STAGE D -- proposals land in `exposure_proposal`, never in the ledger.

`ExposureProposal` is the phase file's dataclass, with `source_page` and
`excerpt` MANDATORY by contract (a proposal may be constructed without them,
and is then discarded by the gate -- which is the point: the discard is
RECORDED, with a reason, rather than the object being impossible to build
and the failure invisible).

WHAT IS WRITTEN. Every proposal is written, passing or failing. A failing one
carries `status = 'REJECTED_UNVERBATIM'` and a `reject_reason`, so a
fabricated excerpt is visible in the review console and countable in
`extractor_quality` (master context invariant 12: rejected candidates are
retained with a reason). Silently dropping them would hide exactly the signal
that an extraction prompt has started inventing.

This module writes ONE table: `exposure_proposal`. It cannot write
`company_exposure` -- the database refuses it.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Sequence

import logging
import uuid

from sqlalchemy import text

from app.ingest.filings.documents import SourceDocument
from app.ledger.db import commit_if_owned
from app.ingest.filings.verbatim import check_excerpt

logger = logging.getLogger(__name__)


@dataclass
class ExposureProposal:
    """The phase file's Stage C output, plus the provenance this repo's
    ledger needs. Nothing here is a decision -- it is a claim awaiting one."""
    company_id: int
    exposure_kind: str
    exposure_tag: str
    share_of_base: float | None
    base_kind: str
    source_page: str            # MANDATORY -- page/section locating the claim
    excerpt: str                # MANDATORY -- verbatim text from the filing
    extraction_confidence: float | None
    model_id: str | None
    created_by: str             # 'ingest:…' (deterministic) | 'llm:…'
    # Empty means "the document this was extracted from", which
    # `record_proposals` resolves from the SourceDocument. It is never left
    # empty in a stored row: `exposure_proposal.source_url` is NOT NULL.
    source_url: str = ""
    measurement: str = "FILED"
    source_type: str = "ANNUAL_REPORT"
    base_value_inr: float | None = None
    as_of_date: date | None = None
    extractor_version: str | None = None
    segment_id: str | None = None
    proposal_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass(frozen=True)
class ProposalOutcome:
    accepted: int
    rejected: int
    accepted_ids: tuple[str, ...] = ()
    rejected_ids: tuple[str, ...] = ()


_COLUMNS = (
    "proposal_id", "company_id", "exposure_kind", "exposure_tag", "share_of_base",
    "base_kind", "base_value_inr", "measurement", "source_type", "source_url",
    "source_page", "excerpt", "extraction_confidence", "model_id", "created_by",
    "extractor_version", "document_sha256", "as_of_date", "status",
    "reject_reason", "created_at",
)


def _row(proposal: ExposureProposal, document: SourceDocument, *, status: str,
         reason: str | None) -> dict[str, Any]:
    return {
        "proposal_id": proposal.proposal_id,
        "company_id": int(proposal.company_id),
        "exposure_kind": proposal.exposure_kind,
        "exposure_tag": proposal.exposure_tag,
        "share_of_base": proposal.share_of_base,
        "base_kind": proposal.base_kind,
        "base_value_inr": proposal.base_value_inr,
        "measurement": proposal.measurement,
        "source_type": proposal.source_type,
        # The proposal's own URL wins only if it has one; otherwise the
        # document it was extracted from is the source, by construction.
        "source_url": proposal.source_url or document.url,
        "source_page": proposal.source_page or None,
        "excerpt": proposal.excerpt or None,
        "extraction_confidence": proposal.extraction_confidence,
        "model_id": proposal.model_id,
        "created_by": proposal.created_by,
        "extractor_version": proposal.extractor_version,
        "document_sha256": document.sha256,
        "as_of_date": proposal.as_of_date,
        "status": status,
        "reject_reason": reason,
        "created_at": datetime.now(timezone.utc),
    }


def record_proposals(session, proposals: Sequence[ExposureProposal],
                     document: SourceDocument) -> ProposalOutcome:
    """Run the verbatim gate over each proposal and write the result.

    Passing -> PENDING_REVIEW. Failing -> REJECTED_UNVERBATIM + reason.
    Neither one touches `company_exposure`.
    """
    accepted: list[str] = []
    rejected: list[str] = []
    for proposal in proposals:
        result = check_excerpt(document, excerpt=proposal.excerpt,
                               source_page=proposal.source_page)
        status = "PENDING_REVIEW" if result.ok else "REJECTED_UNVERBATIM"
        row = _row(proposal, document, status=status, reason=result.reason)
        session.execute(text(
            f"INSERT INTO exposure_proposal ({', '.join(_COLUMNS)}) VALUES "
            f"({', '.join(':' + c for c in _COLUMNS)})"), row)
        (accepted if result.ok else rejected).append(proposal.proposal_id)
        if not result.ok:
            logger.warning(
                "[ledger] discarded proposal %s from %s: %s (%s)",
                proposal.proposal_id, proposal.created_by, result.reason,
                document.url)
    commit_if_owned(session)
    return ProposalOutcome(len(accepted), len(rejected), tuple(accepted),
                           tuple(rejected))
