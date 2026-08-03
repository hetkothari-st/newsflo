from datetime import date

from fastapi.testclient import TestClient

from app.main import app
from app.market.cap_tier import resolve_cap_tier
from app.models import Alert, AlertCompany, Article, Company, MarketMove, utcnow
from app.routers.articles import get_db

TODAY = date.today()


def _override_db(db_session):
    def _get_db():
        yield db_session
    app.dependency_overrides[get_db] = _get_db


def _measured_alert(db_session, ticker="RELIANCE.NS", excess=-4.2):
    company = Company(ticker=ticker, name=f"Company {ticker}", sector="oil_gas", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()
    article = Article(source="test", url=f"https://example.com/{ticker}", title="Oil surges", content="c")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_gas", summary_short="Oil supply shock hits refiners")
    db_session.add(alert)
    db_session.flush()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bearish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.8, sector_move_pct=-0.6, excess_move_pct=excess,
        volume=300.0, avg_volume_20d=100.0, volume_multiple=3.0,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()
    return alert


def _unmeasured_alert(db_session):
    company = Company(ticker="NODATA.NS", name="No Data Co", sector="other", index_tier="OTHER")
    db_session.add(company)
    db_session.commit()
    article = Article(source="test", url="https://example.com/nodata", title="Untradeable news", content="c")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="other")
    db_session.add(alert)
    db_session.flush()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^NSEI",
        measurement_status="no_data", measured_at=utcnow(),
    ))
    db_session.commit()
    return alert


def _multi_company_alert(db_session):
    a = Company(ticker="A.NS", name="Company A", sector="oil_gas", index_tier="NIFTY50")
    b = Company(ticker="B.NS", name="Company B", sector="oil_gas", index_tier="NIFTY50")
    db_session.add_all([a, b])
    db_session.commit()
    article = Article(source="test", url="https://example.com/multi", title="Oil news", content="c")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=a.id, direction="bearish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
        impact_level="direct", why="Crude spike raises input costs.",
    ))
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=b.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
        impact_level="direct",
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=a.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=-4.2, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=b.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=1.1, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()
    return alert


def test_list_feed_v2_returns_only_measured_alerts(db_session):
    _override_db(db_session)
    measured = _measured_alert(db_session)
    _unmeasured_alert(db_session)
    client = TestClient(app)

    response = client.get("/api/feed-v2")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == measured.id
    assert body[0]["excess_move_pct"] == -4.2
    assert body[0]["summary_short"] == "Oil supply shock hits refiners"
    assert body[0]["peak_ticker"] == "RELIANCE.NS"
    assert body[0]["article"]["title"] == "Oil surges"
    app.dependency_overrides.clear()


def test_peak_cap_tier_excludes_global_companies_from_the_ranking_pool(db_session):
    """The card feed's peak_cap_tier (GET /api/feed-v2) must not let GLOBAL
    companies shift Indian ranks. Before this fix, feed_v2's own cap-tier
    query had no ``market == 'INDIA'`` filter, so 10 GLOBAL megacaps could
    push an Indian peak sitting right at rank 100 out of LARGE into MID
    here, while the single-company /stock/{ticker} endpoint (already
    India-filtered) still called it LARGE -- same company, two tiers, two
    screens."""
    _override_db(db_session)
    peak = Company(
        ticker="PEAK.NS", name="Peak Co", sector="oil_gas", index_tier="OTHER",
        market_cap=1000.0, market_cap_as_of=TODAY,
    )
    # 99 more Indian companies ranked above PEAK.NS so it sits exactly at
    # rank 100 -- the LARGE/MID boundary a GLOBAL company bumping everyone
    # down by even one slot would flip to MID.
    fillers = [
        Company(
            ticker=f"F{i}.NS", name=f"Filler {i}", sector="other", index_tier="OTHER",
            market_cap=100000.0 - i, market_cap_as_of=TODAY,
        )
        for i in range(99)
    ]
    global_megacaps = [
        Company(
            ticker=f"GLOB{i}", name=f"Global {i}", sector="it", index_tier="GLOBAL_LARGE_CAP",
            market="GLOBAL", market_cap=10_000_000.0 + i, market_cap_as_of=TODAY,
        )
        for i in range(10)
    ]
    db_session.add_all([peak, *fillers, *global_megacaps])
    db_session.commit()
    article = Article(source="test", url="https://example.com/peak", title="Peak news", content="c")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=peak.id, direction="bearish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=peak.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.8, sector_move_pct=-0.6, excess_move_pct=-4.2,
        volume=300.0, avg_volume_20d=100.0, volume_multiple=3.0,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()
    client = TestClient(app)

    body = client.get("/api/feed-v2").json()

    assert body[0]["peak_cap_tier"] == "LARGE"
    # Same company, single-lookup path (as used by /stock/{ticker}) --
    # must agree with the batch path above.
    assert resolve_cap_tier(db_session, peak, today=TODAY).tier == "LARGE"
    app.dependency_overrides.clear()


def test_get_feed_v2_alert_by_id(db_session):
    _override_db(db_session)
    alert = _measured_alert(db_session)
    client = TestClient(app)

    response = client.get(f"/api/feed-v2/{alert.id}")

    assert response.status_code == 200
    assert response.json()["id"] == alert.id
    app.dependency_overrides.clear()


