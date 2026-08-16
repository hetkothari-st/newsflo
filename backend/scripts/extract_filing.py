"""TASK 1.3 -- the operator entrypoint: one filing, end to end.

    # Stage A + B only. No model is contacted.
    python scripts/extract_filing.py --file ~/ar/reliance_fy25.pdf \
        --url https://www.example-exchange.in/… --isin INE002A01018 \
        --as-of 2025-03-31

    # Stage C as well. Explicit, opt-in, and it COSTS MONEY.
    python scripts/extract_filing.py … --llm --model claude-…

WHAT IT DOES
  A. stores the raw document under `artefacts/`, with its URL and retrieval
     time, and records the `filing_artefact` row ("never discard the source
     document");
  B. extracts the text (pypdf for PDFs) and reports what it got;
  C. ONLY with an explicit client: asks the model for exposure proposals;
  D. runs every proposal through the verbatim containment gate and writes
     the survivors as PENDING_REVIEW, the rest as REJECTED_UNVERBATIM with a
     reason.

It never writes `company_exposure`. Approving is a human act in
`tools/ledger_ui.py`, and the database refuses this process the privilege.

SAFE BY DEFAULT. `run()` takes an INJECTED client and does nothing model-
shaped when it is None. The CLI constructs a real client in exactly one
place, inside the `--llm` branch, so no import, no test and no accidental
invocation can reach a provider.

This is the script the DoD's "runs end to end on 5 real annual reports"
belongs to. That run is DEFERRED to the repo owner (DATA_GAPS.md §5): this
repo contains no real annual report, and downloading five of them is the
owner's act, not the agent's.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import sqlalchemy as sa  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.ingest.filings.acquire import store_artefact  # noqa: E402
from app.ingest.filings.documents import document_from_bytes  # noqa: E402
from app.ingest.filings.llm_extract import ExposureExtractor  # noqa: E402
from app.ingest.filings.proposals import record_proposals  # noqa: E402

DEFAULT_MODEL_ID = "unspecified-model"


@dataclass(frozen=True)
class ExtractionRun:
    artefact_id: str
    pages: int
    characters: int
    proposed: int
    accepted: int
    rejected: int


def _media_type(path: Path) -> str:
    return ("application/pdf" if path.suffix.lower() == ".pdf"
            else "text/plain")


def run(session, *, path: Path | str, url: str, company_id: int,
        as_of_date: date, source_type: str, retrieved_at: datetime,
        artefacts_dir: Path | str, client=None,
        model_id: str = DEFAULT_MODEL_ID,
        extractor_version: str = "ar_extractor_v0",
        fiscal_period: str | None = None) -> ExtractionRun:
    path = Path(path)
    content = path.read_bytes()

    artefact = store_artefact(
        session, company_id=company_id, url=url, content=content,
        media_type=_media_type(path), source_type=source_type,
        retrieved_at=retrieved_at, artefacts_dir=artefacts_dir,
        fiscal_period=fiscal_period)

    document = document_from_bytes(content, url=url, retrieved_at=retrieved_at,
                                   media_type=_media_type(path))

    if client is None:
        # Stage C not requested. Nothing is proposed -- and nothing is
        # guessed to make the run look productive.
        return ExtractionRun(artefact.artefact_id, len(document.pages),
                             len(document.text), 0, 0, 0)

    extractor = ExposureExtractor(client, model_id=model_id,
                                  extractor_version=extractor_version)
    proposals = extractor.propose(document, company_id=company_id,
                                  as_of_date=as_of_date)
    outcome = record_proposals(session, proposals, document)
    return ExtractionRun(artefact.artefact_id, len(document.pages),
                         len(document.text), len(proposals), outcome.accepted,
                         outcome.rejected)


class _ClaudeAdapter:
    """Bridges this repo's `ClaudeJSONClient` (schema-shaped, keyword-only)
    to the one method `ExposureExtractor` is allowed to call.

    Kept HERE rather than in `app/ingest/filings/`, so the extraction package
    stays provider-agnostic and cannot import a provider by accident."""

    _SCHEMA = {
        "type": "object",
        "properties": {
            "proposals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "exposure_kind": {"type": "string"},
                        "exposure_tag": {"type": "string"},
                        "share_of_base": {"type": ["number", "null"]},
                        "base_kind": {"type": "string"},
                        "base_value_inr": {"type": ["number", "null"]},
                        "measurement": {"type": "string"},
                        "source_type": {"type": "string"},
                        "source_page": {"type": "string"},
                        "excerpt": {"type": "string"},
                        "extraction_confidence": {"type": "number"},
                    },
                    "required": ["exposure_kind", "exposure_tag", "base_kind",
                                 "source_page", "excerpt"],
                },
            },
        },
        "required": ["proposals"],
    }

    def __init__(self, client, *, model: str):
        self._client = client
        self._model = model

    def generate(self, prompt: str) -> str:
        import json

        result = self._client.generate(
            model=self._model, schema=self._SCHEMA,
            static_prefix="You extract exposures from regulatory filings.",
            dynamic_suffix=prompt, stage="ledger_exposure_extraction")
        return json.dumps(result)


def _default_db_url() -> str:
    return os.environ.get("DATABASE_URL", "sqlite:///./newsflo.db")


def _resolve_company(session, *, isin: str | None, company_id: int | None,
                     as_of: date) -> int:
    from app.entities.resolver import RESOLVED, resolve_entity

    if company_id is not None:
        return company_id
    resolution = resolve_entity(session, isin=isin, as_of=as_of)
    if resolution.status != RESOLVED:
        raise SystemExit(
            f"entity resolution returned {resolution.status} for {isin!r} "
            f"({resolution.detail}). Nothing was extracted -- a filing is "
            f"never attached to a company we are not sure of.")
    return int(resolution.company_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract exposure proposals from ONE filing.")
    parser.add_argument("--file", required=True, help="local path to the filing")
    parser.add_argument("--url", required=True,
                        help="the URL the document came from (stored as provenance)")
    parser.add_argument("--isin", default=None)
    parser.add_argument("--company-id", type=int, default=None)
    parser.add_argument("--as-of", required=True,
                        help="ISO date the disclosure describes (e.g. the "
                             "financial year end)")
    parser.add_argument("--source-type", default="ANNUAL_REPORT")
    parser.add_argument("--fiscal-period", default=None)
    parser.add_argument("--artefacts-dir", default=str(BACKEND_DIR / "artefacts"))
    parser.add_argument("--db", default=None)
    parser.add_argument("--llm", action="store_true",
                        help="run Stage C. This makes a PAID model call. Off "
                             "by default.")
    parser.add_argument("--model", default=None,
                        help="model id for --llm (required with it)")
    parser.add_argument("--extractor-version", default="ar_extractor_v0")
    args = parser.parse_args(argv)

    if args.isin is None and args.company_id is None:
        parser.error("pass --isin or --company-id")

    as_of_date = date.fromisoformat(args.as_of)
    engine = sa.create_engine(args.db or _default_db_url())
    session = sessionmaker(bind=engine)()

    client = None
    model_id = DEFAULT_MODEL_ID
    if args.llm:
        if not args.model:
            parser.error("--llm requires --model")
        from app.analysis.impact_graph.claude_json import ClaudeJSONClient
        from app.config import settings

        if not settings.claude_api_key:
            parser.error("--llm requested but no Claude API key is configured")
        print(f"[extract] Stage C ENABLED: this will call {args.model} and cost "
              f"money.")
        client = _ClaudeAdapter(ClaudeJSONClient(settings.claude_api_key),
                                model=args.model)
        model_id = args.model

    try:
        company_id = _resolve_company(session, isin=args.isin,
                                      company_id=args.company_id, as_of=as_of_date)
        result = run(session, path=args.file, url=args.url, company_id=company_id,
                     as_of_date=as_of_date, source_type=args.source_type,
                     retrieved_at=datetime.now(timezone.utc),
                     artefacts_dir=args.artefacts_dir, client=client,
                     model_id=model_id, extractor_version=args.extractor_version,
                     fiscal_period=args.fiscal_period)
    finally:
        session.close()
        engine.dispose()

    print(f"[extract] artefact {result.artefact_id}: {result.pages} page(s), "
          f"{result.characters} chars")
    print(f"[extract] {result.proposed} proposal(s): {result.accepted} pending "
          f"review, {result.rejected} discarded by the verbatim gate")
    if not args.llm:
        print("[extract] Stage C was not run (no --llm). Nothing was proposed.")
    print("[extract] nothing entered company_exposure -- review at "
          "`python tools/ledger_ui.py` (http://127.0.0.1:8601/)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
