"""Regression coverage for backend/migrate_precision.py's row-count-based
sub-floor deletion. A row-count check alone would not have caught the real
incident this guards against: deleting a below-floor AlertCompany row
without first deleting the rows in CalibrationSample, CarOutcome,
EmailNotification, and AlertCompanyTranslation that reference it left 8
alert_company_translations rows and 4 calibration_samples rows dangling
(SQLite's default off FK enforcement hid it until something ran
PRAGMA foreign_key_check). This test builds one row in each of those four
dependent tables against a single below-floor AlertCompany, runs the
migration, and asserts every dependent is gone too -- not just the
AlertCompany row itself.
"""
from app.models import (
    Alert,
    AlertCompany,
    AlertCompanyTranslation,
    Article,
    CalibrationSample,
    CarOutcome,
    Company,
    EmailNotification,
    User,
)
from app.pipeline import CONFIDENCE_FLOOR
from migrate_precision import run_migration


def test_below_floor_deletion_leaves_no_dangling_dependents(db_session):
    company = Company(ticker="HPCL.NS", name="HPCL", sector="oil_gas", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()

    article = Article(source="test", url="https://example.com/y", title="t")
    db_session.add(article)
    db_session.commit()

    alert = Alert(article_id=article.id, category="test")
    db_session.add(alert)
    db_session.commit()

    user = User(email="u2@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()

    below_floor = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, basis="direct_mention",
        confidence_score=CONFIDENCE_FLOOR - 1, rationale="stale rationale",
    )
    db_session.add(below_floor)
    db_session.commit()
    below_floor_id = below_floor.id

    db_session.add(CalibrationSample(
        alert_company_id=below_floor_id, category="test", company_id=company.id,
        direction="bullish", magnitude_actual=1.5, horizon_days=1,
    ))
    db_session.add(CarOutcome(
        alert_company_id=below_floor_id, company_id=company.id, category="test",
        day0_excess_move_pct=1.0, car_pct=1.0,
    ))
    db_session.add(EmailNotification(user_id=user.id, alert_company_id=below_floor_id))
    db_session.add(AlertCompanyTranslation(alert_company_id=below_floor_id, lang="hi", rationale="r"))
    db_session.commit()

    run_migration(db_session, dry_run=False)

    assert db_session.query(AlertCompany).filter_by(id=below_floor_id).count() == 0
    assert db_session.query(CalibrationSample).filter_by(alert_company_id=below_floor_id).count() == 0
    assert db_session.query(CarOutcome).filter_by(alert_company_id=below_floor_id).count() == 0
    assert db_session.query(EmailNotification).filter_by(alert_company_id=below_floor_id).count() == 0
    assert db_session.query(AlertCompanyTranslation).filter_by(alert_company_id=below_floor_id).count() == 0


def test_dry_run_deletes_nothing(db_session):
    company = Company(ticker="BPCL.NS", name="BPCL", sector="oil_gas", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()

    article = Article(source="test", url="https://example.com/z", title="t")
    db_session.add(article)
    db_session.commit()

    alert = Alert(article_id=article.id, category="test")
    db_session.add(alert)
    db_session.commit()

    below_floor = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, basis="direct_mention",
        confidence_score=CONFIDENCE_FLOOR - 1,
    )
    db_session.add(below_floor)
    db_session.commit()

    run_migration(db_session, dry_run=True)

    assert db_session.query(AlertCompany).filter_by(id=below_floor.id).count() == 1
