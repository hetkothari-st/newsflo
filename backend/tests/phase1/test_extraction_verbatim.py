"""TASK 1.3 -- the filing extraction pipeline and its anti-hallucination gate.

The phase file's TESTS section, verbatim:
  - proposal whose excerpt does not appear in source document is discarded
  - proposal without source_page is discarded
  - approved proposal writes company_exposure with reviewed_by populated

DoD: "Verbatim containment check rejects fabricated excerpts (proven with an
adversarial fixture)" -- `fabricated_proposal` in
tests/fixtures/phase1/testco_filing.json is a plausible annual-report
sentence that appears NOWHERE in the document.

Zero real API calls: the Stage C extractor takes an INJECTED client and
every test here hands it a stub.
"""
import json
from datetime import date

import pytest
from sqlalchemy import text

from tests.phase1.conftest import FIXTURE_NOW, FIXTURE_TODAY, make_company
from tests.phase1.pdf_fixture import build_pdf


def _document(filing: dict):
    from app.ingest.filings.documents import document_from_pages

    return document_from_pages(
        filing["pages"], url=filing["source_url"], retrieved_at=FIXTURE_NOW,
        media_type="text/plain")


def _proposal(filing: dict, key: str, company_id: int, **overrides):
    from app.ingest.filings.proposals import ExposureProposal

    raw = {k: v for k, v in filing[key].items() if not k.startswith("_")}
    raw.update(overrides)
    return ExposureProposal(company_id=company_id, as_of_date=date(2222, 2, 22),
                            created_by="llm:fixture-model-not-real",
                            extractor_version="fixture-v0", **raw)


@pytest.fixture()
def company(ledger_session, filing_fixture):
    return make_company(ledger_session, ticker="FIXCO.NS",
                        name=filing_fixture["company_name"],
                        isin=filing_fixture["isin"], market_cap=11111.0)


# --- the containment check itself -----------------------------------------

def test_whitespace_differences_do_not_break_containment(filing_fixture):
    from app.ingest.filings.verbatim import contains_verbatim

    document = _document(filing_fixture)
    excerpt = filing_fixture["honest_proposal"]["excerpt"]
    assert contains_verbatim(document.text, excerpt)
    assert contains_verbatim(document.text, f"  {excerpt}\n\n   ".replace(" ", "  "))


def test_a_fabricated_excerpt_is_not_contained(filing_fixture):
    from app.ingest.filings.verbatim import contains_verbatim

    document = _document(filing_fixture)
    assert not contains_verbatim(
        document.text, filing_fixture["fabricated_proposal"]["excerpt"])


def test_a_non_page_label_is_not_read_as_a_page_number(filing_fixture):
    """FIX ROUND 1 / M4. 'Note 11' is a note reference, not page 11. Only a
    label that actually looks like a page is turned into a page index;
    anything else takes the UNVERIFIED path the docstring promises."""
    from app.ingest.filings.verbatim import check_excerpt, page_number_from

    assert page_number_from("2") == 2
    assert page_number_from(" p. 2 ") == 2
    assert page_number_from("Page 2") == 2
    assert page_number_from("Note 11") is None
    assert page_number_from("F-12") is None
    assert page_number_from("11.2") is None

    document = _document(filing_fixture)
    result = check_excerpt(document,
                           excerpt=filing_fixture["honest_proposal"]["excerpt"],
                           source_page="Note 11")
    assert result.ok is True
    assert result.page_verified is False
    assert result.page_number is None


def test_a_trivially_short_excerpt_is_refused(filing_fixture):
    """'the' appears in every document. An excerpt must actually locate a
    claim, so there is a minimum length."""
    from app.ingest.filings.verbatim import MIN_EXCERPT_CHARS, check_excerpt

    document = _document(filing_fixture)
    result = check_excerpt(document, excerpt="the", source_page="2")
    assert result.ok is False
    assert result.reason == "EXCERPT_TOO_SHORT"
    assert MIN_EXCERPT_CHARS >= 16


# --- the gate, over proposals ---------------------------------------------

def test_proposal_whose_excerpt_is_not_in_the_document_is_discarded(
        ledger_session, filing_fixture, company):
    from app.ingest.filings.proposals import record_proposals

    document = _document(filing_fixture)
    outcome = record_proposals(
        ledger_session,
        [_proposal(filing_fixture, "fabricated_proposal", company.id)], document)

    assert outcome.accepted == 0
    assert outcome.rejected == 1
    row = ledger_session.execute(text(
        "SELECT status, reject_reason FROM exposure_proposal")).one()
    assert row[0] == "REJECTED_UNVERBATIM"
    assert row[1] == "EXCERPT_NOT_IN_DOCUMENT"