def test_get_feed_v2_alert_404_when_not_found(db_session):
    _override_db(db_session)
    client = TestClient(app)

    response = client.get("/api/feed-v2/999999")

    assert response.status_code == 404
    app.dependency_overrides.clear()


def test_get_feed_v2_alert_404_when_unmeasured(db_session):
    _override_db(db_session)
    alert = _unmeasured_alert(db_session)
    client = TestClient(app)

    response = client.get(f"/api/feed-v2/{alert.id}")

    assert response.status_code == 404
    app.dependency_overrides.clear()


def test_get_feed_v2_alert_includes_layers_and_timeline(db_session):
    _override_db(db_session)
    # Single-company alert: the card back still shows the complete
    # who's-affected view (spec v2 §2) -- one "Directly affected" layer
    # containing the peak itself.
    alert = _measured_alert(db_session)
    client = TestClient(app)

    response = client.get(f"/api/feed-v2/{alert.id}")

    assert response.status_code == 200
    body = response.json()
    assert len(body["layers"]) == 1
    assert body["layers"][0]["relationship"] == "DIRECT"
    assert len(body["layers"][0]["rows"]) == 1
    assert body["timeline"] == []
    app.dependency_overrides.clear()


def test_list_feed_v2_does_not_include_layers_or_timeline(db_session):
    _override_db(db_session)
    _measured_alert(db_session)
    client = TestClient(app)

    response = client.get("/api/feed-v2")

    assert response.status_code == 200
    body = response.json()
    assert "layers" not in body[0]
    assert "timeline" not in body[0]
    app.dependency_overrides.clear()


def test_get_feed_v2_alert_layers_carry_both_direct_companies(db_session):
    _override_db(db_session)
    alert = _multi_company_alert(db_session)
    client = TestClient(app)

    response = client.get(f"/api/feed-v2/{alert.id}")

    assert response.status_code == 200
    body = response.json()
    direct = next(l for l in body["layers"] if l["relationship"] == "DIRECT")
    assert len(direct["rows"]) == 2
    rows_by_ticker = {r["ticker"]: r for r in direct["rows"]}
    assert rows_by_ticker["A.NS"]["why"] == "Crude spike raises input costs."
    assert rows_by_ticker["B.NS"]["why"] is None
    app.dependency_overrides.clear()


def test_get_feed_v2_alert_includes_article_image_url(db_session):
    _override_db(db_session)
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()
    article = Article(
        source="test", url="https://example.com/img", title="Oil surges", content="c",
        image_url="https://example.com/photo.jpg",
    )
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bearish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=-4.2, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()
    client = TestClient(app)

    response = client.get(f"/api/feed-v2/{alert.id}")

    assert response.status_code == 200
    assert response.json()["article"]["image_url"] == "https://example.com/photo.jpg"
    app.dependency_overrides.clear()


def test_list_feed_v2_includes_article_image_url_null_when_absent(db_session):
    _override_db(db_session)
    _measured_alert(db_session)  # no image_url set -- Article defaults to None
    client = TestClient(app)

    response = client.get("/api/feed-v2")

    assert response.status_code == 200
    assert response.json()[0]["article"]["image_url"] is None
    app.dependency_overrides.clear()


def test_list_feed_v2_date_param_reopens_a_previous_day(db_session):
    from datetime import timedelta

    from app.ist_time import to_ist_date
    from app.models import utcnow

    _override_db(db_session)
    alert = _measured_alert(db_session)
    # Move the alert two days back -- today's feed must be empty, the
    # calendar date's feed must contain it (spec: calendar mechanism).
    alert.created_at = utcnow() - timedelta(days=2)
    db_session.commit()
    past_day = to_ist_date(alert.created_at).isoformat()
    client = TestClient(app)

    assert client.get("/api/feed-v2").json() == []
    body = client.get(f"/api/feed-v2?date={past_day}").json()
    assert [a["id"] for a in body] == [alert.id]
    assert client.get("/api/feed-v2?date=not-a-date").status_code == 400
    app.dependency_overrides.clear()


def test_list_feed_v2_serves_translations_for_lang(db_session):
    from app.models import AlertTranslation, ArticleTranslation, CategoryTranslation

    _override_db(db_session)
    alert = _measured_alert(db_session)
    db_session.add(ArticleTranslation(
        article_id=alert.article_id, lang="hi", title="हिंदी शीर्षक", content="",
    ))
    db_session.add(AlertTranslation(
        alert_id=alert.id, lang="hi", summary_short="हिंदी सार", summary_long="हिंदी विस्तार",
    ))
    db_session.add(CategoryTranslation(category="oil_gas", lang="hi", label="तेल और गैस"))
    db_session.commit()
    client = TestClient(app)

    english = client.get("/api/feed-v2").json()[0]
    assert english["article"]["title"] == "Oil surges"
    assert english["category_label"] is None  # frontend prettifies the slug

    hindi = client.get("/api/feed-v2?lang=hi").json()[0]
    assert hindi["article"]["title"] == "हिंदी शीर्षक"
    assert hindi["summary_short"] == "हिंदी सार"
    assert hindi["category_label"] == "तेल और गैस"
    app.dependency_overrides.clear()
