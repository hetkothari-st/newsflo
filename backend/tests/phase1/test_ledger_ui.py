"""TASK 1.4 -- the review UI.

Server-rendered, standalone, on its own port (controller adaptation: same
shape as tools/eval_ui.py). DoD: "Review UI functional; approval is the only
write path."
"""
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.phase1.conftest import FIXTURE_NOW, make_company

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture()
def seeded(ledger_engine, filing_fixture):
    """One PENDING_REVIEW LLM proposal and one deterministic proposal."""
    from sqlalchemy.orm import sessionmaker

    from app.ingest.filings.documents import document_from_pages
    from app.ingest.filings.proposals import ExposureProposal, record_proposals

    session = sessionmaker(bind=ledger_engine)()
    company = make_company(session, ticker="FIXCO.NS",
                           name=filing_fixture["company_name"],
                           isin=filing_fixture["isin"], market_cap=11111.0)
    document = document_from_pages(filing_fixture["pages"],
                                   url=filing_fixture["source_url"],
                                   retrieved_at=FIXTURE_NOW, media_type="text/plain")
    honest = {k: v for k, v in filing_fixture["honest_proposal"].items()
              if not k.startswith("_")}
    record_proposals(session, [
        ExposureProposal(company_id=company.id, as_of_date=date(2222, 2, 22),
                         created_by="llm:fixture-model-not-real",
                         extractor_version="fixture-v0", **honest),
        ExposureProposal(company_id=company.id, as_of_date=date(2222, 2, 22),
                         created_by="ingest:segment_note_v0",
                         extractor_version="fixture-v0",
                         **dict(honest, exposure_tag="input:fixture_det",
                                model_id=None)),
    ], document)
    session.commit()
    session.close()
    return ledger_engine


@pytest.fixture()
def client(seeded):
    from tools.ledger_ui import build_app

    return TestClient(build_app(seeded))


def _proposal_ids(engine, created_by_prefix: str) -> list[str]:
    with engine.connect() as connection:
        return [r[0] for r in connection.execute(text(
            "SELECT proposal_id FROM exposure_proposal WHERE created_by LIKE :p"),
            {"p": f"{created_by_prefix}%"}).all()]


def test_the_queue_page_shows_pending_proposals_with_their_excerpt(client, filing_fixture):
    response = client.get("/")
    assert response.status_code == 200
    assert "PENDING_REVIEW" in response.text or "pending" in response.text.lower()
    assert filing_fixture["honest_proposal"]["exposure_tag"] in response.text


def test_the_detail_page_shows_the_verbatim_excerpt_and_a_link_to_the_page(
        seeded, client, filing_fixture):
    proposal_id = _proposal_ids(seeded, "llm:")[0]
    response = client.get(f"/ledger/proposal?proposal_id={proposal_id}")
    assert response.status_code == 200
    assert filing_fixture["honest_proposal"]["excerpt"][:40] in response.text
    assert filing_fixture["source_url"] in response.text
    assert "page 2" in response.text.lower()


def test_approving_from_the_ui_writes_the_ledger_row(seeded, client):
    proposal_id = _proposal_ids(seeded, "llm:")[0]
    response = client.post("/ledger/approve", data={
        "proposal_id": proposal_id, "reviewed_by": "human:fixture-reviewer"},
        follow_redirects=False)
    assert response.status_code in (200, 303)

    with seeded.connect() as connection:
        row = connection.execute(text(
            "SELECT reviewed_by, created_by FROM company_exposure")).one()
    assert row[0] == "human:fixture-reviewer"
    assert row[1] == "llm:fixture-model-not-real"


def test_approving_without_a_reviewer_writes_nothing(seeded, client):
    proposal_id = _proposal_ids(seeded, "llm:")[0]
    response = client.post("/ledger/approve", data={
        "proposal_id": proposal_id, "reviewed_by": ""}, follow_redirects=False)
    assert response.status_code == 400
    with seeded.connect() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM company_exposure")).scalar() == 0


