"""TASK 6.3 -- the review console.

A human window into every decision, mounted ADDITIVELY on the standalone
ledger console (the same console Phase 1's exposure queue, Phase 3's edge and
coverage-gap queues and Phase 5's divergence queue already live on). Four
queues, one console.

The load-bearing property is the one invariant 12 states: **the rejected set
is visible, with reasons**. A console that showed only what published would
be a marketing page for the pipeline.
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from tests.phase6 import helpers
from tests.phase6.conftest import (
    BACKEND, FIXTURE_ANALYSIS_VERSION, FIXTURE_NOW, load_fixture,
)

EVENT_ID = "article:6001"
LABELER = "human:fixture-reviewer"


@pytest.fixture()
def seeded(phase6_engine):
    """One event's worth of canonical records, signals and evidence.

    Written through the REAL write paths: `company_impact` via the reducer
    capability (the table refuses anything else), signals via the append-only
    appender. Nothing here bypasses a guard.
    """
    from app.core.impact_writer import append_signals, persist_company_impact

    session = sessionmaker(bind=phase6_engine)()
    fixture = load_fixture("integrated_energy_sections.json")

    session.execute(text(
        "INSERT INTO articles (id, source, url, title, published_at) VALUES "
        "(6001, 'FIXTURE WIRE', 'https://fixture.invalid/crude-article', "
        "'Fixture crude benchmark moves', :published)"),
        {"published": FIXTURE_NOW})
    session.execute(text(
        "INSERT INTO alerts (id, article_id, category, created_at) VALUES "
        "(7001, 6001, 'commodity', :created)"), {"created": FIXTURE_NOW})
    session.execute(text(
        "INSERT INTO evidence_records (id, event_id, company_id, evidence_class, "
        "evidence_tier, source_type, source_name, source_url, fact_text) VALUES "
        "(4242, 7001, 6103, 'FILING', 'A', 'ANNUAL_REPORT', "
        "'Fixture Integrated Energy Ltd annual report', "
        "'https://fixture.invalid/filings/integrated-energy-ar.pdf', "
        "'fixture segment disclosure')"))

    for row in fixture["companies"]:
        session.execute(text(
            "INSERT INTO companies (id, ticker, name, sector, market, "
            "index_tier, tradeability) VALUES (:id, :ticker, :name, "
            "'Fixture Sector', 'INDIA', 'OTHER', 'NORMAL')"),
            {"id": row["company_id"], "ticker": row["ticker"], "name": row["name"]})

    for row in fixture["companies"]:
        record = helpers.impact(
            company_id=int(row["company_id"]), ticker=str(row["ticker"]),
            publication_tier=str(row["publication_tier"]),
            net_effect=str(row["net_effect"]), mechanism_id=row["mechanism_id"],
            headline_horizon=str(row["horizon_bucket"]),
            delta_ebitda_pct_p50=row.get("delta_ebitda_pct_p50"),
            rejection_reason=row.get("rejection_reason"),
            event_id=EVENT_ID,
            channels=[{"channel_id": f"fixture-{row['ticker'].lower()}",
                       "mechanism_id": row["mechanism_id"],
                       "horizon": str(row["horizon_bucket"]),
                       "direction": str(row["net_effect"]),
                       "materiality": "MEDIUM", "material": True,
                       "evidence_ids": ["4242"], "modifiers_applied": []}],
            claim_bindings=[{"claim_id": f"claim-{row['company_id']}",
                             "claim_type": "COST_EXPOSURE",
                             "binding_status": "BOUND", "evidence_grade": "B",
                             "evidence_ids": ["4242"]}],
            objections=([{"objection_id": "falsifier:q6:OFFSET_IGNORED",
                          "type": "OFFSET_IGNORED", "severity": "MAJOR",
                          "sustained": True, "rebutted_by": [],
                          "raised_by": "falsifier"}]
                        if row["ticker"] == "FIXINT" else []))
        persist_company_impact(session, record, reducer_run_seq=1)

    append_signals(session, [helpers.signal(
        "OBJECTION", {"objection_id": "falsifier:q6:OFFSET_IGNORED",
                      "type": "OFFSET_IGNORED", "severity": "MAJOR",
                      "sustained": True, "raised_by": "falsifier",
                      "model_id": "fixture-falsifier-model"},
        stage="FALSIFICATION", company_id=6103, event_id=EVENT_ID,
        analysis_version=FIXTURE_ANALYSIS_VERSION)])
    session.commit()
    session.close()
    return phase6_engine


@pytest.fixture()
def client(seeded):
    from tools.ledger_ui import build_app

    return TestClient(build_app(seeded))


# ---------------------------------------------------------------------------
# the phase file's TESTS section
# ---------------------------------------------------------------------------

def test_rejected_candidates_are_visible_with_their_reasons(client):
    """Invariant 12, and the phase file's last DO NOT. The rejected set is
    not a footnote: the candidate and the reason are both on the page."""
    page = client.get(f"/event?event_id={EVENT_ID}")
    assert page.status_code == 200
    body = page.text

    assert "FIXREJ" in body
    assert "PRIMARY_FAILED_EVIDENCE" in body
    assert "rejected" in body.lower()


def test_a_rejected_candidate_is_never_shown_as_a_published_section(seeded):
    from app.ledger.event_review import event_detail

    with seeded.connect() as connection:
        detail = event_detail(connection, EVENT_ID)

    placed = {c["ticker"] for s in detail["sections"] for c in s["companies"]}
    assert "FIXREJ" not in placed
    assert [r["ticker"] for r in detail["rejected"]] == ["FIXREJ"]
    assert detail["rejected"][0]["rejection_reason"] == "PRIMARY_FAILED_EVIDENCE"


def test_labels_persist_to_the_eval_corpus_with_the_labeler_identity(client, seeded):
    response = client.post("/event/label", data={
        "event_id": EVENT_ID, "company_ref": "FIXINT", "labeler": LABELER,
        "label": "WRONG_MECHANISM", "expected_tier": "SECONDARY_RIPPLE",
        "expected_direction": "mixed", "rationale": "fixture rationale"},
        follow_redirects=False)
    assert response.status_code in (303, 200), response.text

    with seeded.connect() as connection:
        row = connection.execute(text(
            "SELECT event_id, company_ref, labeler, label, expected_tier, "
            "expected_direction, rationale, labeled_at FROM eval_label")
        ).mappings().one()

    assert row["event_id"] == EVENT_ID
    assert row["company_ref"] == "FIXINT"
    assert row["labeler"] == LABELER
    assert row["label"] == "WRONG_MECHANISM"
    assert row["expected_tier"] == "SECONDARY_RIPPLE"
    assert row["rationale"] == "fixture rationale"
    assert row["labeled_at"] is not None


def test_a_label_outside_the_phase_file_vocabulary_is_refused(client, seeded):
    response = client.post("/event/label", data={
        "event_id": EVENT_ID, "company_ref": "FIXINT", "labeler": LABELER,
        "label": "FIXTURE_MADE_UP_LABEL", "expected_tier": "PRIMARY"},
        follow_redirects=False)
    assert response.status_code == 400

    with seeded.connect() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM eval_label")).scalar() == 0


def test_a_label_without_a_labeler_is_refused(client, seeded):
    """A label nobody signed is not evidence about anything."""
    response = client.post("/event/label", data={
        "event_id": EVENT_ID, "company_ref": "FIXINT", "labeler": "",
        "label": "CORRECT", "expected_tier": "PRIMARY"}, follow_redirects=False)
    assert response.status_code == 400
    with seeded.connect() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM eval_label")).scalar() == 0


def test_the_label_vocabulary_is_the_phase_files_nine():
    from app.ledger.event_review import REVIEW_LABELS

    assert REVIEW_LABELS == (
        "CORRECT", "WRONG_COMPANY", "WRONG_DIRECTION", "WRONG_MECHANISM",
        "WRONG_MATERIALITY", "WRONG_TIER", "WRONG_SECTION",
        "INSUFFICIENT_EVIDENCE", "DISPUTED")


def test_evidence_links_resolve_to_the_stored_source_urls(client):
    page = client.get(f"/event?event_id={EVENT_ID}")
    assert "https://fixture.invalid/filings/integrated-energy-ar.pdf" in page.text
    assert ("href='https://fixture.invalid/filings/integrated-energy-ar.pdf'"
            in page.text
            or 'href="https://fixture.invalid/filings/integrated-energy-ar.pdf"'
            in page.text)


def test_an_unresolvable_evidence_id_is_reported_not_hidden(client, seeded):
    """An evidence id with no stored artefact is a broken chain, and a broken
    chain is exactly what this console exists to show."""
    from app.ledger.event_review import evidence_for_event

    with seeded.connect() as connection:
        resolved = evidence_for_event(connection, EVENT_ID, ["4242", "9999"])

    assert resolved["4242"]["source_url"].endswith("integrated-energy-ar.pdf")
    assert resolved["9999"] is None


# ---------------------------------------------------------------------------
# the rest of the phase file's per-event display list
# ---------------------------------------------------------------------------

def test_the_event_view_shows_the_article_and_its_shocks(client):
    body = client.get(f"/event?event_id={EVENT_ID}").text
    assert "Fixture crude benchmark moves" in body
    assert "https://fixture.invalid/crude-article" in body


def test_primary_ripple_and_rejected_are_three_separate_groups(seeded):
    from app.ledger.event_review import event_detail

    with seeded.connect() as connection:
        detail = event_detail(connection, EVENT_ID)

    assert {c["ticker"] for c in detail["by_tier"]["PRIMARY"]} == {
        "FIXOMC1", "FIXOMC2", "FIXINT", "FIXUP"}
    assert {c["ticker"] for c in detail["by_tier"]["SECONDARY_RIPPLE"]} == {
        "FIXAIR", "FIXPNT"}
    assert {r["ticker"] for r in detail["rejected"]} == {"FIXREJ"}


def test_the_four_separation_fields_are_four_separate_cells(client):
    """Invariant 4 at the console: the console renders each of the four in
    its own column and never joins two of them into one string."""
    from tests.phase0.test_field_separation import _python_violations

    path = BACKEND / "app" / "ledger" / "event_review_pages.py"
    assert not _python_violations(path)

    body = client.get(f"/event?event_id={EVENT_ID}").text
    for header in ("directness", "graph distance", "discovery", "tier"):
        assert header in body.lower()


def test_objections_are_shown_with_their_resolution(client):
    body = client.get(f"/event?event_id={EVENT_ID}").text
    assert "OFFSET_IGNORED" in body
    assert "sustained" in body.lower()


def test_the_console_renders_the_zero_primary_state_when_nothing_publishes(
        phase6_engine):
    from app.core.impact_writer import persist_company_impact
    from tools.ledger_ui import build_app

    session = sessionmaker(bind=phase6_engine)()
    session.execute(text(
        "INSERT INTO companies (id, ticker, name, sector, market, index_tier, "
        "tradeability) VALUES (6201, 'FIXZP', 'Fixture Zero Primary Ltd', "
        "'Fixture Sector', 'INDIA', 'OTHER', 'NORMAL')"))
    persist_company_impact(session, helpers.impact(
        company_id=6201, ticker="FIXZP", publication_tier="REJECTED",
        net_effect="NEGATIVE", mechanism_id="paints_input_cost",
        rejection_reason="PRIMARY_FAILED_EVIDENCE", event_id="article:6002"),
        reducer_run_seq=1)
    session.commit()
    session.close()

    body = TestClient(build_app(phase6_engine)).get("/event?event_id=article:6002").text
    assert "NO PRIMARY IMPACT IDENTIFIED" in body
    assert "1 candidate rejected" in body


def test_the_event_index_lists_every_event_with_its_counts(client):
    body = client.get("/events").text
    assert EVENT_ID in body
    assert "Fixture crude benchmark moves" in body


def test_one_console_four_queues(client):
    """The four queues are reachable from each other -- Phase 1's exposure
    proposals, Phase 3's coverage gaps, Phase 5's divergence reviews and this
    phase's events."""
    body = client.get(f"/event?event_id={EVENT_ID}").text
    for route in ("/", "/graph/gaps", "/divergence/queue", "/events"):
        assert f"href='{route}'" in body or f'href="{route}"' in body


