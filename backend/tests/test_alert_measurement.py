from app.market.alert_measurement import compute_alert_measurement
from app.models import Alert, AlertCompany, Article, Company, MarketMove, utcnow


def _company(ticker, sector="oil_gas"):
    return Company(ticker=ticker, name=f"Company {ticker}", sector=sector, index_tier="NIFTY50")


def _article(db_session):
    article = Article(source="test", url="https://example.com/a", title="t", content="c")
    db_session.add(article)
    db_session.commit()
    return article


def _alert_company(alert_id, company_id, direction="bullish"):
    return AlertCompany(
        alert_id=alert_id, company_id=company_id, direction=direction,
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
    )


def test_returns_none_when_no_measured_companies(db_session):
    company = _company("A.NS")
    db_session.add(company)
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, company.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        measurement_status="no_data", measured_at=utcnow(),
    ))
    db_session.commit()

    assert compute_alert_measurement(db_session, alert) is None


def test_single_measured_company_is_the_peak(db_session):
    company = _company("A.NS")
    db_session.add(company)
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, company.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.8, sector_move_pct=-0.6, excess_move_pct=-4.2,
        volume=300.0, avg_volume_20d=100.0, volume_multiple=3.0,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_alert_measurement(db_session, alert)

    assert result["excess_move_pct"] == -4.2
    assert result["direction"] == "bearish"
    assert result["raw_move_pct"] == -4.8
    assert result["sector_move_pct"] == -0.6
    assert result["volume_multiple"] == 3.0
    assert result["peak_ticker"] == "A.NS"
    assert result["peak_company_name"] == "Company A.NS"
    assert result["benchmark_ticker"] == "^CNXENERGY"
    assert result["is_fallback_benchmark"] is False
    assert result["verdict"] in ("COMPANY_SPECIFIC", "SECTOR_WIDE")
    assert set(result["intensity"].keys()) == {"score", "band", "components"}
    assert isinstance(result["breadth_score"], int)


def test_picks_the_larger_magnitude_move_as_peak(db_session):
    small = _company("SMALL.NS")
    big = _company("BIG.NS")
    db_session.add_all([small, big])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, small.id))
    db_session.add(_alert_company(alert.id, big.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=small.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=0.5, sector_move_pct=0.3, excess_move_pct=0.2,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=big.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-6.0, sector_move_pct=-0.5, excess_move_pct=-5.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_alert_measurement(db_session, alert)

    assert result["peak_ticker"] == "BIG.NS"
    assert result["excess_move_pct"] == -5.5


def test_no_data_companies_are_excluded_but_do_not_block_the_measured_ones(db_session):
    measured = _company("A.NS")
    unmeasured = _company("B.NS")
    db_session.add_all([measured, unmeasured])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, measured.id))
    db_session.add(_alert_company(alert.id, unmeasured.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=measured.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=2.0, sector_move_pct=0.5, excess_move_pct=1.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=unmeasured.id, benchmark_ticker="^NSEI",
        measurement_status="no_data", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_alert_measurement(db_session, alert)

    assert result is not None
    assert result["peak_ticker"] == "A.NS"


def test_fallback_benchmark_sector_is_flagged(db_session):
    company = _company("A.NS", sector="textiles")  # textiles falls back to Nifty 50
    db_session.add(company)
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="other")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, company.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^NSEI",
        raw_move_pct=1.0, sector_move_pct=0.2, excess_move_pct=0.8,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_alert_measurement(db_session, alert)

    assert result["is_fallback_benchmark"] is True
