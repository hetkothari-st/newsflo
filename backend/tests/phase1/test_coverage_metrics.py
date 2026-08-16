"""TASK 1.5 -- coverage and metrics.

DoD: "Coverage and staleness views live with metrics exported."

Adaptation (recorded in the report): this repo has no `prometheus_client`,
so metrics are exported in Prometheus TEXT FORMAT by a hand-rolled function
and served by the ledger UI -- exactly the substitution Phase 0 made for the
firewall's deletion-rate metric.
"""
from datetime import date, timedelta

from sqlalchemy import text

from tests.phase1.conftest import make_company

AS_OF = date(2226, 2, 22)


def _exposure(session, company_id, *, as_of_date, exposure_tag, exposure_id):
    from app.ledger.review import review_session

    row = {
        "exposure_id": exposure_id, "company_id": company_id,
        "exposure_kind": "INPUT_COST", "exposure_tag": exposure_tag,
        "share_of_base": 0.1111, "base_kind": "COGS", "base_value_inr": 99999.0,
        "measurement": "FILED", "source_type": "ANNUAL_REPORT",
        "source_url": "https://fixture.invalid/ar", "source_page": "2",
        "as_of_date": as_of_date.isoformat(), "freshness_days": 400,
        "confidence": 0.1111, "created_by": "test:phase1",
        "reviewed_by": "human:fixture",
    }
    with review_session(session):
        session.execute(text(
            "INSERT INTO company_exposure (" + ", ".join(row) + ") VALUES ("
            + ", ".join(f":{c}" for c in row) + ")"), row)
        session.commit()


def test_coverage_of_an_empty_ledger_is_empty_not_zero_percent(ledger_session):
    """An empty ledger has NO coverage rows. Reporting '0% of every sector'
    would be a claim about sectors we have never looked at."""
    from app.ledger.coverage import coverage_rows

    make_company(ledger_session, ticker="FIXA.NS", name="Fixture Alpha Ltd",
                 isin="INFIXTUREA01", market_cap=11111.0)
    assert coverage_rows(ledger_session, as_of=AS_OF) == []


def test_coverage_reports_companies_and_sector_market_cap_share(ledger_session):
    from app.ledger.coverage import coverage_rows

    tagged = make_company(ledger_session, ticker="FIXA.NS", name="Fixture Alpha Ltd",
                          isin="INFIXTUREA01", sector="Fixture Sector",
                          market_cap=11111.0)
    make_company(ledger_session, ticker="FIXB.NS", name="Fixture Beta Ltd",
                 isin="INFIXTUREB01", sector="Fixture Sector", market_cap=33333.0)
    _exposure(ledger_session, tagged.id, as_of_date=AS_OF - timedelta(days=100),
              exposure_tag="input:fixture_foo", exposure_id="fixture-cov-1")

    rows = coverage_rows(ledger_session, as_of=AS_OF)
    assert len(rows) == 1
    row = rows[0]
    assert row["sector"] == "Fixture Sector"
    assert row["exposure_tag"] == "input:fixture_foo"
    assert row["companies_tagged"] == 1
    assert row["pct_sector_market_cap_tagged"] == 25.0
    assert row["median_exposure_age_days"] == 100


def test_median_exposure_age_is_a_median(ledger_session):
    from app.ledger.coverage import coverage_rows

    a = make_company(ledger_session, ticker="FIXA.NS", name="Fixture Alpha Ltd",
                     isin="INFIXTUREA01", market_cap=11111.0)
    b = make_company(ledger_session, ticker="FIXB.NS", name="Fixture Beta Ltd",
                     isin="INFIXTUREB01", market_cap=11111.0)
    c = make_company(ledger_session, ticker="FIXC.NS", name="Fixture Gamma Ltd",
                     isin="INFIXTUREC01", market_cap=11111.0)
    for index, company in enumerate((a, b, c)):
        _exposure(ledger_session, company.id,
                  as_of_date=AS_OF - timedelta(days=100 * (index + 1)),
                  exposure_tag="input:fixture_foo", exposure_id=f"fixture-med-{index}")

    row = coverage_rows(ledger_session, as_of=AS_OF)[0]
    assert row["median_exposure_age_days"] == 200


def test_the_coverage_view_exists_in_the_schema(ledger_session):
    """The DoD asks for a VIEW, not only a Python function -- the view is
    what a human can query without importing the app."""
    names = {row[0] for row in ledger_session.execute(text(
        "SELECT name FROM sqlite_master WHERE type='view'"))}
    assert {"exposure_coverage", "extractor_quality"} <= names


def test_metrics_are_exported_in_prometheus_text_format(ledger_session):
    from app.ledger.coverage import metrics_text

    company = make_company(ledger_session, ticker="FIXA.NS", name="Fixture Alpha Ltd",
                           isin="INFIXTUREA01", market_cap=11111.0)
    _exposure(ledger_session, company.id, as_of_date=AS_OF - timedelta(days=100),
              exposure_tag="input:fixture_foo", exposure_id="fixture-metrics-1")

    body = metrics_text(ledger_session, as_of=AS_OF)
    assert "# TYPE newsflo_ledger_exposure_rows gauge" in body
    assert "newsflo_ledger_exposure_rows 1" in body
    assert "newsflo_ledger_exposure_age_p90_days" in body
    assert "newsflo_ledger_stale_exposure_rows" in body
    # FIX ROUND 1 / I3: both extraction-failure modes are exported, since an
    # extractor that has started producing rubbish is an operational event.
    assert "newsflo_ledger_unverbatim_proposals" in body
    assert "newsflo_ledger_malformed_proposals" in body


