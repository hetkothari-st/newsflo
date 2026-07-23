from datetime import timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.models import Alert, AlertCompany, Article, CarOutcome, Company, User, utcnow
from app.routers.articles import get_db
from app.auth.tokens import create_access_token


def _override_db(db_session):
    def _get_db():
        yield db_session
    app.dependency_overrides[get_db] = _get_db


def _auth_headers(db_session):
    user = User(email="reviewer@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    token = create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


def _seed_outcome(db_session, ticker, category, day0_excess, car_pct, url_suffix):
    company = Company(ticker=ticker, name=f"Company {ticker}", sector=category, index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()
    article = Article(source="test", url=f"https://example.com/{url_suffix}", title=f"{ticker} news", content="c")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category=category, created_at=utcnow() - timedelta(days=10))
    db_session.add(alert)
    db_session.flush()
    ac = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bearish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
    )
    db_session.add(ac)
    db_session.flush()
    db_session.add(CarOutcome(
        alert_company_id=ac.id, company_id=company.id, category=category,
        day0_excess_move_pct=day0_excess, car_pct=car_pct,
    ))
    db_session.commit()
    return alert, company


def test_car_review_requires_auth(db_session):
    _override_db(db_session)
    client = TestClient(app)

    response = client.get("/api/car-review")

    # HTTPBearer(auto_error=True) returns 403 for a missing header; a present-but-
    # invalid token returns our explicit 401 (same convention as
    # test_auth_dependencies.py / test_holdings_api.py). Either counts as "rejected".
    assert response.status_code in (401, 403)
    app.dependency_overrides.clear()


def test_car_review_lists_outcomes_with_derived_label(db_session):
    _override_db(db_session)
    headers = _auth_headers(db_session)
    _seed_outcome(db_session, "A.NS", "oil_gas", day0_excess=-4.2, car_pct=-3.0, url_suffix="a")
    client = TestClient(app)

    response = client.get("/api/car-review", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["ticker"] == "A.NS"
    assert body[0]["day0_excess_move_pct"] == -4.2
    assert body[0]["car_pct"] == -3.0
    assert body[0]["outcome_label"] == "HELD"
    app.dependency_overrides.clear()


def test_car_review_summary_requires_auth(db_session):
    _override_db(db_session)
    client = TestClient(app)

    response = client.get("/api/car-review/summary")

    # See test_car_review_requires_auth for why both codes are accepted.
    assert response.status_code in (401, 403)
    app.dependency_overrides.clear()


def test_car_review_summary_is_none_below_threshold(db_session):
    _override_db(db_session)
    headers = _auth_headers(db_session)
    _seed_outcome(db_session, "A.NS", "oil_gas", day0_excess=-4.2, car_pct=-3.0, url_suffix="a")
    client = TestClient(app)

    response = client.get("/api/car-review/summary", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["sample_count"] == 1
    assert body["hold_rate"] is None
    assert body["mean_car_pct"] is None
    app.dependency_overrides.clear()


def test_car_review_summary_populated_at_threshold(db_session):
    _override_db(db_session)
    headers = _auth_headers(db_session)
    for i in range(5):
        _seed_outcome(db_session, f"A{i}.NS", "oil_gas", day0_excess=-4.2, car_pct=-3.0, url_suffix=f"a{i}")
    client = TestClient(app)

    response = client.get("/api/car-review/summary", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["sample_count"] == 5
    assert body["hold_rate"] == 1.0
    assert body["mean_car_pct"] == -3.0
    assert len(body["by_category"]) == 1
    assert body["by_category"][0]["category"] == "oil_gas"
    app.dependency_overrides.clear()
