from app.calibration.track_record import WIN_RATE_SAMPLE_THRESHOLD, get_win_rate
from app.models import Alert, AlertCompany, Article, CalibrationSample, Company, utcnow


def _make_company(session, ticker="RELIANCE.NS", name="Reliance Industries"):
    company = Company(ticker=ticker, name=name, sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    session.add(company)
    session.commit()
    return company


def _make_alert_company(session, company, direction, url_suffix):
    article = Article(source="test", url=f"https://example.com/{url_suffix}", title="t", status="ANALYZED")
    session.add(article)
    session.commit()
    alert = Alert(article_id=article.id, category="oil_energy", created_at=utcnow())
    session.add(alert)
    session.commit()
    ac = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction=direction,
        magnitude_low=1.0, magnitude_high=2.0, rationale="x", basis="direct_mention",
    )
    session.add(ac)
    session.commit()
    return ac


def _add_sample(session, ac, actual_direction, horizon_days, magnitude_actual=1.0):
    session.add(CalibrationSample(
        alert_company_id=ac.id, category="oil_energy", company_id=ac.company_id,
        direction=actual_direction, magnitude_actual=magnitude_actual, horizon_days=horizon_days,
    ))
    session.commit()


def test_threshold_is_five():
    assert WIN_RATE_SAMPLE_THRESHOLD == 5


def test_returns_none_when_no_horizon_has_enough_samples(db_session):
    company = _make_company(db_session)
    for i in range(4):  # below threshold
        ac = _make_alert_company(db_session, company, "bullish", url_suffix=i)
        _add_sample(db_session, ac, "bullish", horizon_days=1)

    assert get_win_rate(db_session, company.id) is None


def test_computes_win_rate_for_qualifying_horizon(db_session):
    company = _make_company(db_session)
    # 4 correct predictions, 1 wrong -> win_rate 0.8
    for i, actual in enumerate(["bullish", "bullish", "bullish", "bullish", "bearish"]):
        ac = _make_alert_company(db_session, company, "bullish", url_suffix=i)
        _add_sample(db_session, ac, actual, horizon_days=1)

    result = get_win_rate(db_session, company.id)

    assert result is not None
    assert result["1"]["sample_size"] == 5
    assert result["1"]["win_rate"] == 0.8


def test_horizon_below_threshold_omitted_others_included(db_session):
    company = _make_company(db_session)
    for i in range(5):
        ac = _make_alert_company(db_session, company, "bullish", url_suffix=f"h1-{i}")
        _add_sample(db_session, ac, "bullish", horizon_days=1)
    for i in range(2):  # below threshold, horizon 7 should be omitted
        ac = _make_alert_company(db_session, company, "bullish", url_suffix=f"h7-{i}")
        _add_sample(db_session, ac, "bearish", horizon_days=7)

    result = get_win_rate(db_session, company.id)

    assert "1" in result
    assert "7" not in result


def test_excludes_other_companies(db_session):
    company_a = _make_company(db_session, ticker="RELIANCE.NS", name="Reliance")
    company_b = _make_company(db_session, ticker="ONGC.NS", name="ONGC")
    for i in range(5):
        ac = _make_alert_company(db_session, company_b, "bullish", url_suffix=f"b-{i}")
        _add_sample(db_session, ac, "bearish", horizon_days=1)  # all wrong, for company B only

    assert get_win_rate(db_session, company_a.id) is None
