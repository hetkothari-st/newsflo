import pytest

from app.auth.security import hash_password, verify_password
from app.models import User


def test_hash_password_is_not_plaintext():
    hashed = hash_password("s3cret-pw")
    assert hashed != "s3cret-pw"
    assert hashed.startswith("$2")  # bcrypt hash prefix


def test_verify_password_accepts_correct_and_rejects_wrong():
    hashed = hash_password("s3cret-pw")
    assert verify_password("s3cret-pw", hashed) is True
    assert verify_password("wrong-pw", hashed) is False


def test_create_user(db_session):
    user = User(email="a@example.com", hashed_password="hash")
    db_session.add(user)
    db_session.commit()

    fetched = db_session.query(User).filter_by(email="a@example.com").one()
    assert fetched.id is not None
    assert fetched.created_at is not None


def test_user_email_is_unique(db_session):
    db_session.add(User(email="dup@example.com", hashed_password="h1"))
    db_session.commit()

    db_session.add(User(email="dup@example.com", hashed_password="h2"))
    with pytest.raises(Exception):
        db_session.commit()