# ---------------------------------------------------------------------------
# what the console may NOT do
# ---------------------------------------------------------------------------

def test_the_console_never_writes_a_canonical_record():
    """It is a WINDOW. The reducer is the only writer (invariant 1), and the
    console holds no reducer capability -- structurally, not by convention."""
    import ast

    for name in ("event_review.py", "event_review_pages.py"):
        source = (BACKEND / "app" / "ledger" / name).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                upper = node.value.upper()
                assert "INSERT INTO COMPANY_IMPACT" not in upper
                assert "UPDATE COMPANY_IMPACT" not in upper
                assert "INSERT INTO SIGNAL" not in upper
        assert "reducer_session" not in source


def test_the_console_cannot_write_company_impact_at_runtime(seeded):
    """The empirical proof, not the ast one: the guard refuses the console's
    own connection."""
    import sqlalchemy as sa

    session = sessionmaker(bind=seeded)()
    with pytest.raises(sa.exc.DatabaseError):
        session.execute(text(
            "UPDATE company_impact SET publication_tier = 'PRIMARY' "
            "WHERE ticker = 'FIXREJ'"))
    session.rollback()
    session.close()


def test_the_console_writes_only_the_eval_corpus(seeded):
    """The one write path this console has is the label. After a label, every
    canonical row is byte-identical."""
    from tools.ledger_ui import build_app

    def snapshot():
        with seeded.connect() as connection:
            return json.dumps([dict(r) for r in connection.execute(text(
                "SELECT * FROM company_impact ORDER BY id")).mappings()],
                default=str)

    before = snapshot()
    TestClient(build_app(seeded)).post("/event/label", data={
        "event_id": EVENT_ID, "company_ref": "FIXUP", "labeler": LABELER,
        "label": "CORRECT", "expected_tier": "PRIMARY"}, follow_redirects=False)
    assert snapshot() == before


def test_nothing_under_app_imports_the_console_module():
    """Same rule as every other page module: the console imports these, never
    the other way round."""
    for path in sorted((BACKEND / "app").rglob("*.py")):
        if path.name in ("event_review_pages.py",):
            continue
        source = path.read_text(encoding="utf-8")
        assert "tools.ledger_ui" not in source, path
