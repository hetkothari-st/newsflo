from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user, get_current_user_optional
from app.auth.tokens import create_access_token
from app.models import User
from app.routers.articles import get_db


def _build_client(db_session):
    test_app = FastAPI()

    @test_app.get("/protected")
    def protected(user: User = Depends(get_current_user)):
        return {"email": user.email}

    @test_app.get("/maybe")
    def maybe(user: User | None = Depends(get_current_user_optional)):
        return {"email": user.email if user else None}

    test_app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(test_app)


def _make_user(db_session):
    user = User(email="dep@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    return user


def test_get_current_user_returns_user_for_valid_token(db_session):
    user = _make_user(db_session)
    client = _build_client(db_session)
    token = create_access_token(user.id)

    response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["email"] == "dep@example.com"


def test_get_current_user_rejects_missing_token(db_session):
    _make_user(db_session)
    client = _build_client(db_session)

    response = client.get("/protected")

    # HTTPBearer(auto_error=True) returns 403 for a missing header; a present-but-
    # invalid token returns our explicit 401. Either counts as "rejected".
    assert response.status_code in (401, 403)


def test_get_current_user_401s_for_invalid_token(db_session):
    _make_user(db_session)
    client = _build_client(db_session)

    response = client.get("/protected", headers={"Authorization": "Bearer garbage"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired token"


def test_get_current_user_optional_returns_none_without_token(db_session):
    client = _build_client(db_session)

    response = client.get("/maybe")

    assert response.status_code == 200
    assert response.json()["email"] is None


def test_get_current_user_optional_returns_user_with_token(db_session):
    user = _make_user(db_session)
    client = _build_client(db_session)
    token = create_access_token(user.id)

    response = client.get("/maybe", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["email"] == "dep@example.com"