def test_a_discarded_proposal_is_recorded_not_silently_dropped(
        ledger_session, filing_fixture, company):
    """Master context invariant 12: rejected candidates are retained with a
    reason and are visible in the review console."""
    from app.ingest.filings.proposals import record_proposals

    document = _document(filing_fixture)
    record_proposals(
        ledger_session,
        [_proposal(filing_fixture, "fabricated_proposal", company.id)], document)

    stored = ledger_session.execute(text(
        "SELECT excerpt, source_url, model_id FROM exposure_proposal")).one()
    assert stored[0] == filing_fixture["fabricated_proposal"]["excerpt"]
    assert stored[1] == filing_fixture["source_url"]
    assert stored[2] == "fixture-model-not-real"


def test_proposal_without_source_page_is_discarded(
        ledger_session, filing_fixture, company):
    from app.ingest.filings.proposals import record_proposals

    document = _document(filing_fixture)
    outcome = record_proposals(
        ledger_session,
        [_proposal(filing_fixture, "pageless_proposal", company.id)], document)

    assert outcome.accepted == 0
    assert ledger_session.execute(text(
        "SELECT reject_reason FROM exposure_proposal")).scalar() == "NO_SOURCE_PAGE"


def test_proposal_citing_the_wrong_page_is_discarded(
        ledger_session, filing_fixture, company):
    from app.ingest.filings.proposals import record_proposals

    document = _document(filing_fixture)
    outcome = record_proposals(
        ledger_session,
        [_proposal(filing_fixture, "wrong_page_proposal", company.id)], document)

    assert outcome.accepted == 0
    assert ledger_session.execute(text(
        "SELECT reject_reason FROM exposure_proposal")).scalar() == "EXCERPT_NOT_ON_CITED_PAGE"


def test_an_honest_proposal_lands_as_pending_review(
        ledger_session, filing_fixture, company):
    from app.ingest.filings.proposals import record_proposals

    document = _document(filing_fixture)
    outcome = record_proposals(
        ledger_session, [_proposal(filing_fixture, "honest_proposal", company.id)],
        document)

    assert (outcome.accepted, outcome.rejected) == (1, 0)
    status, sha = ledger_session.execute(text(
        "SELECT status, document_sha256 FROM exposure_proposal")).one()
    assert status == "PENDING_REVIEW"
    assert sha == document.sha256
    # Stage D: nothing entered the ledger.
    assert ledger_session.execute(
        text("SELECT count(*) FROM company_exposure")).scalar() == 0


# --- approval is the only write path --------------------------------------

def test_approved_proposal_writes_company_exposure_with_reviewed_by(
        ledger_session, filing_fixture, company):
    from app.ingest.filings.proposals import record_proposals
    from app.ledger.review import approve_proposal, pending_queue

    document = _document(filing_fixture)
    record_proposals(ledger_session,
                     [_proposal(filing_fixture, "honest_proposal", company.id)],
                     document)
    proposal_id = pending_queue(ledger_session)[0]["proposal_id"]

    exposure_id = approve_proposal(ledger_session, proposal_id,
                                   reviewed_by="human:fixture-reviewer")

    row = ledger_session.execute(text(
        "SELECT reviewed_by, created_by, share_of_base, source_page, "
        "freshness_days, proposal_id FROM company_exposure "
        "WHERE exposure_id = :id"), {"id": exposure_id}).one()
    assert row[0] == "human:fixture-reviewer"
    # created_by records the MODEL that proposed it (phase file Task 1.4).
    assert row[1] == "llm:fixture-model-not-real"
    assert float(row[2]) == pytest.approx(0.1111)
    assert row[3] == "2"
    assert int(row[4]) == 400          # INPUT_COST default from config
    assert row[5] == proposal_id
    assert ledger_session.execute(text(
        "SELECT status FROM exposure_proposal")).scalar() == "APPROVED"


