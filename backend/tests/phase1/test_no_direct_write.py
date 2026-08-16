"""The ledger's single-writer guarantee.

The phase file's TESTS section, verbatim:
  - LLM extractor cannot write company_exposure (role/permission test)
  - exposure_proposal is the only path into company_exposure

SQLite substitution for the Postgres role (controller adaptation, same
pattern as Phase 0's `company_impact`): a BEFORE INSERT/UPDATE trigger that
demands a per-connection TEMP table which only `app.ledger.review` creates.
Proven at the DATABASE, not by inspection.
"""
import ast
import json
import uuid
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from tests.phase1.conftest import FIXTURE_NOW, make_company

BACKEND = Path(__file__).resolve().parents[2]
FILINGS = BACKEND / "app" / "ingest" / "filings"

_ROW = {
    "exposure_id": "fixture-direct-write", "company_id": 1, "exposure_kind": "INPUT_COST",
    "exposure_tag": "input:fixture_foo", "share_of_base": 0.1111, "base_kind": "COGS",
    "base_value_inr": 99999.0, "measurement": "FILED", "source_type": "ANNUAL_REPORT",
    "source_url": "https://fixture.invalid/ar", "source_page": "2",
    "as_of_date": "2222-02-22", "freshness_days": 400, "confidence": 0.1111,
    "created_by": "test:phase1", "reviewed_by": "human:fixture",
}
_INSERT = text(
    "INSERT INTO company_exposure (" + ", ".join(_ROW) + ") VALUES ("
    + ", ".join(f":{c}" for c in _ROW) + ")")


def test_a_plain_session_cannot_insert_into_company_exposure(ledger_session):
    with pytest.raises(DatabaseError):
        ledger_session.execute(_INSERT, _ROW)
        ledger_session.commit()
    ledger_session.rollback()
    assert ledger_session.execute(
        text("SELECT count(*) FROM company_exposure")).scalar() == 0


def test_the_review_session_grants_the_capability_and_takes_it_back(ledger_session):
    from app.ledger.review import review_session

    with review_session(ledger_session):
        ledger_session.execute(_INSERT, _ROW)
        ledger_session.commit()
    assert ledger_session.execute(
        text("SELECT count(*) FROM company_exposure")).scalar() == 1

    with pytest.raises(DatabaseError):
        ledger_session.execute(_INSERT, dict(_ROW, exposure_id="fixture-second"))
        ledger_session.commit()
    ledger_session.rollback()


def test_a_plain_session_cannot_rewrite_an_approved_claim(ledger_session):
    from app.ledger.review import review_session

    with review_session(ledger_session):
        ledger_session.execute(_INSERT, _ROW)
        ledger_session.commit()

    with pytest.raises(DatabaseError):
        ledger_session.execute(text(
            "UPDATE company_exposure SET share_of_base = 0.9999"))
        ledger_session.commit()
    ledger_session.rollback()
    assert float(ledger_session.execute(
        text("SELECT share_of_base FROM company_exposure")).scalar()) == 0.1111


def test_the_staleness_flag_is_maintainable_without_the_review_capability(ledger_session):
    """The ledger's CLAIM columns are review-only. `stale` is a DERIVED flag
    the nightly job maintains, so the guard is scoped to the claim columns
    rather than to the whole row."""
    from app.ledger.review import review_session

    with review_session(ledger_session):
        ledger_session.execute(_INSERT, _ROW)
        ledger_session.commit()

    ledger_session.execute(text("UPDATE company_exposure SET stale = 1"))
    ledger_session.commit()
    assert ledger_session.execute(
        text("SELECT stale FROM company_exposure")).scalar() == 1


def test_no_module_under_ingest_filings_writes_company_exposure():
    """The extractor is a PROPOSER. Structurally, not by convention."""
    offenders = []
    for path in FILINGS.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        body = "\n".join(line for line in source.splitlines()
                         if not line.lstrip().startswith("#"))
        if "INSERT INTO company_exposure" in body or "review_session" in body:
            offenders.append(path.name)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "app.ledger.review":
                offenders.append(f"{path.name}:imports app.ledger.review")
    assert offenders == []


def test_the_llm_extractor_run_leaves_the_ledger_empty(ledger_session, filing_fixture):
    """End to end with a stub client: extract, record, and the ledger is
    still empty because nobody reviewed anything."""
    from app.ingest.filings.documents import document_from_pages
    from app.ingest.filings.llm_extract import ExposureExtractor
    from app.ingest.filings.proposals import record_proposals

    company = make_company(ledger_session, ticker="FIXCO.NS",
                           name=filing_fixture["company_name"],
                           isin=filing_fixture["isin"])
    honest = {k: v for k, v in filing_fixture["honest_proposal"].items()
              if not k.startswith("_")}

    class _Client:
        def generate(self, prompt: str) -> str:
            return json.dumps({"proposals": [honest]})

    document = document_from_pages(filing_fixture["pages"],
                                   url=filing_fixture["source_url"],
                                   retrieved_at=FIXTURE_NOW, media_type="text/plain")
    extractor = ExposureExtractor(_Client(), model_id="fixture-model-not-real",
                                  extractor_version="fixture-v0")
    proposals = extractor.propose(document, company_id=company.id,
                                  as_of_date=date(2222, 2, 22))
    record_proposals(ledger_session, proposals, document)

    assert ledger_session.execute(
        text("SELECT count(*) FROM exposure_proposal")).scalar() == 1
    assert ledger_session.execute(
        text("SELECT count(*) FROM company_exposure")).scalar() == 0


