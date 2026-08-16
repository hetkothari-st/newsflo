"""STAGE C -- LLM extraction of unstructured filing content.

Only for what a deterministic parser cannot read: the raw-material BREAKUP by
commodity, hedging policy statements, pricing and pass-through commentary in
MD&A and earnings calls.

THREE HARD RULES, all structural rather than instructed:

1. THE CLIENT IS INJECTED. This module constructs nothing, imports no
   provider SDK and reads no API key. It calls `client.generate(prompt)` and
   nothing else, so a test hands it a stub and the suite makes zero network
   calls by construction, not by mocking a global.

2. THE OUTPUT IS A PROPOSAL, NEVER A WRITE. `propose()` returns a list of
   `ExposureProposal`. This module cannot write `company_exposure` -- the
   database refuses it, and tests/phase1/test_no_direct_write.py ast-scans
   this package for the attempt.

3. NOTHING IS FILLED IN. A model row without an `excerpt`, without a
   `source_page`, or without a `share_of_base` is DROPPED here, before it
   even reaches the verbatim gate. "Missing is missing" (phase file DO NOT):
   a plausible default at this seam would become a permanent ledger row.
   Every drop is collected on `self.dropped` and the caller PERSISTS it via
   `proposals.record_malformed` -- a drop that lives only in memory is a
   regression `extractor_quality` cannot see (fix round 1, I3).

The prompt asks for the excerpt to be copied verbatim, but the ask is not
the guarantee -- `verbatim.check_excerpt` is, and it runs over every
proposal in `proposals.record_proposals` regardless of what the model
claimed.
"""
from datetime import date
from typing import Any, Protocol, Sequence

import json
import logging

from app.ingest.filings.documents import SourceDocument
from app.ingest.filings.proposals import DroppedRow, ExposureProposal
from app.ledger.vocabulary import (
    BASE_KINDS, EXPOSURE_KINDS, MEASUREMENTS, SOURCE_TYPES,
)

logger = logging.getLogger(__name__)

EXTRACTOR_NAME = "exposure_extractor"

PROMPT_TEMPLATE = """You are reading one company's regulatory filing.

Extract ONLY exposures the document STATES. Do not infer, do not estimate,
do not use anything you know about this company from outside this document.

For each exposure return an object with:
  exposure_kind: one of {exposure_kinds}
  exposure_tag:  a 'family:leaf' tag, e.g. input:crude_derivative_petchem
  share_of_base: the fraction (0-1) the document states, or null
  base_kind:     one of {base_kinds}
  base_value_inr: the base amount in INR the document states, or null
  measurement:   one of {measurements}
  source_type:   one of {source_types}
  source_page:   the page number this appears on, as a string
  excerpt:       the sentence from the document that states it, COPIED
                 CHARACTER FOR CHARACTER. An excerpt you have paraphrased,
                 corrected, shortened or written yourself will be detected
                 and the whole proposal discarded.
  extraction_confidence: 0-1, your confidence in THIS extraction

If the document does not state a number, return share_of_base: null. Never
supply a figure the document does not contain.

Return JSON: {{"proposals": [ ... ]}}

DOCUMENT (page breaks marked):
{document}
"""


class JSONClient(Protocol):
    """The one method this module is allowed to call."""

    def generate(self, prompt: str) -> str: ...


class ExposureExtractor:
    def __init__(self, client: JSONClient, *, model_id: str,
                 extractor_version: str, max_document_chars: int = 60_000):
        self.client = client
        self.model_id = model_id
        self.extractor_version = extractor_version
        self.max_document_chars = max_document_chars
        self.dropped: list[DroppedRow] = []

    # -- prompt ------------------------------------------------------------
    def build_prompt(self, document: SourceDocument) -> str:
        body = "\n\n[PAGE BREAK]\n\n".join(
            f"[page {index + 1}]\n{page}" for index, page in enumerate(document.pages))
        return PROMPT_TEMPLATE.format(
            exposure_kinds="|".join(EXPOSURE_KINDS),
            base_kinds="|".join(BASE_KINDS),
            measurements="|".join(MEASUREMENTS),
            source_types="|".join(SOURCE_TYPES),
            document=body[:self.max_document_chars])

    # -- extraction --------------------------------------------------------
    def propose(self, document: SourceDocument, *, company_id: int,
                as_of_date: date) -> list[ExposureProposal]:
        raw = self.client.generate(self.build_prompt(document))
        rows = self._parse(raw)
        proposals: list[ExposureProposal] = []
        for row in rows:
            proposal = self._to_proposal(row, company_id=company_id,
                                         as_of_date=as_of_date, document=document)
            if proposal is not None:
                proposals.append(proposal)
        return proposals

    def _parse(self, raw: Any) -> Sequence[dict]:
        if isinstance(raw, (dict, list)):
            payload = raw
        else:
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                logger.warning("[ledger] extractor returned unparseable output")
                self.dropped.append(DroppedRow("UNPARSEABLE_OUTPUT", {}))
                return []
        if isinstance(payload, dict):
            payload = payload.get("proposals", [])
        return [row for row in payload if isinstance(row, dict)]

    def _to_proposal(self, row: dict, *, company_id: int, as_of_date: date,
                     document: SourceDocument) -> ExposureProposal | None:
        # Nothing below supplies a value. Each `drop` is a row the model
        # produced that cannot become a reviewable claim.
        def drop(reason: str):
            logger.info("[ledger] dropped extracted row (%s)", reason)
            self.dropped.append(DroppedRow(reason, dict(row)))
            return None

        if not str(row.get("excerpt") or "").strip():
            return drop("NO_EXCERPT")
        if not str(row.get("source_page") or "").strip():
            return drop("NO_SOURCE_PAGE")
        if row.get("share_of_base") is None:
            return drop("NO_SHARE_OF_BASE")
        if row.get("exposure_kind") not in EXPOSURE_KINDS:
            return drop("UNKNOWN_EXPOSURE_KIND")
        if row.get("base_kind") not in BASE_KINDS:
            return drop("UNKNOWN_BASE_KIND")

        try:
            share = float(row["share_of_base"])
            confidence = (None if row.get("extraction_confidence") is None
                          else float(row["extraction_confidence"]))
            base_value = (None if row.get("base_value_inr") is None
                          else float(row["base_value_inr"]))
        except (TypeError, ValueError):
            return drop("NON_NUMERIC_VALUE")

        measurement = row.get("measurement")
        if measurement not in MEASUREMENTS:
            return drop("UNKNOWN_MEASUREMENT")
        source_type = row.get("source_type")
        if source_type not in SOURCE_TYPES:
            return drop("UNKNOWN_SOURCE_TYPE")

        return ExposureProposal(
            company_id=company_id,
            exposure_kind=str(row["exposure_kind"]),
            exposure_tag=str(row.get("exposure_tag") or ""),
            share_of_base=share,
            base_kind=str(row["base_kind"]),
            base_value_inr=base_value,
            measurement=str(measurement),
            source_type=str(source_type),
            source_url=str(row.get("source_url") or document.url),
            source_page=str(row["source_page"]),
            excerpt=str(row["excerpt"]),
            extraction_confidence=confidence,
            model_id=self.model_id,
            created_by=f"llm:{self.model_id}",
            extractor_version=self.extractor_version,
            as_of_date=as_of_date)
