"""TASK 1.1 -- the ledger schema and its DB-level constraints.

The phase file's TESTS section, verbatim:
  - no_selfcertify constraint rejects MODELLED without reviewed_by
  - curve_needs_review constraint rejects ESTIMATED without reviewed_by
  - freshness defaults load from config

Plus the two structural facts the fabrication guard demands: every ledger
table ships EMPTY, and every ledger row carries a source_url column that
cannot be NULL.
"""
import uuid

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

LEDGER_TABLES = ("company_exposure", "company_segment", "company_financials",
                 "pass_through_curve", "company_modifier", "exposure_proposal",
                 "filing_artefact")


def _exposure_row(**overrides) -> dict:
    row = {
        "exposure_id": str(uuid.uuid4()),
        "company_id": 1,
        "segment_id": None,
        "exposure_kind": "INPUT_COST",
        "exposure_tag": "input:fixture_foo",
        "share_of_base": 0.1111,
        "base_kind": "COGS",
        "base_value_inr": 99999.0,
        "measurement": "FILED",
        "source_type": "ANNUAL_REPORT",
        "source_url": "https://fixture.invalid/testco/annual-report-fixture.pdf",
        "source_page": "2",
        "as_of_date": "2222-02-22",
        "freshness_days": 400,
        "confidence": 0.1111,
        "created_by": "test:phase1",
        "reviewed_by": None,
        "proposal_id": None,
    }
    row.update(overrides)
    return row


def _insert_exposure(session, **overrides) -> None:
    from app.ledger.review import review_session

    row = _exposure_row(**overrides)
    columns = ", ".join(row)
    values = ", ".join(f":{c}" for c in row)
    with review_session(session):
        session.execute(
            text(f"INSERT INTO company_exposure ({columns}) VALUES ({values})"), row)
        session.commit()


def test_the_ledger_tables_exist(ledger_engine):
    tables = set(inspect(ledger_engine).get_table_names())
    for table in LEDGER_TABLES:
        assert table in tables, f"{table} missing"


def test_the_v4_company_exposures_table_is_untouched(ledger_engine):
    """The repo already has a `company_exposures` (plural) ordinal-rating
    table. The V5 ledger is `company_exposure` (singular) and must not
    collide with, replace or alter it."""
    tables = set(inspect(ledger_engine).get_table_names())
    assert {"company_exposure", "company_exposures"} <= tables
    columns = {c["name"] for c in inspect(ledger_engine).get_columns("company_exposures")}
    assert columns == {"id", "company_id", "dimension", "level", "source",
                       "version", "updated_at"}


def test_every_ledger_table_ships_empty(ledger_session):
    """The whole point of Phase 1: machinery, not data."""
    for table in LEDGER_TABLES:
        count = ledger_session.execute(text(f"SELECT count(*) FROM {table}")).scalar()
        assert count == 0, f"{table} shipped with {count} row(s)"


def test_no_selfcertify_rejects_modelled_without_reviewed_by(ledger_session):
    with pytest.raises(IntegrityError):
        _insert_exposure(ledger_session, measurement="MODELLED", reviewed_by=None)


def test_no_selfcertify_accepts_modelled_with_reviewed_by(ledger_session):
    _insert_exposure(ledger_session, measurement="MODELLED", reviewed_by="human:fixture")
    assert ledger_session.execute(
        text("SELECT count(*) FROM company_exposure")).scalar() == 1


def test_curve_needs_review_rejects_estimated_without_reviewed_by(ledger_session):
    from app.ledger.review import review_session

    row = {
        "curve_id": str(uuid.uuid4()), "company_id": None,
        "sector_id": "fixture-sector", "exposure_tag": "input:fixture_foo",
        "points": '[{"lag_days": 0, "fraction": 0.0}]', "ceiling": None,
        "basis": "ESTIMATED", "evidence_id": None, "as_of_date": "2222-02-22",
        "reviewed_by": None,
    }
    with pytest.raises(IntegrityError):
        with review_session(ledger_session):
            ledger_session.execute(text(
                "INSERT INTO pass_through_curve (curve_id, company_id, sector_id, "
                "exposure_tag, points, ceiling, basis, evidence_id, as_of_date, "
                "reviewed_by) VALUES (:curve_id, :company_id, :sector_id, "
                ":exposure_tag, :points, :ceiling, :basis, :evidence_id, "
                ":as_of_date, :reviewed_by)"), row)
            ledger_session.commit()


def test_curve_needs_review_accepts_estimated_with_reviewed_by(ledger_session):
    from app.ledger.review import review_session

    with review_session(ledger_session):
        ledger_session.execute(text(
            "INSERT INTO pass_through_curve (curve_id, exposure_tag, points, "
            "basis, as_of_date, reviewed_by) VALUES (:curve_id, :tag, :points, "
            "'ESTIMATED', '2222-02-22', 'human:fixture')"), {
                "curve_id": str(uuid.uuid4()), "tag": "input:fixture_foo",
                "points": '[{"lag_days": 0, "fraction": 0.0}]'})
        ledger_session.commit()
    assert ledger_session.execute(
        text("SELECT count(*) FROM pass_through_curve")).scalar() == 1


def test_source_url_is_not_nullable_anywhere_in_the_ledger(ledger_engine):
    """THE ONE RULE: a ledger row that cannot be traced to a document is not
    a ledger row."""
    inspector = inspect(ledger_engine)
    for table in ("company_exposure", "company_segment", "company_financials",
                  "company_modifier", "filing_artefact"):
        column = {c["name"]: c for c in inspector.get_columns(table)}["source_url"]
        assert column["nullable"] is False, f"{table}.source_url is nullable"


def test_freshness_defaults_load_from_config():
    from app.ledger.freshness import freshness_days_for, load_freshness_config

    config = load_freshness_config()
    assert config.version
    assert freshness_days_for("INPUT_COST") == 400
    assert freshness_days_for("REVENUE_REALIZATION") == 400
    assert freshness_days_for("FX_TRANSACTION") == 200
    assert freshness_days_for("FX_TRANSLATION") == 200
    assert freshness_days_for("INTEREST_RATE") == 200
    assert freshness_days_for("REGULATORY") == 120


def test_a_kind_with_no_configured_freshness_raises_rather_than_defaulting():
    """Fabrication guard: a missing policy number is missing, not 365."""
    from app.ledger.freshness import FreshnessNotConfigured, freshness_days_for

    with pytest.raises(FreshnessNotConfigured):
        freshness_days_for("VOLUME_DEMAND")


def test_freshness_config_names_no_company_and_no_financial_value():
    """config/freshness.yaml is POLICY (how old is too old), never data."""
    from app.ledger.freshness import FRESHNESS_CONFIG_PATH

    body = FRESHNESS_CONFIG_PATH.read_text(encoding="utf-8")
    for word in ("crore", "lakh", "INR", "Ltd", "Limited"):
        assert word not in body
