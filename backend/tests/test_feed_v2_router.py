from fastapi.testclient import TestClient

from app.main import app
from app.models import Alert, AlertCompany, Article, Company, MarketMove, utcnow
from app.routers.articles import get_db


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


def test_get_feed_v2_alert_includes_ripple_and_timeline(db_session):
    _override_db(db_session)
    alert = _measured_alert(db_session)  # single-company alert -- peak only, no ripple companions
    client = TestClient(app)

    response = client.get(f"/api/feed-v2/{alert.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["ripple"] == []
    assert body["timeline"] == []
    app.dependency_overrides.clear()


def test_list_feed_v2_does_not_include_ripple_or_timeline(db_session):
    _override_db(db_session)
    _measured_alert(db_session)
    client = TestClient(app)

    response = client.get("/api/feed-v2")

    assert response.status_code == 200
    body = response.json()
    assert "ripple" not in body[0]
    assert "timeline" not in body[0]
    app.dependency_overrides.clear()
