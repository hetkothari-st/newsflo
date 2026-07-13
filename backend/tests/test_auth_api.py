from fastapi.testclient import TestClient

from app.auth.tokens import decode_access_token
from app.main import app
from app.routers.articles import get_db


def _client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(app)


def test_register_returns_token(db_session):
    client = _client(db_session)
    response = client.post("/api/auth/register", json={"email": "new@example.com", "password": "pw12345"})

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert decode_access_token(body["access_token"]) is not None

    app.dependency_overrides.clear()


def test_register_rejects_duplicate_email(db_session):
    client = _client(db_session)
    client.post("/api/auth/register", json={"email": "dup@example.com", "password": "pw12345"})
    response = client.post("/api/auth/register", json={"email": "dup@example.com", "password": "other"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Email already registered"

    app.dependency_overrides.clear()


def test_login_succeeds_with_correct_password(db_session):
    client = _client(db_session)
    client.post("/api/auth/register", json={"email": "log@example.com", "password": "pw12345"})
    response = client.post("/api/auth/login", json={"email": "log@example.com", "password": "pw12345"})

    assert response.status_code == 200
    assert decode_access_token(response.json()["access_token"]) is not None

    app.dependency_overrides.clear()


def test_login_fails_with_wrong_password(db_session):
    client = _client(db_session)
    client.post("/api/auth/register", json={"email": "log2@example.com", "password": "pw12345"})
    response = client.post("/api/auth/login", json={"email": "log2@example.com", "password": "WRONG"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"

    app.dependency_overrides.clear()


def test_login_fails_for_unknown_email(db_session):
    client = _client(db_session)
    response = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "pw12345"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"

    app.dependency_overrides.clear()


def test_register_rejects_password_over_72_bytes(db_session):
    client = _client(db_session)
    response = client.post(
        "/api/auth/register", json={"email": "toolong@example.com", "password": "x" * 73}
    )

    assert response.status_code == 422

    app.dependency_overrides.clear()


def test_register_rejects_empty_password(db_session):
    client = _client(db_session)
    response = client.post("/api/auth/register", json={"email": "empty@example.com", "password": ""})

    assert response.status_code == 422

    app.dependency_overrides.clear()


def test_register_rejects_malformed_email(db_session):
    client = _client(db_session)
    response = client.post(
        "/api/auth/register", json={"email": "not-an-email", "password": "pw12345"}
    )

    assert response.status_code == 422

    app.dependency_overrides.clear()


def test_get_me_returns_profile(db_session):
    client = _client(db_session)
    reg = client.post("/api/auth/register", json={"email": "me@example.com", "password": "pw12345"})
    token = reg.json()["access_token"]

    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "me@example.com"
    assert body["email_alerts_enabled"] is True
    assert "created_at" in body

    app.dependency_overrides.clear()


def test_get_me_requires_auth(db_session):
    client = _client(db_session)
    response = client.get("/api/auth/me")
    assert response.status_code in (401, 403)
    app.dependency_overrides.clear()


def test_patch_me_updates_email_alerts_enabled(db_session):
    client = _client(db_session)
    reg = client.post("/api/auth/register", json={"email": "toggle@example.com", "password": "pw12345"})
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = client.patch("/api/auth/me", json={"email_alerts_enabled": False}, headers=headers)

    assert response.status_code == 200
    assert response.json()["email_alerts_enabled"] is False

    refetch = client.get("/api/auth/me", headers=headers)
    assert refetch.json()["email_alerts_enabled"] is False

    app.dependency_overrides.clear()


def test_change_password_succeeds_and_new_password_logs_in(db_session):
    client = _client(db_session)
    reg = client.post("/api/auth/register", json={"email": "pwchange@example.com", "password": "oldpass1"})
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/api/auth/me/password",
        json={"current_password": "oldpass1", "new_password": "newpass2"},
        headers=headers,
    )
    assert response.status_code == 204

    old_login = client.post("/api/auth/login", json={"email": "pwchange@example.com", "password": "oldpass1"})
    assert old_login.status_code == 401

    new_login = client.post("/api/auth/login", json={"email": "pwchange@example.com", "password": "newpass2"})
    assert new_login.status_code == 200

    app.dependency_overrides.clear()


def test_change_password_rejects_wrong_current_password(db_session):
    client = _client(db_session)
    reg = client.post("/api/auth/register", json={"email": "pwwrong@example.com", "password": "rightpass"})
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/api/auth/me/password",
        json={"current_password": "WRONG", "new_password": "newpass2"},
        headers=headers,
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Current password is incorrect"

    app.dependency_overrides.clear()


def test_delete_me_removes_user_and_cascades(db_session):
    from app.models import Company, EmailNotification, Holding, User, UserWatchlistCategory, UserWatchlistCompany

    client = _client(db_session)
    reg = client.post("/api/auth/register", json={"email": "delete@example.com", "password": "deleteme1"})
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    user_id = decode_access_token(token)

    company = Company(ticker="DEL.NS", name="DelCo", sector="it", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()
    db_session.add(Holding(user_id=user_id, company_id=company.id, quantity=1.0))
    db_session.add(UserWatchlistCategory(user_id=user_id, category="banking"))
    db_session.add(UserWatchlistCompany(user_id=user_id, company_id=company.id))
    db_session.commit()

    response = client.request(
        "DELETE", "/api/auth/me", json={"password": "deleteme1"}, headers=headers
    )
    assert response.status_code == 204

    assert db_session.query(User).filter_by(id=user_id).one_or_none() is None
    assert db_session.query(Holding).filter_by(user_id=user_id).count() == 0
    assert db_session.query(UserWatchlistCategory).filter_by(user_id=user_id).count() == 0
    assert db_session.query(UserWatchlistCompany).filter_by(user_id=user_id).count() == 0

    app.dependency_overrides.clear()


def test_delete_me_rejects_wrong_password(db_session):
    client = _client(db_session)
    reg = client.post("/api/auth/register", json={"email": "delwrong@example.com", "password": "rightpass"})
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = client.request(
        "DELETE", "/api/auth/me", json={"password": "WRONG"}, headers=headers
    )
    assert response.status_code == 401

    login = client.post("/api/auth/login", json={"email": "delwrong@example.com", "password": "rightpass"})
    assert login.status_code == 200  # user was NOT deleted

    app.dependency_overrides.clear()
