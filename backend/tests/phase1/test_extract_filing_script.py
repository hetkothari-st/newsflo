"""The operator entrypoint for Task 1.3.

`scripts/extract_filing.py` is what a human runs against a real annual
report: acquire -> store the artefact -> read the text -> (optionally)
propose -> verbatim gate -> `exposure_proposal`. The DoD's "5 real annual
reports" run is executed with this script and is DEFERRED to the repo owner
(DATA_GAPS.md §5), so the script must be real, runnable and safe by default.

SAFE BY DEFAULT means: with no `--llm`, and with no client injected, it
performs Stage A and B only and makes no model call at all.
"""
import json
from datetime import date

import pytest
from sqlalchemy import text

from tests.phase1.conftest import FIXTURE_NOW, make_company
from tests.phase1.pdf_fixture import build_pdf


@pytest.fixture()
def company(ledger_session, filing_fixture):
    return make_company(ledger_session, ticker="FIXCO.NS",
                        name=filing_fixture["company_name"],
                        isin=filing_fixture["isin"], market_cap=11111.0)


def _pdf(tmp_path, filing_fixture):
    path = tmp_path / "testco_fixture.pdf"
    path.write_bytes(build_pdf(filing_fixture["pages"]))
    return path


def test_without_a_client_the_script_stores_the_artefact_and_proposes_nothing(
        ledger_session, filing_fixture, company, tmp_path):
    from scripts.extract_filing import run

    result = run(ledger_session, path=_pdf(tmp_path, filing_fixture),
                 url=filing_fixture["source_url"], company_id=company.id,
                 as_of_date=date(2222, 2, 22), source_type="ANNUAL_REPORT",
                 retrieved_at=FIXTURE_NOW, artefacts_dir=tmp_path / "artefacts",
                 client=None)

    assert result.proposed == 0
    assert result.pages == len(filing_fixture["pages"])
    assert ledger_session.execute(
        text("SELECT count(*) FROM filing_artefact")).scalar() == 1
    assert ledger_session.execute(
        text("SELECT count(*) FROM exposure_proposal")).scalar() == 0


def test_with_an_injected_client_the_script_records_proposals_for_review(
        ledger_session, filing_fixture, company, tmp_path):
    from scripts.extract_filing import run

    honest = {k: v for k, v in filing_fixture["honest_proposal"].items()
              if not k.startswith("_")}

    class _Client:
        def generate(self, prompt: str) -> str:
            # Normalised, because pypdf wraps a PDF's text at the layout's
            # line breaks -- which is exactly why the verbatim check
            # normalises whitespace too.
            from app.ingest.filings.documents import normalize_whitespace

            assert "fixture input FOO" in normalize_whitespace(prompt), \
                "the document reached the model"
            return json.dumps({"proposals": [honest]})

    result = run(ledger_session, path=_pdf(tmp_path, filing_fixture),
                 url=filing_fixture["source_url"], company_id=company.id,
                 as_of_date=date(2222, 2, 22), source_type="ANNUAL_REPORT",
                 retrieved_at=FIXTURE_NOW, artefacts_dir=tmp_path / "artefacts",
                 client=_Client(), model_id="fixture-model-not-real",
                 extractor_version="fixture-v0")

    assert result.proposed == 1
    assert result.accepted == 1
    status = ledger_session.execute(
        text("SELECT status FROM exposure_proposal")).scalar()
    assert status == "PENDING_REVIEW"
    # Still nothing in the ledger: a human has not reviewed it.
    assert ledger_session.execute(
        text("SELECT count(*) FROM company_exposure")).scalar() == 0


def test_the_script_reports_and_persists_malformed_model_rows(
        ledger_session, filing_fixture, company, tmp_path):
    """FIX ROUND 1 / I3. One good row, one excerpt-less row, one fabricated
    row: the run reports all three buckets and every one of them is in the
    database."""
    from scripts.extract_filing import run

    honest = {k: v for k, v in filing_fixture["honest_proposal"].items()
              if not k.startswith("_")}
    fabricated = {k: v for k, v in filing_fixture["fabricated_proposal"].items()
                  if not k.startswith("_")}
    malformed = dict(honest, exposure_tag="input:fixture_malformed")
    malformed.pop("excerpt")

    class _Client:
        def generate(self, prompt: str) -> str:
            return json.dumps({"proposals": [honest, fabricated, malformed]})

    result = run(ledger_session, path=_pdf(tmp_path, filing_fixture),
                 url=filing_fixture["source_url"], company_id=company.id,
                 as_of_date=date(2222, 2, 22), source_type="ANNUAL_REPORT",
                 retrieved_at=FIXTURE_NOW, artefacts_dir=tmp_path / "artefacts",
                 client=_Client(), model_id="fixture-model-not-real",
                 extractor_version="fixture-v0")

    assert (result.accepted, result.rejected, result.malformed) == (1, 1, 1)
    counts = dict(ledger_session.execute(text(
        "SELECT status, count(*) FROM exposure_proposal GROUP BY status")).all())
    assert counts == {"PENDING_REVIEW": 1, "REJECTED_UNVERBATIM": 1,
                      "REJECTED_MALFORMED": 1}
    assert ledger_session.execute(
        text("SELECT count(*) FROM company_exposure")).scalar() == 0


def test_the_script_never_constructs_a_client_by_itself():
    """`--llm` is opt-in and explicit. Importing or running the script
    without it must not be able to reach a provider."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "scripts"
              / "extract_filing.py").read_text(encoding="utf-8")
    # The only construction site is inside the CLI's explicit --llm branch.
    assert source.count("ClaudeJSONClient(") <= 1
    assert "if args.llm" in source or "args.llm" in source
