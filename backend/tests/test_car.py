from datetime import timedelta

from app.models import Alert, AlertCompany, Article, Company, MarketMove, CarOutcome, utcnow
from app.outcomes.car import check_pending_car_outcomes, compute_car_outcome_label


def test_compute_car_outcome_label_held_when_same_sign():
    assert compute_car_outcome_label(day0_excess_move_pct=-4.2, car_pct=-3.0) == "HELD"
    assert compute_car_outcome_label(day0_excess_move_pct=2.1, car_pct=1.5) == "HELD"


def test_compute_car_outcome_label_reversed_when_opposite_sign():
    assert compute_car_outcome_label(day0_excess_move_pct=-4.2, car_pct=3.0) == "REVERSED"
    assert compute_car_outcome_label(day0_excess_move_pct=2.1, car_pct=-1.5) == "REVERSED"


def test_compute_car_outcome_label_flat_when_near_zero():
    assert compute_car_outcome_label(day0_excess_move_pct=-4.2, car_pct=0.1) == "FLAT"
    assert compute_car_outcome_label(day0_excess_move_pct=2.1, car_pct=-0.2) == "FLAT"


def _company(ticker):
    return Company(ticker=ticker, name=f"Company {ticker}", sector="oil_gas", index_tier="NIFTY50")


def _article(db_session, url):
    article = Article(source="test", url=url, title="t", content="c")
    db_session.add(article)
    db_session.commit()
    return article


def _alert_company(alert_id, company_id):
    return AlertCompany(
        alert_id=alert_id, company_id=company_id, direction="bearish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
    )


def test_check_pending_car_outcomes_creates_a_row_when_fetch_succeeds(db_session):
    company = _company("A.NS")
    db_session.add(company)
    db_session.commit()
    article = _article(db_session, "https://example.com/car1")
    old_created_at = utcnow() - timedelta(days=10)
    alert = Alert(article_id=article.id, category="oil_gas", created_at=old_created_at)
    db_session.add(alert)
    db_session.flush()
    ac = _alert_company(alert.id, company.id)
    db_session.add(ac)
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.8, sector_move_pct=-0.6, excess_move_pct=-4.2,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    created = check_pending_car_outcomes(db_session, fetch_fn=lambda *a, **k: -3.5)

    assert created == 1
    row = db_session.query(CarOutcome).one()
    assert row.company_id == company.id
    assert row.category == "oil_gas"
    assert row.day0_excess_move_pct == -4.2
    assert row.car_pct == -3.5


def test_check_pending_car_outcomes_skips_when_fetch_returns_none(db_session):
    company = _company("A.NS")
    db_session.add(company)
    db_session.commit()
    article = _article(db_session, "https://example.com/car2")
    alert = Alert(article_id=article.id, category="oil_gas", created_at=utcnow() - timedelta(days=10))
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, company.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.8, sector_move_pct=-0.6, excess_move_pct=-4.2,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    created = check_pending_car_outcomes(db_session, fetch_fn=lambda *a, **k: None)

    assert created == 0
    assert db_session.query(CarOutcome).count() == 0


def test_check_pending_car_outcomes_skips_unmeasured_alert_companies(db_session):
    company = _company("A.NS")
    db_session.add(company)
    db_session.commit()
    article = _article(db_session, "https://example.com/car3")
    alert = Alert(article_id=article.id, category="oil_gas", created_at=utcnow() - timedelta(days=10))
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, company.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        measurement_status="no_data", measured_at=utcnow(),
    ))
    db_session.commit()

    created = check_pending_car_outcomes(db_session, fetch_fn=lambda *a, **k: -3.5)

    assert created == 0


def test_check_pending_car_outcomes_skips_alerts_too_recent(db_session):
    company = _company("A.NS")
    db_session.add(company)
    db_session.commit()
    article = _article(db_session, "https://example.com/car4")
    alert = Alert(article_id=article.id, category="oil_gas", created_at=utcnow())
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, company.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.8, sector_move_pct=-0.6, excess_move_pct=-4.2,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    created = check_pending_car_outcomes(db_session, fetch_fn=lambda *a, **k: -3.5)

    assert created == 0


def test_check_pending_car_outcomes_does_not_recreate_existing_row(db_session):
    company = _company("A.NS")
    db_session.add(company)
    db_session.commit()
    article = _article(db_session, "https://example.com/car5")
    alert = Alert(article_id=article.id, category="oil_gas", created_at=utcnow() - timedelta(days=10))
    db_session.add(alert)
    db_session.flush()
    ac = _alert_company(alert.id, company.id)
    db_session.add(ac)
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.8, sector_move_pct=-0.6, excess_move_pct=-4.2,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.flush()
    db_session.add(CarOutcome(
        alert_company_id=ac.id, company_id=company.id, category="oil_gas",
        day0_excess_move_pct=-4.2, car_pct=-3.0,
    ))
    db_session.commit()

    created = check_pending_car_outcomes(db_session, fetch_fn=lambda *a, **k: -9.9)

    assert created == 0
    assert db_session.query(CarOutcome).count() == 1
