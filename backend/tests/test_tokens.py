from datetime import datetime, timedelta, timezone

import jwt

from app.auth.tokens import ALGORITHM, create_access_token, decode_access_token
from app.config import settings


def test_create_and_decode_round_trip():
    token = create_access_token(42)
    assert decode_access_token(token) == 42


def test_decode_rejects_garbage_token():
    assert decode_access_token("not-a-real-token") is None


def test_decode_rejects_expired_token():
    expired = jwt.encode(
        {"sub": "7", "exp": datetime.now(timezone.utc) - timedelta(hours=1)},
        settings.jwt_secret_key,
        algorithm=ALGORITHM,
    )
    assert decode_access_token(expired) is None


def test_decode_rejects_token_signed_with_wrong_secret():
    forged = jwt.encode(
        {"sub": "7", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        "some-other-secret",
        algorithm=ALGORITHM,
    )
    assert decode_access_token(forged) is None