def test_edit_then_approve_records_the_edit(ledger_session, filing_fixture, company):
    from app.ingest.filings.proposals import record_proposals
    from app.ledger.review import approve_proposal, pending_queue

    document = _document(filing_fixture)
    record_proposals(ledger_session,
                     [_proposal(filing_fixture, "honest_proposal", company.id)],
                     document)
    proposal_id = pending_queue(ledger_session)[0]["proposal_id"]

    approve_proposal(ledger_session, proposal_id, reviewed_by="human:fixture-reviewer",
                     edits={"share_of_base": 0.2222})

    share = ledger_session.execute(
        text("SELECT share_of_base FROM company_exposure")).scalar()
    assert float(share) == pytest.approx(0.2222)
    assert ledger_session.execute(
        text("SELECT edited FROM exposure_proposal")).scalar() == 1


def test_a_rejected_proposal_cannot_be_approved(ledger_session, filing_fixture, company):
    from app.ingest.filings.proposals import record_proposals
    from app.ledger.review import LedgerReviewError, approve_proposal

    document = _document(filing_fixture)
    record_proposals(ledger_session,
                     [_proposal(filing_fixture, "fabricated_proposal", company.id)],
                     document)
    proposal_id = ledger_session.execute(
        text("SELECT proposal_id FROM exposure_proposal")).scalar()

    with pytest.raises(LedgerReviewError):
        approve_proposal(ledger_session, proposal_id, reviewed_by="human:fixture")
    assert ledger_session.execute(
        text("SELECT count(*) FROM company_exposure")).scalar() == 0


def test_approval_without_a_reviewer_is_refused(ledger_session, filing_fixture, company):
    from app.ingest.filings.proposals import record_proposals
    from app.ledger.review import LedgerReviewError, approve_proposal, pending_queue

    document = _document(filing_fixture)
    record_proposals(ledger_session,
                     [_proposal(filing_fixture, "honest_proposal", company.id)],
                     document)
    proposal_id = pending_queue(ledger_session)[0]["proposal_id"]
    with pytest.raises(LedgerReviewError):
        approve_proposal(ledger_session, proposal_id, reviewed_by="  ")


def test_approval_of_a_proposal_without_a_base_value_is_refused(
        ledger_session, filing_fixture, company):
    """`base_value_inr` is NOT NULL in the schema and must never be
    defaulted to a plausible number."""
    from app.ingest.filings.proposals import record_proposals
    from app.ledger.review import LedgerReviewError, approve_proposal, pending_queue

    document = _document(filing_fixture)
    record_proposals(
        ledger_session,
        [_proposal(filing_fixture, "honest_proposal", company.id, base_value_inr=None)],
        document)
    proposal_id = pending_queue(ledger_session)[0]["proposal_id"]
    with pytest.raises(LedgerReviewError):
        approve_proposal(ledger_session, proposal_id, reviewed_by="human:fixture")


def test_rejection_requires_a_reason(ledger_session, filing_fixture, company):
    from app.ingest.filings.proposals import record_proposals
    from app.ledger.review import LedgerReviewError, pending_queue, reject_proposal

    document = _document(filing_fixture)
    record_proposals(ledger_session,
                     [_proposal(filing_fixture, "honest_proposal", company.id)],
                     document)
    proposal_id = pending_queue(ledger_session)[0]["proposal_id"]
    with pytest.raises(LedgerReviewError):
        reject_proposal(ledger_session, proposal_id, reviewed_by="human:fixture",
                        reason="")
    reject_proposal(ledger_session, proposal_id, reviewed_by="human:fixture",
                    reason="fixture rejection reason")
    assert ledger_session.execute(
        text("SELECT status FROM exposure_proposal")).scalar() == "REJECTED"


# --- Stage C: the LLM extractor -------------------------------------------

class _StubClient:
    """The injected LLM seam. No network exists in this object."""

    def __init__(self, payload):
        self.payload = payload
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps(self.payload)


def test_the_llm_extractor_returns_proposals_never_writes(
        ledger_session, filing_fixture, company):
    from app.ingest.filings.llm_extract import ExposureExtractor

    honest = {k: v for k, v in filing_fixture["honest_proposal"].items()
              if not k.startswith("_")}
    client = _StubClient({"proposals": [honest]})
    extractor = ExposureExtractor(client, model_id="fixture-model-not-real",
                                  extractor_version="fixture-v0")
    document = _document(filing_fixture)

    proposals = extractor.propose(document, company_id=company.id,
                                  as_of_date=date(2222, 2, 22))

    assert len(proposals) == 1
    assert proposals[0].created_by == "llm:fixture-model-not-real"
    assert client.prompts, "the extractor never called the injected client"
    # It returned data. It wrote nothing.
    assert ledger_session.execute(
        text("SELECT count(*) FROM exposure_proposal")).scalar() == 0
    assert ledger_session.execute(
        text("SELECT count(*) FROM company_exposure")).scalar() == 0