def test_rejecting_from_the_ui_requires_a_reason(seeded, client):
    proposal_id = _proposal_ids(seeded, "llm:")[0]
    bad = client.post("/ledger/reject", data={
        "proposal_id": proposal_id, "reviewed_by": "human:fixture", "reason": ""},
        follow_redirects=False)
    assert bad.status_code == 400

    good = client.post("/ledger/reject", data={
        "proposal_id": proposal_id, "reviewed_by": "human:fixture",
        "reason": "fixture rejection reason"}, follow_redirects=False)
    assert good.status_code in (200, 303)
    with seeded.connect() as connection:
        status = connection.execute(text(
            "SELECT status FROM exposure_proposal WHERE proposal_id = :p"),
            {"p": proposal_id}).scalar()
    assert status == "REJECTED"


def test_bulk_approve_refuses_an_llm_proposal_from_the_ui(seeded, client):
    proposal_id = _proposal_ids(seeded, "llm:")[0]
    response = client.post("/ledger/bulk-approve", data={
        "proposal_ids": proposal_id, "reviewed_by": "human:fixture"},
        follow_redirects=False)
    assert response.status_code == 400
    with seeded.connect() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM company_exposure")).scalar() == 0


def test_bulk_approve_accepts_a_deterministic_proposal_from_the_ui(seeded, client):
    proposal_id = _proposal_ids(seeded, "ingest:")[0]
    response = client.post("/ledger/bulk-approve", data={
        "proposal_ids": proposal_id, "reviewed_by": "human:fixture"},
        follow_redirects=False)
    assert response.status_code in (200, 303)
    with seeded.connect() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM company_exposure")).scalar() == 1


def test_the_quality_and_coverage_pages_render(client):
    assert client.get("/ledger/quality").status_code == 200
    assert client.get("/ledger/coverage").status_code == 200
    metrics = client.get("/ledger/metrics")
    assert metrics.status_code == 200
    assert "newsflo_ledger_exposure_rows" in metrics.text
    coverage_json = client.get("/ledger/coverage.json")
    assert coverage_json.status_code == 200
    assert isinstance(coverage_json.json(), list)


def test_an_empty_queue_says_so_rather_than_inventing_work(ledger_engine):
    from tools.ledger_ui import build_app

    client = TestClient(build_app(ledger_engine))
    response = client.get("/")
    assert response.status_code == 200
    assert "no proposals" in response.text.lower()


def test_the_ui_is_not_wired_into_the_production_app():
    """Internal tooling. It must never be reachable from the deployed
    service -- the same rule tools/eval_ui.py lives under."""
    for path in (BACKEND / "app").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "ledger_ui" not in source, f"{path} references the ledger UI"


def test_the_queue_is_ordered_by_market_cap_times_uncertainty(ledger_engine,
                                                              filing_fixture):
    from sqlalchemy.orm import sessionmaker

    from app.ingest.filings.documents import document_from_pages
    from app.ingest.filings.proposals import ExposureProposal, record_proposals
    from app.ledger.review import pending_queue

    session = sessionmaker(bind=ledger_engine)()
    big = make_company(session, ticker="FIXBIG.NS", name="Fixture Big Ltd",
                       isin="INFIXTUREB99", market_cap=99999.0)
    small = make_company(session, ticker="FIXSML.NS", name="Fixture Small Ltd",
                         isin="INFIXTURES99", market_cap=11.0)
    document = document_from_pages(filing_fixture["pages"],
                                   url=filing_fixture["source_url"],
                                   retrieved_at=FIXTURE_NOW, media_type="text/plain")
    honest = {k: v for k, v in filing_fixture["honest_proposal"].items()
              if not k.startswith("_")}
    record_proposals(session, [
        ExposureProposal(company_id=small.id, as_of_date=date(2222, 2, 22),
                         created_by="llm:fixture", extractor_version="v0",
                         **dict(honest, extraction_confidence=0.1111)),
        ExposureProposal(company_id=big.id, as_of_date=date(2222, 2, 22),
                         created_by="llm:fixture", extractor_version="v0",
                         **dict(honest, exposure_tag="input:fixture_big",
                                extraction_confidence=0.5)),
    ], document)
    session.commit()

    queue = pending_queue(session)
    assert [row["company_id"] for row in queue] == [big.id, small.id]
    session.close()