def test_the_p90_age_alert_fires_past_the_configured_threshold(ledger_session):
    from app.ledger.coverage import age_alert

    company = make_company(ledger_session, ticker="FIXA.NS", name="Fixture Alpha Ltd",
                           isin="INFIXTUREA01", market_cap=11111.0)
    _exposure(ledger_session, company.id, as_of_date=AS_OF - timedelta(days=10),
              exposure_tag="input:fixture_fresh", exposure_id="fixture-alert-1")
    assert age_alert(ledger_session, as_of=AS_OF) is None

    _exposure(ledger_session, company.id, as_of_date=AS_OF - timedelta(days=900),
              exposure_tag="input:fixture_old", exposure_id="fixture-alert-2")
    alert = age_alert(ledger_session, as_of=AS_OF)
    assert alert is not None
    assert "p90" in alert.lower()


def test_metrics_on_an_empty_ledger_report_zero_rows_and_no_age(ledger_session):
    from app.ledger.coverage import metrics_text

    body = metrics_text(ledger_session, as_of=AS_OF)
    assert "newsflo_ledger_exposure_rows 0" in body
    # No rows means no age to report -- not an age of 0.
    assert "newsflo_ledger_exposure_age_p90_days" not in body


def test_extractor_quality_tracks_approve_and_edit_rate(ledger_session, filing_fixture):
    from app.ingest.filings.documents import document_from_pages
    from app.ingest.filings.proposals import ExposureProposal, record_proposals
    from app.ledger.coverage import extractor_quality
    from app.ledger.review import approve_proposal, reject_proposal
    from tests.phase1.conftest import FIXTURE_NOW

    company = make_company(ledger_session, ticker="FIXCO.NS",
                           name=filing_fixture["company_name"],
                           isin=filing_fixture["isin"], market_cap=11111.0)
    document = document_from_pages(filing_fixture["pages"],
                                   url=filing_fixture["source_url"],
                                   retrieved_at=FIXTURE_NOW, media_type="text/plain")
    honest = {k: v for k, v in filing_fixture["honest_proposal"].items()
              if not k.startswith("_")}
    proposals = [
        ExposureProposal(company_id=company.id, as_of_date=date(2222, 2, 22),
                         created_by="llm:fixture-model-not-real",
                         extractor_version="fixture-v0",
                         **dict(honest, exposure_tag=f"input:fixture_{i}"))
        for i in range(2)]
    record_proposals(ledger_session, proposals, document)

    ids = [r[0] for r in ledger_session.execute(text(
        "SELECT proposal_id FROM exposure_proposal ORDER BY exposure_tag")).all()]
    approve_proposal(ledger_session, ids[0], reviewed_by="human:fixture",
                     edits={"share_of_base": 0.2222})
    reject_proposal(ledger_session, ids[1], reviewed_by="human:fixture",
                    reason="fixture rejection")

    rows = extractor_quality(ledger_session)
    assert len(rows) == 1
    row = rows[0]
    assert row["extractor"] == "llm:fixture-model-not-real"
    assert row["proposed"] == 2
    assert row["approved"] == 1
    assert row["edited"] == 1
    assert row["approve_rate"] == 0.5
    assert row["edit_rate"] == 1.0


def test_malformed_rows_count_against_the_extractors_approve_rate(
        ledger_session, filing_fixture):
    """FIX ROUND 1 / I3. The regression signal only works if a prompt that
    starts emitting excerpt-less rows MOVES the approve rate. A malformed row
    is in the denominator."""
    from app.ingest.filings.documents import document_from_pages
    from app.ingest.filings.proposals import (
        DroppedRow, ExposureProposal, record_malformed, record_proposals,
    )
    from app.ledger.coverage import extractor_quality
    from app.ledger.review import approve_proposal
    from tests.phase1.conftest import FIXTURE_NOW

    company = make_company(ledger_session, ticker="FIXCO.NS",
                           name=filing_fixture["company_name"],
                           isin=filing_fixture["isin"], market_cap=11111.0)
    document = document_from_pages(filing_fixture["pages"],
                                   url=filing_fixture["source_url"],
                                   retrieved_at=FIXTURE_NOW, media_type="text/plain")
    honest = {k: v for k, v in filing_fixture["honest_proposal"].items()
              if not k.startswith("_")}
    record_proposals(ledger_session, [ExposureProposal(
        company_id=company.id, as_of_date=date(2222, 2, 22),
        created_by="llm:fixture-model-not-real", extractor_version="fixture-v0",
        **honest)], document)
    proposal_id = ledger_session.execute(
        text("SELECT proposal_id FROM exposure_proposal")).scalar()
    approve_proposal(ledger_session, proposal_id, reviewed_by="human:fixture")

    before = extractor_quality(ledger_session)[0]
    assert before["approve_rate"] == 1.0
    assert before["malformed"] == 0

    record_malformed(ledger_session,
                     [DroppedRow("NO_EXCERPT", {"exposure_tag": "input:fixture_x"})],
                     document, company_id=company.id,
                     created_by="llm:fixture-model-not-real",
                     model_id="fixture-model-not-real",
                     extractor_version="fixture-v0")

    after = extractor_quality(ledger_session)[0]
    assert after["proposed"] == 2
    assert after["malformed"] == 1
    assert after["rejected"] == 1
    assert after["approve_rate"] == 0.5
