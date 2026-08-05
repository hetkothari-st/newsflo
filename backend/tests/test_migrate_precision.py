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
    MarketMove,
    User,
    utcnow,
)
from app.pipeline import CONFIDENCE_FLOOR, LEVEL_CONFIDENCE_MULTIPLIER
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


def test_below_floor_deletion_takes_its_market_move_but_spares_a_surviving_alert_companys(db_session):
    """Regression test for the root-cause bug this migration shares with
    reanalyze_cascade.py: MarketMove references alert_id/company_id
    directly, not alert_company_id, so it is NOT in ALERT_COMPANY_DEPENDENTS
    and the dependents loop never touches it. Deleting ~270 sub-floor rows
    in production without this fix would orphan their MarketMove rows and
    reproduce the exact StopIteration crash
    app.market.alert_measurement.compute_alert_measurement hit in
    production. Two AlertCompany rows on the SAME alert -- one below the
    floor (deleted), one above it (kept) -- each with their own MarketMove.
    The below-floor row's MarketMove must go with it; the kept row's
    MarketMove must survive untouched. That second half is the one that
    catches an over-broad delete (e.g. filtering only on alert_id and
    sweeping up a surviving row's own measurement).
    """
    deleted_co = Company(ticker="HPCL.NS", name="HPCL", sector="oil_gas", index_tier="NIFTY50")
    kept_co = Company(ticker="BPCL.NS", name="BPCL", sector="oil_gas", index_tier="NIFTY50")
    db_session.add_all([deleted_co, kept_co])
    db_session.commit()

    article = Article(source="test", url="https://example.com/mm-orphan", title="t")
    db_session.add(article)
    db_session.commit()

    alert = Alert(article_id=article.id, category="test")
    db_session.add(alert)
    db_session.commit()

    below_floor = AlertCompany(
        alert_id=alert.id, company_id=deleted_co.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, basis="direct_mention",
        confidence_score=CONFIDENCE_FLOOR - 1,
    )
    kept = AlertCompany(
        alert_id=alert.id, company_id=kept_co.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, basis="direct_mention",
        confidence_score=CONFIDENCE_FLOOR + 30,
    )
    db_session.add_all([below_floor, kept])
    db_session.commit()
    below_floor_id, kept_id = below_floor.id, kept.id

    db_session.add(MarketMove(
        alert_id=alert.id, company_id=deleted_co.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=-1.0, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=kept_co.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=2.0, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    run_migration(db_session, dry_run=False)

    assert db_session.query(AlertCompany).filter_by(id=below_floor_id).count() == 0
    assert db_session.query(AlertCompany).filter_by(id=kept_id).count() == 1
    assert db_session.query(MarketMove).filter_by(alert_id=alert.id, company_id=deleted_co.id).count() == 0
    survivor_move = db_session.query(MarketMove).filter_by(alert_id=alert.id, company_id=kept_co.id).one()
    assert survivor_move.excess_move_pct == 2.0


def test_dry_run_leaves_market_move_rows_untouched(db_session):
    company = Company(ticker="IOC.NS", name="IOC", sector="oil_gas", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()

    article = Article(source="test", url="https://example.com/mm-dry-run", title="t")
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
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=-1.0, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    run_migration(db_session, dry_run=True)

    assert db_session.query(MarketMove).filter_by(alert_id=alert.id, company_id=company.id).count() == 1


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


def _make_alert_company(db_session, ticker, url, impact_level, confidence_score):
    """Shared scaffolding for the floor-reconstruction tests below: one
    Company/Article/Alert plus a single AlertCompany row with the given
    already-persisted (post-multiplier) confidence_score and impact_level."""
    company = Company(ticker=ticker, name=ticker, sector="oil_gas", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()

    article = Article(source="test", url=url, title="t")
    db_session.add(article)
    db_session.commit()

    alert = Alert(article_id=article.id, category="test")
    db_session.add(alert)
    db_session.commit()

    row = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, basis="direct_mention",
        confidence_score=confidence_score, impact_level=impact_level,
    )
    db_session.add(row)
    db_session.commit()
    return row.id


def test_indirect_l2_row_kept_when_pre_multiplier_score_clears_floor(db_session):
    """A pre-multiplier score of 69 clears CONFIDENCE_FLOOR (40) on its own,
    but indirect_l2's 0.45x multiplier persists round(69 * 0.45) = 31 --
    below 40. The migration must reconstruct the pre-multiplier score and
    keep this row, not delete it for a "low" score that's really just the
    intended distance discount."""
    multiplier = LEVEL_CONFIDENCE_MULTIPLIER["indirect_l2"]
    pre_score = 69
    assert pre_score >= CONFIDENCE_FLOOR  # would have been kept under the real (unrounded) rule
    persisted = round(pre_score * multiplier)
    assert persisted < CONFIDENCE_FLOOR  # and yet the persisted value reads as sub-floor

    row_id = _make_alert_company(
        db_session, "IOC.NS", "https://example.com/l2-clears",
        impact_level="indirect_l2", confidence_score=persisted,
    )

    run_migration(db_session, dry_run=False)

    assert db_session.query(AlertCompany).filter_by(id=row_id).count() == 1


def test_direct_row_genuinely_below_floor_still_deleted(db_session):
    """A direct row (multiplier 1.0, so persisted == pre-multiplier score)
    that is actually below the floor must still be dropped -- the fix only
    corrects the multiplier compounding, it doesn't stop enforcing the
    floor."""
    row_id = _make_alert_company(
        db_session, "BPCL.NS", "https://example.com/direct-low",
        impact_level="direct", confidence_score=CONFIDENCE_FLOOR - 10,
    )

    run_migration(db_session, dry_run=False)

    assert db_session.query(AlertCompany).filter_by(id=row_id).count() == 0


def test_borderline_rounding_favours_retention(db_session):
    """Documents the chosen rounding direction (see migrate_precision._below_floor):
    an indirect_l2 row with a true pre-multiplier score of 39 -- one point
    below the floor, so it WOULD have been dropped under the real, unrounded
    rule -- persists as round(39 * 0.45) = 18. Reconstructing generously,
    (18 + 0.5) / 0.45 = 41.1, which reads as >= floor. The migration keeps
    this row: an occasional false keep on a rounding boundary is the
    accepted tradeoff against ever falsely deleting a row that should have
    survived, since deletion is irreversible and retention is not."""
    multiplier = LEVEL_CONFIDENCE_MULTIPLIER["indirect_l2"]
    pre_score = CONFIDENCE_FLOOR - 1  # 39: genuinely below floor under the real rule
    persisted = round(pre_score * multiplier)
    assert persisted == 18

    row_id = _make_alert_company(
        db_session, "GAIL.NS", "https://example.com/l2-borderline",
        impact_level="indirect_l2", confidence_score=persisted,
    )

    run_migration(db_session, dry_run=False)

    assert db_session.query(AlertCompany).filter_by(id=row_id).count() == 1
