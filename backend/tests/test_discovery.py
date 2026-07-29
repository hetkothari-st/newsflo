from fastapi.testclient import TestClient

from app.main import app
from app.models import Alert, AlertCompany, Article, Company, Holding, MarketMove, User, utcnow
from app.routers.articles import get_db


def _override_db(db_session):
    def _get_db():
        yield db_session
    app.dependency_overrides[get_db] = _get_db


def _seed_today(db_session):
    """One large parent + one micro child (linked via parent_company_id),
    both measured today. Micro child has high materiality + abnormal
    volume + low delivery -- qualifies for every discovery tab."""
    parent = Company(ticker="BIG.NS", name="Big Co", sector="oil_gas", index_tier="NIFTY50", market_cap=900000.0)
    child = Company(ticker="TINY.NS", name="Tiny Co", sector="oil_gas", index_tier="OTHER", market_cap=400.0)
    db_session.add_all([parent, child])
    db_session.commit()
    article = Article(source="test", url="https://example.com/disc", title="Oil news", content="c")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_gas", summary_short="Crude falls sharply")
    db_session.add(alert)
    db_session.flush()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=parent.id, direction="bearish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
        impact_level="direct", why="Crude fall cuts realisations.",
    ))
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=child.id, direction="bullish",
        magnitude_low=0.5, magnitude_high=1.5, rationale="r", basis="direct_mention",
        impact_level="indirect_l1", parent_company_id=parent.id,
        why="Cheaper crude lifts refining margins.",
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=parent.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-2.4, sector_move_pct=0.0, excess_move_pct=-2.4,
        volume=260.0, avg_volume_20d=100.0, volume_multiple=2.6,
        materiality=0.001, avg_traded_value=900_000_000.0,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=child.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=4.7, sector_move_pct=0.0, excess_move_pct=4.7,
        volume=410.0, avg_volume_20d=100.0, volume_multiple=4.1,
        delivery_pct=38.0, materiality=0.09, avg_traded_value=20_000_000.0,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()
    return parent, child, alert


def test_materiality_tab_ranks_by_news_size_vs_company_size(db_session):
    _override_db(db_session)
    _seed_today(db_session)
    client = TestClient(app)

    response = client.get("/api/feed-v2/discovery/materiality")

    assert response.status_code == 200
    body = response.json()
    # Micro cap's 0.09 materiality outranks the giant's 0.001 -- the
    # ranking floats the small name, not the headline one (spec §6).
    assert body[0]["ticker"] == "TINY.NS"
    assert body[0]["cap_tier"] == "MICRO"
    assert body[0]["low_delivery"] is True
    assert body[0]["thin_trading"] is True
    app.dependency_overrides.clear()


def test_unusual_tab_only_lists_small_micro_with_abnormal_volume(db_session):
    _override_db(db_session)
    _seed_today(db_session)
    client = TestClient(app)

    response = client.get("/api/feed-v2/discovery/unusual")

    assert response.status_code == 200
    body = response.json()
    assert [row["ticker"] for row in body] == ["TINY.NS"]  # BIG.NS is LARGE -> excluded
    app.dependency_overrides.clear()


def test_holdings_tab_is_empty_for_anonymous_users(db_session):
    _override_db(db_session)
    _seed_today(db_session)
    client = TestClient(app)

    response = client.get("/api/feed-v2/discovery/holdings")

    assert response.status_code == 200
    assert response.json() == []
    app.dependency_overrides.clear()


def test_holdings_tab_surfaces_children_of_held_companies(db_session):
    _override_db(db_session)
    parent, child, alert = _seed_today(db_session)
    user = User(email="u@example.com", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    db_session.add(Holding(user_id=user.id, company_id=parent.id, quantity=10))
    db_session.commit()

    from app.auth.dependencies import get_current_user_optional
    app.dependency_overrides[get_current_user_optional] = lambda: user
    client = TestClient(app)

    response = client.get("/api/feed-v2/discovery/holdings")

    assert response.status_code == 200
    body = response.json()
    assert [row["ticker"] for row in body] == ["TINY.NS"]
    assert body[0]["via_ticker"] == "BIG.NS"
    app.dependency_overrides.clear()


def test_unknown_tab_404s(db_session):
    _override_db(db_session)
    client = TestClient(app)
    assert client.get("/api/feed-v2/discovery/nope").status_code == 404
    app.dependency_overrides.clear()


def test_portfolio_overlay_marks_affected_holdings(db_session):
    _override_db(db_session)
    parent, child, alert = _seed_today(db_session)
    quiet = Company(ticker="QUIET.NS", name="Quiet Co", sector="it", index_tier="NIFTY50", market_cap=100000.0)
    db_session.add(quiet)
    db_session.flush()
    user = User(email="p@example.com", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    db_session.add_all([
        Holding(user_id=user.id, company_id=parent.id, quantity=40),
        Holding(user_id=user.id, company_id=quiet.id, quantity=75),
    ])
    db_session.commit()

    from app.auth.dependencies import get_current_user
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)

    response = client.get("/api/feed-v2/portfolio")

    assert response.status_code == 200
    body = response.json()
    assert body["affected_count"] == 1
    by_ticker = {row["ticker"]: row for row in body["holdings"]}
    assert by_ticker["BIG.NS"]["affected_alert_id"] == alert.id
    assert by_ticker["BIG.NS"]["affected_headline"] == "Crude falls sharply"
    assert by_ticker["QUIET.NS"]["affected_alert_id"] is None
    app.dependency_overrides.clear()
