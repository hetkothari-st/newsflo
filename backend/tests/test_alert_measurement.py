from app.market.alert_measurement import compute_alert_measurement
from app.models import Alert, AlertCompany, Article, Company, MarketMove, utcnow


def _company(ticker, sector="oil_gas"):
    return Company(ticker=ticker, name=f"Company {ticker}", sector=sector, index_tier="NIFTY50")


def _article(db_session, url_suffix="a"):
    article = Article(source="test", url=f"https://example.com/{url_suffix}", title="t", content="c")
    db_session.add(article)
    db_session.commit()
    return article


def _alert_company(alert_id, company_id, direction="bullish", impact_level="direct"):
    return AlertCompany(
        alert_id=alert_id, company_id=company_id, direction=direction,
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
        impact_level=impact_level,
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
    assert result["direction"] == "negative"
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


def test_returns_none_when_peak_move_has_no_matching_alert_company(db_session):
    """Regression test for the production crash: alert_measurement.py:109
    used a bare next() with no default to find the AlertCompany matching
    the peak MarketMove's company_id. When alert.companies is empty (or has
    no row for that company_id) -- e.g. an orphaned MarketMove left behind
    by a script that deleted AlertCompany rows without deleting their
    MarketMove rows, see reanalyze_cascade.py -- that raised StopIteration,
    which surfaces inside an async request handler as
    "RuntimeError: coroutine raised StopIteration", a 500 on
    GET /api/feed-v2. 1,049 production alerts have zero companies, so this
    is the common case, not an edge case. A MarketMove with nothing to
    attribute it to is exactly as unusable as no measurement at all -- the
    function must degrade to None the same way `not moves` does above, not
    raise.
    """
    company = _company("A.NS")
    db_session.add(company)
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    # No AlertCompany row is added for this alert at all -- alert.companies
    # is empty, yet a measured MarketMove exists (the orphan shape).
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.8, sector_move_pct=-0.6, excess_move_pct=-4.2,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    assert compute_alert_measurement(db_session, alert) is None


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


def test_intensity_peer_group_spans_same_sector_alerts_today(db_session):
    """Two DIFFERENT alerts, same sector, one measured company each. Before
    the fix, each alert's peer group was only its own moves -- a lone
    company is trivially the max of a group containing only itself, so
    both would degenerate to the same maxed-out excess_score regardless of
    real magnitude. After the fix, the peer group spans every measured
    company in the sector across today's alerts, so the small move and the
    large move are compared against each other and score differently.

    Reviewer-caught confound fix: both alerts' excess_move_pct (2.0 and
    -7.5) are kept on the SAME side of config.BREADTH_MEANINGFUL_MOVE_PCT
    (1.0), i.e. both |excess_move_pct| >= 1.0. breadth_score is
    event-scoped and untouched by this fix, but with the original values
    (0.2 vs -7.5) it straddled the threshold and produced 0 vs 100 on its
    own -- enough by itself to make small_score < big_score true even
    under the OLD, buggy same-event-only peer group (where both alerts'
    excess/volume sub-scores degenerately maxed to 100, so the assertion
    was actually being carried entirely by breadth, not by the peer-group
    fix). Pinning both magnitudes above the threshold makes breadth_score
    100 for both alerts under old and new code alike, so the only thing
    that can make small_score < big_score is the excess/volume
    normalization against the sector-wide peer group -- i.e. the fix
    itself."""
    small_co = _company("SMALLMOVE.NS", sector="metals")
    big_co = _company("BIGMOVE.NS", sector="metals")
    db_session.add_all([small_co, big_co])
    db_session.commit()

    small_article = _article(db_session, url_suffix="small-move")
    small_alert = Alert(article_id=small_article.id, category="metals")
    db_session.add(small_alert)
    db_session.flush()
    db_session.add(_alert_company(small_alert.id, small_co.id))
    db_session.add(MarketMove(
        alert_id=small_alert.id, company_id=small_co.id, benchmark_ticker="^CNXMETAL",
        raw_move_pct=2.3, sector_move_pct=0.3, excess_move_pct=2.0,
        volume=110.0, avg_volume_20d=100.0, volume_multiple=1.1,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    big_article = _article(db_session, url_suffix="big-move")
    big_alert = Alert(article_id=big_article.id, category="metals")
    db_session.add(big_alert)
    db_session.flush()
    db_session.add(_alert_company(big_alert.id, big_co.id))
    db_session.add(MarketMove(
        alert_id=big_alert.id, company_id=big_co.id, benchmark_ticker="^CNXMETAL",
        raw_move_pct=-8.0, sector_move_pct=-0.5, excess_move_pct=-7.5,
        volume=400.0, avg_volume_20d=100.0, volume_multiple=4.0,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    small_result = compute_alert_measurement(db_session, small_alert)
    big_result = compute_alert_measurement(db_session, big_alert)

    assert small_result["intensity"]["score"] < big_result["intensity"]["score"]


def test_result_includes_peak_company_id(db_session):
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
        raw_move_pct=2.0, sector_move_pct=0.5, excess_move_pct=1.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_alert_measurement(db_session, alert)

    assert result["peak_company_id"] == company.id


from app.market.alert_measurement import compute_impact_companies


def test_impact_companies_includes_every_direct_measured_company(db_session):
    a = _company("A.NS")
    b = _company("B.NS")
    db_session.add_all([a, b])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, a.id, direction="bearish"))
    db_session.add(_alert_company(alert.id, b.id, direction="bullish"))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=a.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=-4.2, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=b.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=1.5, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_impact_companies(db_session, alert)

    tickers = [r["ticker"] for r in result]
    assert tickers == ["A.NS", "B.NS"]  # sorted by |excess_move_pct| descending
    assert result[0]["direction"] == "bearish"
    assert result[0]["excess_move_pct"] == -4.2
    assert result[1]["name"] == "Company B.NS"


def test_impact_companies_excludes_indirect_companies(db_session):
    direct = _company("A.NS")
    indirect = _company("B.NS")
    db_session.add_all([direct, indirect])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, direct.id))
    db_session.add(_alert_company(alert.id, indirect.id, impact_level="indirect_l1"))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=direct.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=2.0, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=indirect.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=9.0, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_impact_companies(db_session, alert)

    assert [r["ticker"] for r in result] == ["A.NS"]


def test_impact_companies_excludes_unmeasured_companies(db_session):
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
        excess_move_pct=2.0, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=unmeasured.id, benchmark_ticker="^NSEI",
        measurement_status="no_data", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_impact_companies(db_session, alert)

    assert [r["ticker"] for r in result] == ["A.NS"]


def test_impact_companies_includes_why_when_present(db_session):
    company = _company("A.NS")
    db_session.add(company)
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    ac = _alert_company(alert.id, company.id)
    ac.why = "Higher crude prices lift upstream margins."
    db_session.add(ac)
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=2.0, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_impact_companies(db_session, alert)

    assert result[0]["why"] == "Higher crude prices lift upstream margins."


def test_impact_companies_why_is_none_when_not_populated(db_session):
    company = _company("A.NS")
    db_session.add(company)
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, company.id))  # why left unset -- defaults to None
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=2.0, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_impact_companies(db_session, alert)

    assert result[0]["why"] is None


def test_impact_companies_returns_empty_list_when_none_qualify(db_session):
    company = _company("A.NS")
    db_session.add(company)
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, company.id, impact_level="indirect_l1"))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=2.0, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    assert compute_impact_companies(db_session, alert) == []


def test_impact_companies_include_logo_url(db_session, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "brandfetch_client_id", "test-client-id")

    company = Company(
        ticker="A.NS", name="Company A.NS", sector="oil_gas", index_tier="NIFTY50",
        isin="INE111A11111",
    )
    db_session.add(company)
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, company.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=2.0, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_impact_companies(db_session, alert)

    assert result[0]["logo_url"] == "https://cdn.brandfetch.io/isin/INE111A11111?c=test-client-id"
