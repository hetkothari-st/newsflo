from fastapi.testclient import TestClient

from app.main import app
from app.models import Alert, AlertCompany, Article, Company, MarketMove, utcnow
from app.routers.articles import get_db


def _override_db(db_session):
    def _get_db():
        yield db_session
    app.dependency_overrides[get_db] = _get_db


def _company(ticker, sector="oil_gas", business_desc=None, market_cap=None):
    return Company(
        ticker=ticker, name=f"Company {ticker}", sector=sector, index_tier="NIFTY50",
        business_desc=business_desc, market_cap=market_cap,
    )


def _article(db_session, url="https://example.com/stock-deep-dive"):
    article = Article(source="test", url=url, title="Oil surges", content="c")
    db_session.add(article)
    db_session.commit()
    return article


def _alert_company(alert_id, company_id, direction="bearish"):
    return AlertCompany(
        alert_id=alert_id, company_id=company_id, direction=direction,
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
    )


def test_stock_deep_dive_without_alert_id_returns_company_facts_only(db_session, monkeypatch):
    monkeypatch.setattr("app.routers.stock_deep_dive.fetch_pe_ratio", lambda ticker: None)
    _override_db(db_session)
    company = _company("RELIANCE.NS", business_desc="Refines crude oil.", market_cap=1500000.0)
    db_session.add(company)
    db_session.commit()
    client = TestClient(app)

    response = client.get("/api/feed-v2/stock/RELIANCE.NS")

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "RELIANCE.NS"
    assert body["business_desc"] == "Refines crude oil."
    assert body["market_cap"] == 1500000.0
    assert body["pe"] is None
    assert body["excess_move_pct"] is None
    assert body["intensity"] is None
    assert body["peers"] == []
    app.dependency_overrides.clear()