def test_bulk_approve_refuses_llm_proposals(ledger_session, filing_fixture):
    """Bulk approve is for DETERMINISTIC extractors only (phase file Task
    1.4). An LLM proposal is read one at a time, by a human, or not at all."""
    from app.ingest.filings.documents import document_from_pages
    from app.ingest.filings.proposals import ExposureProposal, record_proposals
    from app.ledger.review import LedgerReviewError, bulk_approve, pending_queue

    company = make_company(ledger_session, ticker="FIXCO.NS",
                           name=filing_fixture["company_name"],
                           isin=filing_fixture["isin"])
    document = document_from_pages(filing_fixture["pages"],
                                   url=filing_fixture["source_url"],
                                   retrieved_at=FIXTURE_NOW, media_type="text/plain")
    honest = {k: v for k, v in filing_fixture["honest_proposal"].items()
              if not k.startswith("_")}
    record_proposals(ledger_session, [ExposureProposal(
        company_id=company.id, as_of_date=date(2222, 2, 22),
        created_by="llm:fixture-model-not-real", extractor_version="fixture-v0",
        **honest)], document)
    proposal_id = pending_queue(ledger_session)[0]["proposal_id"]

    with pytest.raises(LedgerReviewError):
        bulk_approve(ledger_session, [proposal_id], reviewed_by="human:fixture")
    assert ledger_session.execute(
        text("SELECT count(*) FROM company_exposure")).scalar() == 0


def test_bulk_approve_accepts_deterministic_proposals(ledger_session, filing_fixture):
    from app.ingest.filings.documents import document_from_pages
    from app.ingest.filings.proposals import ExposureProposal, record_proposals
    from app.ledger.review import bulk_approve, pending_queue

    company = make_company(ledger_session, ticker="FIXCO.NS",
                           name=filing_fixture["company_name"],
                           isin=filing_fixture["isin"])
    document = document_from_pages(filing_fixture["pages"],
                                   url=filing_fixture["source_url"],
                                   retrieved_at=FIXTURE_NOW, media_type="text/plain")
    honest = {k: v for k, v in filing_fixture["honest_proposal"].items()
              if not k.startswith("_")}
    honest["model_id"] = None
    record_proposals(ledger_session, [ExposureProposal(
        company_id=company.id, as_of_date=date(2222, 2, 22),
        created_by="ingest:segment_note_v0", extractor_version="fixture-v0",
        **honest)], document)
    proposal_id = pending_queue(ledger_session)[0]["proposal_id"]

    bulk_approve(ledger_session, [proposal_id], reviewed_by="human:fixture")
    assert ledger_session.execute(text(
        "SELECT reviewed_by FROM company_exposure")).scalar() == "human:fixture"


def test_no_fixture_data_can_reach_a_production_table(ledger_session):
    """Master context: 'A test asserting no fixture data reaches production
    tables must exist.' Every Phase 1 fixture lives under tests/fixtures/
    and no production module may import the fixture helpers."""
    production = [p for p in (BACKEND / "app").rglob("*.py")]
    production += [p for p in (BACKEND / "tools").rglob("*.py")]
    production += [p for p in (BACKEND / "scripts").rglob("*.py")]
    for path in production:
        source = path.read_text(encoding="utf-8")
        assert "tests.phase1" not in source, f"{path} imports the Phase 1 fixtures"
        assert "tests/fixtures/phase1" not in source, f"{path} reads a Phase 1 fixture"

    for table in ("company_exposure", "company_segment", "company_financials",
                  "pass_through_curve", "company_modifier"):
        assert ledger_session.execute(
            text(f"SELECT count(*) FROM {table}")).scalar() == 0


def test_every_numeric_fixture_object_is_marked(filing_fixture):
    """Fabrication guard: fixture numerals must be identifiable as fixture
    numerals, in the file itself."""
    def _walk(node):
        if isinstance(node, dict):
            if any(isinstance(v, (int, float)) and not isinstance(v, bool)
                   for v in node.values()):
                assert node.get("_fixture") is True, f"unmarked numerals in {node}"
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for value in node:
                _walk(value)

    _walk(filing_fixture)


def test_the_review_module_is_the_only_creator_of_the_capability_token():
    from app.ledger.review import LEDGER_REVIEW_SESSION_TABLE

    creators = []
    for root in ("app", "tools", "scripts"):
        for path in (BACKEND / root).rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if "CREATE TEMP TABLE" in source and LEDGER_REVIEW_SESSION_TABLE in source:
                creators.append(str(path.relative_to(BACKEND)))
    assert creators == [str(Path("app") / "ledger" / "review.py")]


def test_an_exposure_row_always_carries_the_proposal_it_came_from(
        ledger_session, filing_fixture):
    """'exposure_proposal is the only path into company_exposure' -- every
    row written by the approval path names its proposal."""
    from app.ingest.filings.documents import document_from_pages
    from app.ingest.filings.proposals import ExposureProposal, record_proposals
    from app.ledger.review import approve_proposal, pending_queue

    company = make_company(ledger_session, ticker="FIXCO.NS",
                           name=filing_fixture["company_name"],
                           isin=filing_fixture["isin"])
    document = document_from_pages(filing_fixture["pages"],
                                   url=filing_fixture["source_url"],
                                   retrieved_at=FIXTURE_NOW, media_type="text/plain")
    honest = {k: v for k, v in filing_fixture["honest_proposal"].items()
              if not k.startswith("_")}
    record_proposals(ledger_session, [ExposureProposal(
        company_id=company.id, as_of_date=date(2222, 2, 22),
        created_by="ingest:segment_note_v0", extractor_version="fixture-v0",
        **honest)], document)
    proposal_id = pending_queue(ledger_session)[0]["proposal_id"]
    approve_proposal(ledger_session, proposal_id, reviewed_by="human:fixture")

    linked = ledger_session.execute(text(
        "SELECT proposal_id FROM company_exposure")).scalar()
    assert linked == proposal_id
    assert uuid.UUID(str(linked))