def test_the_extractor_drops_a_model_row_that_omits_an_excerpt(
        ledger_session, filing_fixture, company):
    from app.ingest.filings.llm_extract import ExposureExtractor

    honest = {k: v for k, v in filing_fixture["honest_proposal"].items()
              if not k.startswith("_")}
    honest.pop("excerpt")
    extractor = ExposureExtractor(_StubClient({"proposals": [honest]}),
                                  model_id="fixture-model-not-real",
                                  extractor_version="fixture-v0")
    proposals = extractor.propose(_document(filing_fixture), company_id=company.id,
                                  as_of_date=date(2222, 2, 22))
    assert proposals == []


def test_a_malformed_model_row_is_persisted_with_its_reason(
        ledger_session, filing_fixture, company):
    """FIX ROUND 1 / I3. A row the extractor drops BEFORE the verbatim gate
    (no excerpt, no page, no share) used to vanish into memory, so a prompt
    that regressed into excerpt-less output showed an UNCHANGED approve rate.
    Drops are now retained as REJECTED_MALFORMED, with the raw model payload,
    and they count."""
    from app.ingest.filings.llm_extract import ExposureExtractor
    from app.ingest.filings.proposals import record_malformed

    honest = {k: v for k, v in filing_fixture["honest_proposal"].items()
              if not k.startswith("_")}
    honest.pop("excerpt")
    extractor = ExposureExtractor(_StubClient({"proposals": [honest]}),
                                  model_id="fixture-model-not-real",
                                  extractor_version="fixture-v0")
    document = _document(filing_fixture)
    assert extractor.propose(document, company_id=company.id,
                             as_of_date=date(2222, 2, 22)) == []

    written = record_malformed(ledger_session, extractor.dropped, document,
                               company_id=company.id,
                               created_by="llm:fixture-model-not-real",
                               model_id="fixture-model-not-real",
                               extractor_version="fixture-v0")
    assert written == 1

    row = ledger_session.execute(text(
        "SELECT status, reject_reason, model_id, raw_payload, exposure_tag "
        "FROM exposure_proposal")).one()
    assert row[0] == "REJECTED_MALFORMED"
    assert row[1] == "NO_EXCERPT"
    assert row[2] == "fixture-model-not-real"
    assert "input:fixture_foo" in row[3]        # the raw model row is kept
    assert row[4] == "input:fixture_foo"        # whatever fields existed survive
    assert ledger_session.execute(
        text("SELECT count(*) FROM company_exposure")).scalar() == 0


def test_a_malformed_row_can_never_be_approved(ledger_session, filing_fixture,
                                               company):
    from app.ingest.filings.proposals import DroppedRow, record_malformed
    from app.ledger.review import LedgerReviewError, approve_proposal, pending_queue

    record_malformed(ledger_session,
                     [DroppedRow("NO_SHARE_OF_BASE", {"exposure_tag": "input:x"})],
                     _document(filing_fixture), company_id=company.id,
                     created_by="llm:fixture-model-not-real",
                     model_id="fixture-model-not-real",
                     extractor_version="fixture-v0")
    assert pending_queue(ledger_session) == []
    proposal_id = ledger_session.execute(
        text("SELECT proposal_id FROM exposure_proposal")).scalar()
    with pytest.raises(LedgerReviewError):
        approve_proposal(ledger_session, proposal_id, reviewed_by="human:fixture")


def test_the_extractor_never_invents_a_share_of_base(
        ledger_session, filing_fixture, company):
    """DO NOT: 'do not default a missing share_of_base to a plausible
    number. Missing is missing.'"""
    from app.ingest.filings.llm_extract import ExposureExtractor

    honest = {k: v for k, v in filing_fixture["honest_proposal"].items()
              if not k.startswith("_")}
    honest["share_of_base"] = None
    extractor = ExposureExtractor(_StubClient({"proposals": [honest]}),
                                  model_id="fixture-model-not-real",
                                  extractor_version="fixture-v0")
    assert extractor.propose(_document(filing_fixture), company_id=company.id,
                             as_of_date=date(2222, 2, 22)) == []


# --- Stage A/B: documents and artefacts -----------------------------------

