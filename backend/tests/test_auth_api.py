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