def test_stock_deep_dive_with_alert_id_returns_measurement_and_peers(db_session, monkeypatch):
    monkeypatch.setattr("app.routers.stock_deep_dive.fetch_pe_ratio", lambda ticker: 22.5)
    _override_db(db_session)
    target = _company("RELIANCE.NS", business_desc="Refines crude oil.")
    peer = _company("PEER.NS")
    db_session.add_all([target, peer])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, target.id))
    db_session.add(_alert_company(alert.id, peer.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=target.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.8, sector_move_pct=-0.6, excess_move_pct=-4.2,
        volume=300.0, avg_volume_20d=100.0, volume_multiple=3.0,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=peer.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=1.0, sector_move_pct=0.2, excess_move_pct=0.8,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    client = TestClient(app)
    response = client.get(f"/api/feed-v2/stock/RELIANCE.NS?alert_id={alert.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["excess_move_pct"] == -4.2
    assert body["pe"] == 22.5
    assert set(body["intensity"].keys()) == {"score", "band", "components"}
    assert len(body["peers"]) == 1
    assert body["peers"][0]["ticker"] == "PEER.NS"
    app.dependency_overrides.clear()


def test_stock_deep_dive_404_when_ticker_not_found(db_session, monkeypatch):
    monkeypatch.setattr("app.routers.stock_deep_dive.fetch_pe_ratio", lambda ticker: None)
    _override_db(db_session)
    client = TestClient(app)

    response = client.get("/api/feed-v2/stock/NOPE.NS")

    assert response.status_code == 404
    app.dependency_overrides.clear()


def test_stock_deep_dive_with_alert_id_but_company_not_in_that_alert_ignores_alert_context(db_session, monkeypatch):
    """The ticker exists and the alert exists, but this company was never
    part of that alert -- degrade to the no-alert-context shape rather
    than erroring or fabricating a measurement."""
    monkeypatch.setattr("app.routers.stock_deep_dive.fetch_pe_ratio", lambda ticker: None)
    _override_db(db_session)
    company = _company("UNRELATED.NS")
    other_company = _company("INALERT.NS")
    db_session.add_all([company, other_company])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, other_company.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=other_company.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=1.0, sector_move_pct=0.2, excess_move_pct=0.8,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    client = TestClient(app)
    response = client.get(f"/api/feed-v2/stock/UNRELATED.NS?alert_id={alert.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["excess_move_pct"] is None
    assert body["peers"] == []
    app.dependency_overrides.clear()


from app.market.cap_tier import compute_cap_tiers


def test_directory_returns_all_companies_with_cap_tier_and_sector(db_session, monkeypatch):
    _override_db(db_session)
    db_session.add_all([
        _company("BIG.NS", sector="oil_gas", market_cap=900000.0),
        _company("SMALL.NS", sector="it", market_cap=500.0),
    ])
    db_session.commit()

    client = TestClient(app)
    response = client.get("/api/feed-v2/directory")

    assert response.status_code == 200
    body = response.json()
    tickers = {row["ticker"] for row in body}
    assert tickers == {"BIG.NS", "SMALL.NS"}
    by_ticker = {row["ticker"]: row for row in body}
    assert by_ticker["BIG.NS"]["sector"] == "oil_gas"
    assert by_ticker["BIG.NS"]["cap_tier"] in ("LARGE", "MID", "SMALL")
    app.dependency_overrides.clear()


def test_directory_filters_by_cap_tier(db_session):
    # Cap tier is rank-based (AMFI_LARGE_CAP_RANK_CUTOFF=100,
    # AMFI_MID_CAP_RANK_CUTOFF=250 -- app/config.py), so ranking TINY.NS into
    # SMALL requires 250+ companies ranked above it, same convention as
    # tests/test_cap_tier.py.
    _override_db(db_session)
    db_session.add_all([
        _company("BIG.NS", sector="oil_gas", market_cap=900000.0),
        *[_company(f"FILLER{i}.NS", sector="other", market_cap=100000.0 - i) for i in range(260)],
        # Below config.MICRO_CAP_FLOOR -> MICRO regardless of rank (spec v2 §4.5).
        _company("TINY.NS", sector="it", market_cap=10.0),
    ])
    db_session.commit()
    client = TestClient(app)

    response = client.get("/api/feed-v2/directory?cap_tier=SMALL")

    assert response.status_code == 200
    body = response.json()
    assert all(row["cap_tier"] == "SMALL" for row in body)
    # TINY.NS is MICRO now (below the market-cap floor), not SMALL.
    assert "TINY.NS" not in {row["ticker"] for row in body}
    assert "BIG.NS" not in {row["ticker"] for row in body}

    micro = client.get("/api/feed-v2/directory?cap_tier=MICRO").json()
    assert {row["ticker"] for row in micro} == {"TINY.NS"}
    app.dependency_overrides.clear()


def test_directory_filters_by_sector(db_session):
    _override_db(db_session)
    db_session.add_all([
        _company("OILCO.NS", sector="oil_gas", market_cap=1000.0),
        _company("ITCO.NS", sector="it", market_cap=1000.0),
    ])
    db_session.commit()
    client = TestClient(app)

    response = client.get("/api/feed-v2/directory?sector=it")

    assert response.status_code == 200
    body = response.json()
    assert {row["ticker"] for row in body} == {"ITCO.NS"}
    app.dependency_overrides.clear()


def test_directory_omits_companies_with_no_market_cap(db_session):
    """cap_tier can't be ranked for a company with no market_cap -- the
    directory omits it rather than showing a fabricated/None cap tier
    (Ground Rules: never fabricate, omit rather than invent)."""
    _override_db(db_session)
    db_session.add(_company("NOCAP.NS", sector="oil_gas", market_cap=None))
    db_session.commit()
    client = TestClient(app)

    response = client.get("/api/feed-v2/directory")

    assert response.status_code == 200
    assert response.json() == []
    app.dependency_overrides.clear()


def test_stock_deep_dive_includes_logo_url(db_session, monkeypatch):
    monkeypatch.setattr("app.routers.stock_deep_dive.fetch_pe_ratio", lambda ticker: None)
    from app.config import settings
    monkeypatch.setattr(settings, "brandfetch_client_id", "test-client-id")
    _override_db(db_session)
    company = Company(
        ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50",
        isin="INE002A01018",
    )
    db_session.add(company)
    db_session.commit()
    client = TestClient(app)

    response = client.get("/api/feed-v2/stock/RELIANCE.NS")

    assert response.status_code == 200
    assert response.json()["logo_url"] == "https://cdn.brandfetch.io/isin/INE002A01018?c=test-client-id"
    app.dependency_overrides.clear()


def test_deep_dive_carries_per_story_reasoning_and_section(db_session):
    # The "why it's under <section>" block below "What they do": causal
    # why + analysis rationale + the card-back section this company
    # renders in for this alert.
    _override_db(db_session)
    company = _company("STORY.NS", sector="oil_gas", market_cap=900000.0)
    db_session.add(company)
    db_session.commit()
    article = Article(source="test", url="https://example.com/story", title="Oil story", content="c")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bearish",
        magnitude_low=1.0, magnitude_high=2.0, basis="direct_mention",
        rationale="Crude costs squeeze its refining margins.",
        why="Higher crude directly raises its biggest input cost.",
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.8, sector_move_pct=-0.6, excess_move_pct=-4.2,
        volume=300.0, avg_volume_20d=100.0, volume_multiple=3.0,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()
    client = TestClient(app)

    body = client.get(f"/api/feed-v2/stock/STORY.NS?alert_id={alert.id}").json()

    assert body["why"] == "Higher crude directly raises its biggest input cost."
    assert body["rationale"] == "Crude costs squeeze its refining margins."
    assert body["section_title"] == "Directly affected"

    # Without alert context there is no story to reason about.
    no_context = client.get("/api/feed-v2/stock/STORY.NS").json()
    assert no_context["why"] is None
    assert no_context["section_title"] is None
    app.dependency_overrides.clear()