def test_a_pdf_round_trips_through_the_pypdf_adapter(filing_fixture):
    from app.ingest.filings.documents import document_from_pdf

    data = build_pdf(filing_fixture["pages"])
    document = document_from_pdf(data, url=filing_fixture["source_url"],
                                 retrieved_at=FIXTURE_NOW)
    assert len(document.pages) == len(filing_fixture["pages"])
    assert "fixture input FOO" in document.text
    assert document.sha256


def test_the_gate_survives_a_pdf_round_trip_and_still_catches_a_fabrication(
        filing_fixture):
    """The realistic case. pypdf returns text wrapped at the PDF's line
    breaks, so an honest excerpt spans a newline that is not in the model's
    output -- which is exactly why the check normalises whitespace, and
    nothing else. A fabricated excerpt is still caught."""
    from app.ingest.filings.documents import document_from_pdf
    from app.ingest.filings.verbatim import check_excerpt

    document = document_from_pdf(build_pdf(filing_fixture["pages"]),
                                 url=filing_fixture["source_url"],
                                 retrieved_at=FIXTURE_NOW)
    honest = check_excerpt(document,
                           excerpt=filing_fixture["honest_proposal"]["excerpt"],
                           source_page="2")
    assert honest.ok is True
    assert honest.page_verified is True

    fabricated = check_excerpt(
        document, excerpt=filing_fixture["fabricated_proposal"]["excerpt"],
        source_page="2")
    assert fabricated.ok is False
    assert fabricated.reason == "EXCERPT_NOT_IN_DOCUMENT"


def test_an_artefact_is_stored_with_its_url_and_retrieval_time(
        ledger_session, filing_fixture, company, tmp_path):
    from app.ingest.filings.acquire import store_artefact

    data = build_pdf(filing_fixture["pages"])
    artefact = store_artefact(
        ledger_session, company_id=company.id, url=filing_fixture["source_url"],
        content=data, media_type="application/pdf", source_type="ANNUAL_REPORT",
        retrieved_at=FIXTURE_NOW, artefacts_dir=tmp_path)

    stored = ledger_session.execute(text(
        "SELECT source_url, retrieved_at, storage_path, content_sha256 "
        "FROM filing_artefact")).one()
    assert stored[0] == filing_fixture["source_url"]
    assert stored[2] == artefact.storage_path
    # "Never discard the source document."
    assert (tmp_path / artefact.storage_path).read_bytes() == data


def test_storing_the_same_artefact_twice_is_idempotent(
        ledger_session, filing_fixture, company, tmp_path):
    from app.ingest.filings.acquire import store_artefact

    data = build_pdf(filing_fixture["pages"])
    for _ in range(2):
        store_artefact(ledger_session, company_id=company.id,
                       url=filing_fixture["source_url"], content=data,
                       media_type="application/pdf", source_type="ANNUAL_REPORT",
                       retrieved_at=FIXTURE_NOW, artefacts_dir=tmp_path)
    assert ledger_session.execute(
        text("SELECT count(*) FROM filing_artefact")).scalar() == 1


def test_acquisition_makes_no_network_call_without_an_injected_fetcher():
    from app.ingest.filings.acquire import AcquisitionError, fetch_artefact

    with pytest.raises(AcquisitionError):
        fetch_artefact("https://fixture.invalid/testco/annual-report-fixture.pdf",
                       fetcher=None)


def test_the_xbrl_parser_reads_facts_from_an_instance_document():
    from app.ingest.filings.xbrl import parse_xbrl_facts

    instance = """<?xml version="1.0"?>
<xbrl xmlns:in-gaap="http://fixture.invalid/in-gaap">
  <in-gaap:RevenueFromOperations contextRef="FY2222" unitRef="INR" decimals="0">99999</in-gaap:RevenueFromOperations>
  <in-gaap:CostOfMaterialsConsumed contextRef="FY2222" unitRef="INR" decimals="0">11111</in-gaap:CostOfMaterialsConsumed>
</xbrl>"""
    facts = parse_xbrl_facts(instance)
    by_concept = {f.concept: f for f in facts}
    assert by_concept["RevenueFromOperations"].value == 99999.0
    assert by_concept["CostOfMaterialsConsumed"].context == "FY2222"


def test_segment_and_financial_rows_require_a_source_url(ledger_session, company):
    from app.ingest.filings.deterministic import LoaderError, load_segments

    with pytest.raises(LoaderError):
        load_segments(ledger_session, [{
            "company_id": company.id, "segment_name": "Fixture Segment",
            "fiscal_year": 2222, "as_of_date": FIXTURE_TODAY, "source_url": ""}])
