# NewsFlo Auth, Holdings & Email Alerting Implementation Plan (Plan 3 of 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make NewsFlo a multi-tenant product: add email/password auth with JWT sessions, per-user demat holdings (manual entry + CSV upload), and email alerting that matches every newly resolved alert against each user's holdings and sends them an email (via a console/log backend by default). This is spec modules #6 "Holdings" and #7 "Alerting", plus the "Auth" bullet under Tech Stack. No CRED-style React UI (Plan 4), no real broker integration, no real email-provider integration.

**Architecture:** Extends the Plan 1/Plan 2 modular monolith. Adds three new packages — `app.auth` (password hashing, JWT tokens, FastAPI dependencies), `app.holdings` (CSV loader), and `app.alerting` (email client, holdings matcher, sender) — plus two new routers (`app.routers.auth`, `app.routers.holdings`) and three new SQLAlchemy models (`User`, `Holding`, `EmailNotification`). The existing `process_new_articles` pipeline gains a match-and-send step after each alert is committed. No Alembic — SQLAlchemy `create_all` handles the new tables in tests, as in Plans 1 and 2.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, Pydantic v2, `bcrypt` (password hashing, called directly), `PyJWT` (HS256 JWT), `python-multipart` (FastAPI form/upload support), `pytest` + `httpx` (testing). Email sending goes through a pluggable client defaulting to a console/log backend.

## Global Constraints

- Database schema must stay portable between SQLite (tests) and PostgreSQL (production) — no native Postgres-only column types (no `ENUM`, no `ARRAY`); enums are plain `String` columns validated in Python.
- No live network calls in any test — news fetching, Claude API calls, price lookups (yfinance), and now email sending are always mocked/monkeypatched or routed through the console backend. Never any real HTTP call to Resend/SendGrid; the console email backend is what every test exercises by default (no `RESEND_API_KEY` set in the test environment).
- News sources for v1 are free RSS/APIs only (per spec) — no paid data sources.
- Market focus is Indian stocks (NSE/BSE) for v1 — tickers use `.NS` suffix.
- Claude structured output must go through forced tool-use (a `record_analysis` tool), never free-text JSON parsing.
- Company sector values are constrained to a fixed taxonomy (`oil_gas`, `banking`, `auto`, `it`, `pharma`, `fmcg`, `metals`, `telecom`, `infra`, `other`) so sector-based company resolution is an exact match, not fuzzy text matching.
- Frontend for this plan is still the single static HTML/JS page (no React/build step) — the full CRED-style UI is Plan 4. This plan builds the *backend* groundwork (e.g. the `in_my_holdings` flag) for Plan 4's "My Demat" tab, not the tab UI.
- The outcome-tracker scheduler must never start automatically during tests or default `uvicorn app.main:app` runs — it is strictly opt-in via `ENABLE_SCHEDULER=true` (unchanged from Plan 2).
- Calibration blending uses **population** standard deviation (`statistics.pstdev`) (unchanged from Plan 2).
- Passwords are never stored or logged in plaintext — only `bcrypt` hashes are persisted; never log a raw password anywhere, including in test assertions' failure messages (do not `print`/`assert` raw passwords).
- The JWT secret key comes from `Settings.jwt_secret_key` (env `JWT_SECRET_KEY`), never hardcoded inline in a route handler — the insecure default is confined to `config.py` and clearly commented as unsafe for production.
- No live broker API integration in this plan — holdings are manual entry / CSV upload only.
- One commit per task, at the end of that task's steps.

## Deviations from spec (documented for later reviewers)

These are deliberate v1 scope decisions, not oversights:

- **Auth is email/password only.** The spec lists "email/password or OAuth, JWT sessions". OAuth is out of scope here — no OAuth provider credentials exist to build/test against. JWT sessions and multi-tenancy are implemented in full.
- **Holdings support manual entry + CSV upload only.** The spec names Zerodha Kite Connect as the "first integration" but *also* mandates that "manual entry is always available as a fallback path, not replaced by the API integration." That fallback path is exactly what this plan builds. The broker integration is deferred future work — no real broker credentials exist to build/test against.
- **Email sending uses a pluggable client defaulting to a console/log backend.** When no real provider key is configured (`RESEND_API_KEY` empty, the default/dev case), `send_email` logs the message and returns `True` — it never fails and never needs an API key, so the whole system runs end-to-end without a real Resend/SendGrid account. A real HTTP-calling backend is left as a loud `NotImplementedError` stub (no real key available to test it against), mirroring how Plan 1 treated `ANTHROPIC_API_KEY` as optional-at-dev-time.
- **Password hashing uses the `bcrypt` package directly** (`bcrypt.hashpw`/`bcrypt.checkpw`), not `passlib`, to avoid passlib's known bcrypt-backend version friction on modern Python.
- **JWT uses `PyJWT`** (not `python-jose`) — simpler, fewer transitive deps. Algorithm HS256.
- **Auth extraction uses `fastapi.security.HTTPBearer`** (a plain `Authorization: Bearer <token>` header), not `OAuth2PasswordBearer` — login/register are plain JSON POST bodies, not an OAuth2 form flow.

---

## Task 1: User Model & Password Hashing

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/app/models.py`
- Create: `backend/app/auth/__init__.py`
- Create: `backend/app/auth/security.py`
- Test: `backend/tests/test_auth_security.py`

**Interfaces:**
- Consumes: `Base` (`app.db`), `utcnow` helper (`app.models`, Plan 1).
- Produces: `User` model (`app.models`) with columns `id`, `email` (unique, not null), `hashed_password` (not null), `created_at`; and `hash_password(password: str) -> str` / `verify_password(password: str, hashed: str) -> bool` (`app.auth.security`). Tasks 2, 3, 4, 5, 7, 9, 10, 11 all rely on `User` and the hashing functions.

- [ ] **Step 1: Add the bcrypt dependency**

Replace the entire contents of `backend/requirements.txt` with:

```
fastapi
uvicorn
sqlalchemy
pydantic
pydantic-settings
anthropic
feedparser
httpx
pytest
yfinance
pandas
apscheduler
bcrypt
```

Install into the existing venv:

```bash
cd backend
.venv/Scripts/pip install -r requirements.txt
```

- [ ] **Step 2: Write the failing test**

`backend/tests/test_auth_security.py`:

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_auth_security.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.auth'` (or `ImportError` on `User`).

- [ ] **Step 4: Implement the User model and hashing**

Append the following `User` class to the end of `backend/app/models.py` (after the existing `CalibrationSample` class — do not modify the existing classes):

```python
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, nullable=False, unique=True)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
```

`backend/app/auth/__init__.py`: empty file.

`backend/app/auth/security.py`:

```python
import bcrypt


def hash_password(password: str) -> str:
    """Return a bcrypt hash of ``password``. Only the hash is ever persisted —
    the raw password is never stored or logged."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Return True iff ``password`` matches the stored bcrypt ``hashed`` value."""
    return bcrypt.checkpw(password.encode(), hashed.encode())
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest tests/test_auth_security.py -v`
Expected: `4 passed`

- [ ] **Step 6: Run the full suite to confirm no regressions**

Run: `cd backend && .venv/Scripts/pytest tests/ -v`
Expected: all previously-passing tests still pass, plus the 4 new ones.

- [ ] **Step 7: Commit**

```bash
git add backend/requirements.txt backend/app/models.py backend/app/auth/__init__.py backend/app/auth/security.py backend/tests/test_auth_security.py
git commit -m "feat: add User model and bcrypt password hashing"
```

---

## Task 2: JWT Tokens & Auth Dependencies

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/app/config.py`
- Create: `backend/app/auth/tokens.py`
- Create: `backend/app/auth/dependencies.py`
- Test: `backend/tests/test_tokens.py`
- Test: `backend/tests/test_auth_dependencies.py`

**Interfaces:**
- Consumes: `settings` (`app.config`), `User` model (`app.models`, Task 1), `get_db` (`app.routers.articles`, Plan 1).
- Produces: `settings.jwt_secret_key` (`app.config`); `create_access_token(user_id: int) -> str` and `decode_access_token(token: str) -> int | None` (`app.auth.tokens`); `get_current_user(...) -> User` and `get_current_user_optional(...) -> User | None` FastAPI dependencies (`app.auth.dependencies`). Task 3 (auth API) uses `create_access_token`; Task 5 (holdings API) uses `get_current_user`; Task 10 (alerts API) uses `get_current_user_optional`.

- [ ] **Step 1: Add the PyJWT dependency**

Replace the entire contents of `backend/requirements.txt` with:

```
fastapi
uvicorn
sqlalchemy
pydantic
pydantic-settings
anthropic
feedparser
httpx
pytest
yfinance
pandas
apscheduler
bcrypt
PyJWT
```

Install into the existing venv:

```bash
cd backend
.venv/Scripts/pip install -r requirements.txt
```

- [ ] **Step 2: Add the `jwt_secret_key` setting**

Replace the entire contents of `backend/app/config.py` with:

```python
import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = os.environ.get("DATABASE_URL", "sqlite:///./newsflo.db")
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    enable_scheduler: bool = os.environ.get("ENABLE_SCHEDULER", "false").lower() == "true"
    # DEV-ONLY default — this value is INSECURE and unsafe for production. Set
    # JWT_SECRET_KEY in the environment for any real deployment. (Same
    # optional-at-dev-time pattern as anthropic_api_key defaulting to "".)
    jwt_secret_key: str = os.environ.get("JWT_SECRET_KEY", "dev-insecure-secret-change-in-production")


settings = Settings()
```

- [ ] **Step 3: Write the failing tests**

`backend/tests/test_tokens.py`:

```python
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
```

`backend/tests/test_auth_dependencies.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/pytest tests/test_tokens.py tests/test_auth_dependencies.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.auth.tokens'`.

- [ ] **Step 5: Implement tokens and dependencies**

`backend/app/auth/tokens.py`:

```python
from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24


def create_access_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> int | None:
    """Return the user id encoded in ``token``, or ``None`` if the token is
    invalid, expired, or signed with the wrong secret."""
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[ALGORITHM])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None
    return int(payload["sub"])
```

`backend/app/auth/dependencies.py`:

```python
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.tokens import decode_access_token
from app.models import User
from app.routers.articles import get_db


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
    db: Session = Depends(get_db),
) -> User:
    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.query(User).filter_by(id=user_id).one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user


def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
    db: Session = Depends(get_db),
) -> User | None:
    """Like ``get_current_user`` but returns ``None`` instead of raising when no
    token is supplied or the token is invalid — for endpoints that work both
    anonymously and authenticated (e.g. the alerts endpoint's holdings-match)."""
    if credentials is None:
        return None
    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        return None
    return db.query(User).filter_by(id=user_id).one_or_none()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/pytest tests/test_tokens.py tests/test_auth_dependencies.py -v`
Expected: `9 passed` (4 token tests + 5 dependency tests).

- [ ] **Step 7: Commit**

```bash
git add backend/requirements.txt backend/app/config.py backend/app/auth/tokens.py backend/app/auth/dependencies.py backend/tests/test_tokens.py backend/tests/test_auth_dependencies.py
git commit -m "feat: add PyJWT tokens and HTTPBearer auth dependencies"
```

---

## Task 3: Auth API Endpoints (Register / Login)

**Files:**
- Create: `backend/app/routers/auth.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_auth_api.py`

**Interfaces:**
- Consumes: `hash_password`/`verify_password` (Task 1), `create_access_token` (Task 2), `User` model (Task 1), `get_db` (Plan 1).
- Produces: `POST /api/auth/register` and `POST /api/auth/login`, both returning `{"access_token": <str>, "token_type": "bearer"}`. Tasks 5, 10, 11 register/login through these real endpoints to obtain bearer tokens.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_auth_api.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_auth_api.py -v`
Expected: FAIL — `POST /api/auth/register` returns 404 (route not registered yet), so the assertions fail.

- [ ] **Step 3: Implement the auth router**

`backend/app/routers/auth.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.security import hash_password, verify_password
from app.auth.tokens import create_access_token
from app.models import User
from app.routers.articles import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


class AuthRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/register", response_model=TokenResponse)
def register(payload: AuthRequest, db: Session = Depends(get_db)):
    # Query first rather than relying on catching the DB unique-constraint error.
    existing = db.query(User).filter_by(email=payload.email).one_or_none()
    if existing is not None:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(email=payload.email, hashed_password=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/login", response_model=TokenResponse)
def login(payload: AuthRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=payload.email).one_or_none()
    # Do not leak whether the email or the password was wrong.
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return TokenResponse(access_token=create_access_token(user.id))
```

- [ ] **Step 4: Register the router in `main.py`**

Replace the entire contents of `backend/app/main.py` with:

```python
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import init_db
from app.routers import alerts, articles, auth
from app.scheduler import start_scheduler

app = FastAPI(title="NewsFlo")

app.include_router(articles.router)
app.include_router(alerts.router)
app.include_router(auth.router)

init_db()

if settings.enable_scheduler:
    start_scheduler()

app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest tests/test_auth_api.py -v`
Expected: `5 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/auth.py backend/app/main.py backend/tests/test_auth_api.py
git commit -m "feat: add register and login auth endpoints"
```

---

## Task 4: Holdings DB Model & CSV Loader

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/app/holdings/__init__.py`
- Create: `backend/app/holdings/csv_loader.py`
- Test: `backend/tests/test_holdings_csv.py`

**Interfaces:**
- Consumes: `Company`/`User` models (`app.models`, Task 1), `utcnow` helper (Plan 1).
- Produces: `Holding` model (`app.models`) with columns `id`, `user_id`, `company_id`, `quantity`, `created_at`, and a unique constraint on `(user_id, company_id)`; and `load_holdings_from_csv(session: Session, user_id: int, csv_file) -> int` (`app.holdings.csv_loader`). Task 5 (holdings API), Task 7 (matcher), and Task 10 (alerts API) all rely on the `Holding` model.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_holdings_csv.py`:

```python
import io

from app.holdings.csv_loader import load_holdings_from_csv
from app.models import Company, Holding, User


def _seed(db_session):
    user = User(email="h@example.com", hashed_password="x")
    reliance = Company(ticker="RELIANCE.NS", name="Reliance", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    tcs = Company(ticker="TCS.NS", name="TCS", sector="it", index_tier="NIFTY50", market_cap=1.0)
    db_session.add_all([user, reliance, tcs])
    db_session.commit()
    return user, reliance, tcs


def test_load_holdings_inserts_known_tickers(db_session):
    user, reliance, tcs = _seed(db_session)
    csv_bytes = io.BytesIO(b"Ticker,Quantity\nRELIANCE.NS,10\nTCS.NS,5\n")

    count = load_holdings_from_csv(db_session, user.id, csv_bytes)

    assert count == 2
    holdings = db_session.query(Holding).filter_by(user_id=user.id).all()
    assert {h.company_id for h in holdings} == {reliance.id, tcs.id}


def test_load_holdings_skips_unknown_ticker(db_session):
    user, reliance, _ = _seed(db_session)
    csv_bytes = io.BytesIO(b"Ticker,Quantity\nRELIANCE.NS,10\nUNKNOWN.NS,99\n")

    count = load_holdings_from_csv(db_session, user.id, csv_bytes)

    assert count == 1  # the unknown ticker is skipped, not counted, and does not fail the batch
    assert db_session.query(Holding).count() == 1


def test_load_holdings_upserts_existing(db_session):
    user, reliance, _ = _seed(db_session)
    load_holdings_from_csv(db_session, user.id, io.BytesIO(b"Ticker,Quantity\nRELIANCE.NS,10\n"))
    load_holdings_from_csv(db_session, user.id, io.BytesIO(b"Ticker,Quantity\nRELIANCE.NS,25\n"))

    holdings = db_session.query(Holding).filter_by(user_id=user.id, company_id=reliance.id).all()
    assert len(holdings) == 1
    assert holdings[0].quantity == 25.0


def test_load_holdings_accepts_text_stream(db_session):
    user, reliance, _ = _seed(db_session)

    count = load_holdings_from_csv(db_session, user.id, io.StringIO("Ticker,Quantity\nRELIANCE.NS,7\n"))

    assert count == 1
    assert db_session.query(Holding).one().quantity == 7.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_holdings_csv.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.holdings'` (or `ImportError` on `Holding`).

- [ ] **Step 3: Implement the model and loader**

Append the following `Holding` class to the end of `backend/app/models.py` (after the `User` class from Task 1):

```python
class Holding(Base):
    __tablename__ = "holdings"
    __table_args__ = (UniqueConstraint("user_id", "company_id", name="uq_holdings_user_company"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    quantity = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
```

`backend/app/holdings/__init__.py`: empty file.

`backend/app/holdings/csv_loader.py`:

```python
import csv
import io

from sqlalchemy.orm import Session

from app.models import Company, Holding


def load_holdings_from_csv(session: Session, user_id: int, csv_file) -> int:
    """Load holdings from a file-like object with ``Ticker,Quantity`` columns.

    ``csv_file`` may be a text stream or a binary stream — it works directly with
    FastAPI's ``UploadFile.file`` (a binary SpooledTemporaryFile). Rows whose
    ticker is unknown are skipped (they do not fail the whole batch). Existing
    ``(user_id, company_id)`` holdings are updated (upsert), not duplicated.
    Returns the number of rows successfully upserted (skipped unknown-ticker rows
    are not counted).
    """
    raw = csv_file.read()
    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    reader = csv.DictReader(io.StringIO(text))

    processed = 0
    for row in reader:
        ticker = (row.get("Ticker") or "").strip()
        if not ticker:
            continue
        company = session.query(Company).filter_by(ticker=ticker).one_or_none()
        if company is None:
            continue
        quantity = float(row["Quantity"])
        existing = (
            session.query(Holding)
            .filter_by(user_id=user_id, company_id=company.id)
            .one_or_none()
        )
        if existing is not None:
            existing.quantity = quantity
        else:
            session.add(Holding(user_id=user_id, company_id=company.id, quantity=quantity))
        processed += 1
    session.commit()
    return processed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest tests/test_holdings_csv.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/app/holdings/__init__.py backend/app/holdings/csv_loader.py backend/tests/test_holdings_csv.py
git commit -m "feat: add Holding model and CSV holdings loader"
```

---

## Task 5: Holdings API Endpoints

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/app/routers/holdings.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_holdings_api.py`

**Interfaces:**
- Consumes: `get_current_user` (Task 2), `load_holdings_from_csv` (Task 4), `Company`/`Holding`/`User` models (Tasks 1, 4), `get_db` (Plan 1).
- Produces: `POST /api/holdings` (manual entry), `POST /api/holdings/csv` (CSV upload), `GET /api/holdings` (list) — all auth-required. Task 11 (e2e) adds a holding through these endpoints. Requires `python-multipart` for `UploadFile`/form-data.

- [ ] **Step 1: Add the python-multipart dependency**

Replace the entire contents of `backend/requirements.txt` with:

```
fastapi
uvicorn
sqlalchemy
pydantic
pydantic-settings
anthropic
feedparser
httpx
pytest
yfinance
pandas
apscheduler
bcrypt
PyJWT
python-multipart
```

Install into the existing venv (needed so FastAPI can parse the `UploadFile` form data):

```bash
cd backend
.venv/Scripts/pip install -r requirements.txt
```

- [ ] **Step 2: Write the failing test**

`backend/tests/test_holdings_api.py`:

```python
from fastapi.testclient import TestClient

from app.main import app
from app.models import Company
from app.routers.articles import get_db


def _client_and_token(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    resp = client.post("/api/auth/register", json={"email": "hold@example.com", "password": "pw12345"})
    return client, resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _seed_company(db_session, ticker="RELIANCE.NS"):
    company = Company(ticker=ticker, name="Reliance", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()
    return company


def test_add_holding_requires_auth(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    response = client.post("/api/holdings", json={"ticker": "RELIANCE.NS", "quantity": 5})

    assert response.status_code in (401, 403)  # no bearer token -> rejected
    app.dependency_overrides.clear()


def test_add_holding_manual_entry(db_session):
    client, token = _client_and_token(db_session)
    _seed_company(db_session)

    response = client.post("/api/holdings", json={"ticker": "RELIANCE.NS", "quantity": 12}, headers=_auth(token))

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "RELIANCE.NS"
    assert body["quantity"] == 12.0

    app.dependency_overrides.clear()


def test_add_holding_unknown_ticker_404(db_session):
    client, token = _client_and_token(db_session)

    response = client.post("/api/holdings", json={"ticker": "NOPE.NS", "quantity": 1}, headers=_auth(token))

    assert response.status_code == 404
    app.dependency_overrides.clear()


def test_add_holding_upserts(db_session):
    client, token = _client_and_token(db_session)
    _seed_company(db_session)
    client.post("/api/holdings", json={"ticker": "RELIANCE.NS", "quantity": 5}, headers=_auth(token))
    client.post("/api/holdings", json={"ticker": "RELIANCE.NS", "quantity": 8}, headers=_auth(token))

    listed = client.get("/api/holdings", headers=_auth(token)).json()

    assert len(listed) == 1
    assert listed[0]["quantity"] == 8.0

    app.dependency_overrides.clear()


def test_upload_holdings_csv(db_session):
    client, token = _client_and_token(db_session)
    _seed_company(db_session)
    _seed_company(db_session, ticker="TCS.NS")

    csv_content = b"Ticker,Quantity\nRELIANCE.NS,10\nTCS.NS,4\n"
    response = client.post(
        "/api/holdings/csv",
        files={"file": ("holdings.csv", csv_content, "text/csv")},
        headers=_auth(token),
    )

    assert response.status_code == 200
    assert response.json()["loaded"] == 2

    app.dependency_overrides.clear()


def test_list_holdings_returns_company_info(db_session):
    client, token = _client_and_token(db_session)
    _seed_company(db_session)
    client.post("/api/holdings", json={"ticker": "RELIANCE.NS", "quantity": 3}, headers=_auth(token))

    response = client.get("/api/holdings", headers=_auth(token))

    assert response.status_code == 200
    body = response.json()
    assert body[0]["ticker"] == "RELIANCE.NS"
    assert body[0]["name"] == "Reliance"
    assert body[0]["quantity"] == 3.0

    app.dependency_overrides.clear()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_holdings_api.py -v`
Expected: FAIL — `POST /api/holdings` returns 404 (route not registered yet).

- [ ] **Step 4: Implement the holdings router**

`backend/app/routers/holdings.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.holdings.csv_loader import load_holdings_from_csv
from app.models import Company, Holding, User
from app.routers.articles import get_db

router = APIRouter(prefix="/api/holdings", tags=["holdings"])


class HoldingRequest(BaseModel):
    ticker: str
    quantity: float


def _upsert_holding(db: Session, user_id: int, company_id: int, quantity: float) -> Holding:
    existing = db.query(Holding).filter_by(user_id=user_id, company_id=company_id).one_or_none()
    if existing is not None:
        existing.quantity = quantity
        holding = existing
    else:
        holding = Holding(user_id=user_id, company_id=company_id, quantity=quantity)
        db.add(holding)
    db.commit()
    db.refresh(holding)
    return holding


@router.post("")
def add_holding(
    payload: HoldingRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    company = db.query(Company).filter_by(ticker=payload.ticker).one_or_none()
    if company is None:
        raise HTTPException(status_code=404, detail="Unknown ticker")
    holding = _upsert_holding(db, current_user.id, company.id, payload.quantity)
    return {
        "company_id": company.id, "ticker": company.ticker,
        "name": company.name, "quantity": holding.quantity,
    }


@router.post("/csv")
def upload_holdings_csv(
    file: UploadFile,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    loaded = load_holdings_from_csv(db, current_user.id, file.file)
    return {"loaded": loaded}


@router.get("")
def list_holdings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(Holding, Company)
        .join(Company, Holding.company_id == Company.id)
        .filter(Holding.user_id == current_user.id)
        .all()
    )
    return [{
        "company_id": company.id, "ticker": company.ticker,
        "name": company.name, "quantity": holding.quantity,
    } for holding, company in rows]
```

- [ ] **Step 5: Register the router in `main.py`**

Replace the entire contents of `backend/app/main.py` with:

```python
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import init_db
from app.routers import alerts, articles, auth, holdings
from app.scheduler import start_scheduler

app = FastAPI(title="NewsFlo")

app.include_router(articles.router)
app.include_router(alerts.router)
app.include_router(auth.router)
app.include_router(holdings.router)

init_db()

if settings.enable_scheduler:
    start_scheduler()

app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest tests/test_holdings_api.py -v`
Expected: `6 passed`

- [ ] **Step 7: Commit**

```bash
git add backend/requirements.txt backend/app/routers/holdings.py backend/app/main.py backend/tests/test_holdings_api.py
git commit -m "feat: add holdings API (manual entry, CSV upload, list)"
```

---

## Task 6: Email Client (Console Backend + Stub)

**Files:**
- Modify: `backend/app/config.py`
- Create: `backend/app/alerting/__init__.py`
- Create: `backend/app/alerting/email_client.py`
- Test: `backend/tests/test_email_client.py`

**Interfaces:**
- Consumes: `settings` (`app.config`).
- Produces: `settings.resend_api_key` (`app.config`) and `send_email(to: str, subject: str, body: str) -> bool` (`app.alerting.email_client`). Task 8 (sender) imports `send_email` as its default `email_fn`.

- [ ] **Step 1: Add the `resend_api_key` setting**

Replace the entire contents of `backend/app/config.py` with:

```python
import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = os.environ.get("DATABASE_URL", "sqlite:///./newsflo.db")
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    enable_scheduler: bool = os.environ.get("ENABLE_SCHEDULER", "false").lower() == "true"
    # DEV-ONLY default — this value is INSECURE and unsafe for production. Set
    # JWT_SECRET_KEY in the environment for any real deployment. (Same
    # optional-at-dev-time pattern as anthropic_api_key defaulting to "".)
    jwt_secret_key: str = os.environ.get("JWT_SECRET_KEY", "dev-insecure-secret-change-in-production")
    resend_api_key: str = os.environ.get("RESEND_API_KEY", "")


settings = Settings()
```

- [ ] **Step 2: Write the failing test**

`backend/tests/test_email_client.py`:

```python
import logging

import pytest

import app.alerting.email_client as email_client
from app.alerting.email_client import send_email


def test_send_email_console_backend_returns_true_and_logs(caplog):
    with caplog.at_level(logging.INFO):
        result = send_email(to="a@example.com", subject="Hello", body="World")

    assert result is True
    assert "[console-email]" in caplog.text
    assert "a@example.com" in caplog.text


def test_send_email_raises_when_real_key_configured(monkeypatch):
    monkeypatch.setattr(email_client.settings, "resend_api_key", "fake-key")

    with pytest.raises(NotImplementedError):
        send_email(to="a@example.com", subject="Hello", body="World")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_email_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.alerting'`.

- [ ] **Step 4: Implement the email client**

`backend/app/alerting/__init__.py`: empty file.

`backend/app/alerting/email_client.py`:

```python
import logging

from app.config import settings

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> bool:
    """Send an email, returning True on success.

    Default/dev backend (no RESEND_API_KEY set): log the message at INFO and
    return True — never touches the network, never needs a key, always
    "succeeds". This is the backend every test exercises.

    If RESEND_API_KEY is configured, a real HTTP-calling backend would go here.
    It is intentionally left as a loud NotImplementedError stub: no real Resend
    key was available to build/test an HTTP implementation against, so we fail
    loudly rather than silently pretend to send. (Same optional-at-dev-time
    pattern as anthropic_api_key in Plan 1.)
    """
    if not settings.resend_api_key:
        logger.info(f"[console-email] to={to} subject={subject!r} body={body!r}")
        return True
    raise NotImplementedError(
        "Real email sending not implemented — no Resend API key was available "
        "to build/test against"
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest tests/test_email_client.py -v`
Expected: `2 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/app/config.py backend/app/alerting/__init__.py backend/app/alerting/email_client.py backend/tests/test_email_client.py
git commit -m "feat: add pluggable email client with console backend default"
```

---

## Task 7: EmailNotification Model & Alert-to-Holdings Matcher

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/app/alerting/matcher.py`
- Test: `backend/tests/test_matcher.py`

**Interfaces:**
- Consumes: `Alert`/`AlertCompany` models (Plan 1), `Holding`/`User` models (Tasks 1, 4), `utcnow` helper (Plan 1).
- Produces: `EmailNotification` model (`app.models`) with columns `id`, `user_id`, `alert_company_id`, `status` (default `"pending"`, values `"pending"|"sent"|"failed"`), `created_at`, `sent_at`, and a unique constraint on `(user_id, alert_company_id)`; and `match_alert_to_holdings(session: Session, alert: Alert) -> list[EmailNotification]` (`app.alerting.matcher`) returning only newly created pending notifications. Task 8 (sender) consumes the returned list; Task 9 (pipeline) calls the matcher.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_matcher.py`:

```python
from app.alerting.matcher import match_alert_to_holdings
from app.models import Alert, AlertCompany, Article, Company, EmailNotification, Holding, User


def _seed_alert_with_company(session):
    company = Company(ticker="RELIANCE.NS", name="Reliance", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    article = Article(source="test", url="https://example.com/m", title="Oil news", content="")
    session.add_all([company, article])
    session.commit()
    alert = Alert(article_id=article.id, category="oil_energy")
    session.add(alert)
    session.commit()
    ac = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="x", basis="direct_mention",
    )
    session.add(ac)
    session.commit()
    return alert, company, ac


def test_matcher_creates_notification_for_holder(db_session):
    alert, company, ac = _seed_alert_with_company(db_session)
    user = User(email="u@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    db_session.add(Holding(user_id=user.id, company_id=company.id, quantity=5.0))
    db_session.commit()

    created = match_alert_to_holdings(db_session, alert)

    assert len(created) == 1
    assert created[0].user_id == user.id
    assert created[0].alert_company_id == ac.id
    assert created[0].status == "pending"


def test_matcher_ignores_non_holders(db_session):
    alert, company, ac = _seed_alert_with_company(db_session)
    other = Company(ticker="TCS.NS", name="TCS", sector="it", index_tier="NIFTY50", market_cap=1.0)
    user = User(email="u@example.com", hashed_password="x")
    db_session.add_all([other, user])
    db_session.commit()
    db_session.add(Holding(user_id=user.id, company_id=other.id, quantity=5.0))
    db_session.commit()

    created = match_alert_to_holdings(db_session, alert)

    assert created == []
    assert db_session.query(EmailNotification).count() == 0


def test_matcher_is_idempotent(db_session):
    alert, company, ac = _seed_alert_with_company(db_session)
    user = User(email="u@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    db_session.add(Holding(user_id=user.id, company_id=company.id, quantity=5.0))
    db_session.commit()

    first = match_alert_to_holdings(db_session, alert)
    second = match_alert_to_holdings(db_session, alert)

    assert len(first) == 1
    assert second == []  # only newly created rows are returned; the pre-existing one is not
    assert db_session.query(EmailNotification).count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_matcher.py -v`
Expected: FAIL with `ImportError: cannot import name 'EmailNotification' from 'app.models'` (or `ModuleNotFoundError` on `app.alerting.matcher`).

- [ ] **Step 3: Implement the model and matcher**

Append the following `EmailNotification` class to the end of `backend/app/models.py` (after the `Holding` class from Task 4):

```python
class EmailNotification(Base):
    __tablename__ = "email_notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "alert_company_id", name="uq_notification_user_alert_company"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    alert_company_id = Column(Integer, ForeignKey("alert_companies.id"), nullable=False)
    status = Column(String, nullable=False, default="pending")  # pending | sent | failed
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    sent_at = Column(DateTime(timezone=True), nullable=True)
```

`backend/app/alerting/matcher.py`:

```python
from sqlalchemy.orm import Session

from app.models import Alert, EmailNotification, Holding


def match_alert_to_holdings(session: Session, alert: Alert) -> list[EmailNotification]:
    """For each company in ``alert``, find every user holding that company and
    queue a pending EmailNotification for the ``(user, alert_company)`` pair,
    unless one already exists. Returns only the newly created notifications.

    The pre-check query is a second layer of idempotency on top of the DB unique
    constraint (mirrors the outcome tracker in Plan 2), so re-running the matcher
    for the same alert never double-notifies the same user for the same
    alert-company match.
    """
    created: list[EmailNotification] = []
    for alert_company in alert.companies:
        holdings = (
            session.query(Holding)
            .filter(Holding.company_id == alert_company.company_id)
            .all()
        )
        for holding in holdings:
            existing = (
                session.query(EmailNotification)
                .filter_by(user_id=holding.user_id, alert_company_id=alert_company.id)
                .one_or_none()
            )
            if existing is not None:
                continue
            notification = EmailNotification(
                user_id=holding.user_id,
                alert_company_id=alert_company.id,
                status="pending",
            )
            session.add(notification)
            session.commit()
            created.append(notification)
    return created
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest tests/test_matcher.py -v`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/app/alerting/matcher.py backend/tests/test_matcher.py
git commit -m "feat: add EmailNotification model and idempotent holdings matcher"
```

---

## Task 8: Send Pending Notifications

**Files:**
- Create: `backend/app/alerting/sender.py`
- Test: `backend/tests/test_sender.py`

**Interfaces:**
- Consumes: `send_email` (Task 6), `Alert`/`AlertCompany`/`User` models (Plan 1, Task 1), `EmailNotification` model (Task 7), `utcnow` helper (Plan 1).
- Produces: `send_pending_notifications(session: Session, notifications: list[EmailNotification], email_fn=send_email) -> int` (`app.alerting.sender`) — sends one email per notification, marks each `"sent"` or `"failed"`, commits after each, and returns the count marked `"sent"`. Task 9 (pipeline) calls this with the matcher's output.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_sender.py`:

```python
from app.alerting.sender import send_pending_notifications
from app.models import Alert, AlertCompany, Article, Company, EmailNotification, User


def _seed_notification(session):
    company = Company(ticker="RELIANCE.NS", name="Reliance", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    article = Article(source="test", url="https://example.com/s", title="Oil news headline", content="")
    user = User(email="send@example.com", hashed_password="x")
    session.add_all([company, article, user])
    session.commit()
    alert = Alert(article_id=article.id, category="oil_energy")
    session.add(alert)
    session.commit()
    ac = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin", basis="direct_mention",
    )
    session.add(ac)
    session.commit()
    notification = EmailNotification(user_id=user.id, alert_company_id=ac.id, status="pending")
    session.add(notification)
    session.commit()
    return notification


def test_send_marks_sent_with_console_backend(db_session):
    notification = _seed_notification(db_session)

    sent = send_pending_notifications(db_session, [notification])  # default console email_fn

    assert sent == 1
    refreshed = db_session.query(EmailNotification).filter_by(id=notification.id).one()
    assert refreshed.status == "sent"
    assert refreshed.sent_at is not None


def test_send_passes_expected_subject_and_recipient(db_session):
    notification = _seed_notification(db_session)
    captured = {}

    def fake_email(to, subject, body):
        captured["to"] = to
        captured["subject"] = subject
        captured["body"] = body
        return True

    sent = send_pending_notifications(db_session, [notification], email_fn=fake_email)

    assert sent == 1
    assert captured["to"] == "send@example.com"
    assert "Reliance" in captured["subject"]
    assert "bullish" in captured["subject"]
    assert "Oil news headline" in captured["body"]


def test_send_marks_failed_on_false_without_raising(db_session):
    notification = _seed_notification(db_session)

    sent = send_pending_notifications(db_session, [notification], email_fn=lambda to, subject, body: False)

    assert sent == 0
    refreshed = db_session.query(EmailNotification).filter_by(id=notification.id).one()
    assert refreshed.status == "failed"
    assert refreshed.sent_at is None


def test_send_marks_failed_on_exception_and_continues_batch(db_session):
    n1 = _seed_notification(db_session)
    # A second notification for a different user on the same alert_company.
    user2 = User(email="send2@example.com", hashed_password="x")
    db_session.add(user2)
    db_session.commit()
    n2 = EmailNotification(user_id=user2.id, alert_company_id=n1.alert_company_id, status="pending")
    db_session.add(n2)
    db_session.commit()

    def flaky(to, subject, body):
        if to == "send@example.com":
            raise RuntimeError("smtp down")
        return True

    sent = send_pending_notifications(db_session, [n1, n2], email_fn=flaky)

    assert sent == 1
    r1 = db_session.query(EmailNotification).filter_by(id=n1.id).one()
    r2 = db_session.query(EmailNotification).filter_by(id=n2.id).one()
    assert r1.status == "failed"  # the raising one is marked failed, not fatal
    assert r2.status == "sent"    # the batch continued
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_sender.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.alerting.sender'`.

- [ ] **Step 3: Implement the sender**

`backend/app/alerting/sender.py`:

```python
import logging

from sqlalchemy.orm import Session

from app.alerting.email_client import send_email
from app.models import Alert, AlertCompany, EmailNotification, User, utcnow

logger = logging.getLogger(__name__)


def send_pending_notifications(
    session: Session, notifications: list[EmailNotification], email_fn=send_email
) -> int:
    """Send an email for each notification, marking it 'sent' or 'failed'.

    For each notification, look up the recipient User, the AlertCompany (company
    name/ticker/direction/magnitude/rationale) and its parent Alert's Article
    (headline), build the email, and call ``email_fn``. On True -> 'sent' +
    sent_at; on False or any exception -> 'failed' (never raised). One failed
    email must not block the others in the batch (same resilience pattern as
    Plan 2's outcome tracker). Commits after each notification. Returns the count
    marked 'sent'.
    """
    sent_count = 0
    for notification in notifications:
        alert_company = (
            session.query(AlertCompany).filter_by(id=notification.alert_company_id).one()
        )
        user = session.query(User).filter_by(id=notification.user_id).one()
        alert = session.query(Alert).filter_by(id=alert_company.alert_id).one()
        company = alert_company.company

        subject = f"NewsFlo Alert: {company.name} ({alert_company.direction})"
        body = (
            f"News: {alert.article.title}\n"
            f"Company: {company.name} ({company.ticker})\n"
            f"Direction: {alert_company.direction}\n"
            f"Estimated move: {alert_company.magnitude_low}% to {alert_company.magnitude_high}%\n"
            f"Why: {alert_company.rationale}\n"
        )

        try:
            ok = email_fn(to=user.email, subject=subject, body=body)
        except Exception:
            logger.exception("Email send raised for notification id=%s", notification.id)
            ok = False

        if ok:
            notification.status = "sent"
            notification.sent_at = utcnow()
            sent_count += 1
        else:
            notification.status = "failed"
        session.commit()

    return sent_count
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest tests/test_sender.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/alerting/sender.py backend/tests/test_sender.py
git commit -m "feat: add resilient email-notification sender"
```

---

## Task 9: Wire Alerting into the Pipeline

**Files:**
- Modify: `backend/app/pipeline.py`
- Test: `backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `match_alert_to_holdings` (Task 7), `send_pending_notifications` (Task 8), plus everything the existing pipeline already consumes (Plans 1-2).
- Produces: unchanged `process_new_articles(session: Session, claude_client) -> int` signature, but after each alert is committed it fans out email notifications to holders. With no matching holdings this is a no-op (matcher returns `[]`, sender processes an empty list), so all existing pipeline/e2e tests are unaffected. Task 11 (e2e) relies on this behavior.

- [ ] **Step 1: Add the new pipeline test**

Replace the entire contents of `backend/tests/test_pipeline.py` with:

```python
import pytest

import app.pipeline as pipeline_module
from app.analysis.schemas import AnalysisOutput, CompanyMention
from app.models import (
    Alert,
    AlertCompany,
    Article,
    CalibrationSample,
    Company,
    EmailNotification,
    Holding,
    User,
)
from app.pipeline import process_new_articles


def test_process_new_articles_creates_alert_end_to_end(db_session, monkeypatch):
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    article = Article(
        source="test", url="https://example.com/a",
        title="US strikes Iran oil export sites", content="crude oil markets react",
    )
    db_session.add(article)
    db_session.commit()

    fake_output = AnalysisOutput(
        category="oil_energy",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)

    created = process_new_articles(db_session, claude_client=object())

    assert created == 1
    alert = db_session.query(Alert).one()
    assert alert.category == "oil_energy"

    alert_companies = db_session.query(AlertCompany).filter_by(alert_id=alert.id).all()
    assert len(alert_companies) == 1
    assert alert_companies[0].company_id == company.id
    # No calibration samples exist, so the alert falls back to the LLM's own estimate.
    assert alert_companies[0].confidence == "llm_estimate"
    assert alert_companies[0].magnitude_low == 2.0
    assert alert_companies[0].magnitude_high == 4.0

    # No holdings exist, so no email notifications were created (matcher no-op).
    assert db_session.query(EmailNotification).count() == 0

    refreshed_article = db_session.query(Article).filter_by(id=article.id).one()
    assert refreshed_article.status == "ANALYZED"


def test_process_new_articles_uses_calibrated_magnitude_when_enough_samples(db_session, monkeypatch):
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    # 5 samples of [1, 2, 3, 4, 5] for (oil_energy, this company) -> mean = 3.0, pstdev = sqrt(2).
    for i, actual in enumerate([1.0, 2.0, 3.0, 4.0, 5.0]):
        db_session.add(CalibrationSample(
            alert_company_id=i + 1, category="oil_energy", company_id=company.id,
            direction="bullish", magnitude_actual=actual, horizon_days=1,
        ))
    db_session.commit()

    article = Article(
        source="test", url="https://example.com/cal",
        title="US strikes Iran oil export sites", content="crude oil markets react",
    )
    db_session.add(article)
    db_session.commit()

    fake_output = AnalysisOutput(
        category="oil_energy",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)

    created = process_new_articles(db_session, claude_client=object())
    assert created == 1

    ac = db_session.query(AlertCompany).one()
    assert ac.confidence == "calibrated"
    # mean([1,2,3,4,5]) = 3.0, pstdev = sqrt(2) ~= 1.41421356
    assert ac.magnitude_low == pytest.approx(3.0 - 2 ** 0.5)
    assert ac.magnitude_high == pytest.approx(3.0 + 2 ** 0.5)


def test_process_new_articles_sends_email_notification_for_holder(db_session, monkeypatch):
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    user = User(email="holder@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    db_session.add(Holding(user_id=user.id, company_id=company.id, quantity=10.0))
    db_session.commit()

    article = Article(
        source="test", url="https://example.com/notify",
        title="US strikes Iran oil export sites", content="crude oil markets react",
    )
    db_session.add(article)
    db_session.commit()

    fake_output = AnalysisOutput(
        category="oil_energy",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)

    created = process_new_articles(db_session, claude_client=object())
    assert created == 1

    notifications = db_session.query(EmailNotification).all()
    assert len(notifications) == 1
    assert notifications[0].user_id == user.id
    # The default console email backend always succeeds, so the row is marked sent.
    assert notifications[0].status == "sent"


def test_process_new_articles_marks_analysis_failed_after_retries(db_session, monkeypatch):
    article = Article(source="test", url="https://example.com/b", title="RBI hikes repo rate", content="")
    db_session.add(article)
    db_session.commit()

    def boom(client, title, content):
        raise RuntimeError("api down")

    monkeypatch.setattr(pipeline_module, "analyze_article", boom)

    created = process_new_articles(db_session, claude_client=object())

    assert created == 0
    refreshed = db_session.query(Article).filter_by(id=article.id).one()
    assert refreshed.status == "ANALYSIS_FAILED"


def test_process_new_articles_ignores_filtered_articles(db_session, monkeypatch):
    irrelevant = Article(source="test", url="https://example.com/c", title="Cat stuck in tree", content="")
    db_session.add(irrelevant)
    db_session.commit()

    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: (_ for _ in ()).throw(AssertionError("should not be called")))

    created = process_new_articles(db_session, claude_client=object())

    assert created == 0
    refreshed = db_session.query(Article).filter_by(id=irrelevant.id).one()
    assert refreshed.status == "FILTERED"
```

- [ ] **Step 2: Run tests to verify the new one fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_pipeline.py -v`
Expected: FAIL — `test_process_new_articles_sends_email_notification_for_holder` fails because the pipeline does not yet call the matcher/sender, so `EmailNotification` count is 0. (The other four tests still pass.)

- [ ] **Step 3: Wire the matcher and sender into the pipeline**

Replace the entire contents of `backend/app/pipeline.py` with:

```python
from sqlalchemy.orm import Session

from app.alerting.matcher import match_alert_to_holdings
from app.alerting.sender import send_pending_notifications
from app.analysis.claude_client import analyze_article
from app.calibration.blender import get_calibrated_magnitude
from app.companies.resolution import resolve_companies
from app.filtering.heuristic import filter_new_articles
from app.models import Alert, AlertCompany, Article


def process_new_articles(session: Session, claude_client) -> int:
    filter_new_articles(session)

    alerts_created = 0
    pending = session.query(Article).filter_by(status="CATEGORIZED").all()

    for article in pending:
        analysis = None
        for _ in range(2):  # try once, retry once
            try:
                analysis = analyze_article(claude_client, article.title, article.content)
                break
            except Exception:
                continue

        if analysis is None:
            article.status = "ANALYSIS_FAILED"
            session.commit()
            continue

        resolved = resolve_companies(session, analysis.companies)

        alert = Alert(article_id=article.id, category=analysis.category)
        session.add(alert)
        session.flush()

        for entry in resolved:
            calibrated = get_calibrated_magnitude(
                session, category=analysis.category, company_id=entry["company_id"],
            )
            if calibrated is not None:
                low, high = calibrated
                entry["magnitude_low"] = low
                entry["magnitude_high"] = high
                entry["confidence"] = "calibrated"
            else:
                entry["confidence"] = "llm_estimate"
            session.add(AlertCompany(alert_id=alert.id, **entry))

        article.status = "ANALYZED"
        article.category = analysis.category
        session.commit()
        alerts_created += 1

        # Plan 3: fan out email alerts to any users holding an affected company.
        # With no matching holdings this is a no-op — the matcher returns [] and
        # the sender processes an empty list — so existing tests are unaffected.
        new_notifications = match_alert_to_holdings(session, alert)
        send_pending_notifications(session, new_notifications)

    return alerts_created
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/pytest tests/test_pipeline.py -v`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline.py backend/tests/test_pipeline.py
git commit -m "feat: fan out email notifications from the pipeline on holdings match"
```

---

## Task 10: Expose Holdings-Match in the Alerts API

**Files:**
- Modify: `backend/app/routers/alerts.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `get_current_user_optional` (Task 2), `Holding`/`User` models (Tasks 1, 4), `Alert` model (Plan 1).
- Produces: each company dict in `GET /api/alerts` now includes `"in_my_holdings": bool` — `True` only when an authenticated user holds that company, `False` otherwise (including for anonymous requests, which never error). Task 11 (e2e) asserts this round-trips as `True` for a holder.

- [ ] **Step 1: Update the API test**

Replace the entire contents of `backend/tests/test_api.py` with:

```python
from fastapi.testclient import TestClient

from app.main import app
from app.models import Alert, AlertCompany, Article, Company
from app.routers.articles import get_db


def test_list_alerts_returns_nested_companies(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    article = Article(
        source="test", url="https://example.com/x", title="Test headline",
        status="ANALYZED", category="oil_energy",
    )
    db_session.add(article)
    db_session.commit()

    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()

    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin",
        basis="direct_mention", confidence="llm_estimate",
    ))
    db_session.commit()

    response = client.get("/api/alerts")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["companies"][0]["ticker"] == "RELIANCE.NS"
    assert body[0]["companies"][0]["confidence"] == "llm_estimate"
    # Anonymous request (no Authorization header) -> in_my_holdings is present and False.
    assert body[0]["companies"][0]["in_my_holdings"] is False
    assert body[0]["article"]["title"] == "Test headline"

    app.dependency_overrides.clear()


def test_list_alerts_flags_in_my_holdings_for_authenticated_holder(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    article = Article(source="test", url="https://example.com/z", title="Oil headline", status="ANALYZED", category="oil_energy")
    db_session.add_all([company, article])
    db_session.commit()

    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=2.0, magnitude_high=4.0, rationale="margin",
        basis="direct_mention", confidence="llm_estimate",
    ))
    db_session.commit()

    token = client.post(
        "/api/auth/register", json={"email": "alertholder@example.com", "password": "pw12345"},
    ).json()["access_token"]
    client.post(
        "/api/holdings", json={"ticker": "RELIANCE.NS", "quantity": 5},
        headers={"Authorization": f"Bearer {token}"},
    )

    response = client.get("/api/alerts", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()[0]["companies"][0]["in_my_holdings"] is True

    app.dependency_overrides.clear()


def test_list_articles_returns_all(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    db_session.add(Article(source="test", url="https://example.com/y", title="Another headline"))
    db_session.commit()

    response = client.get("/api/articles")

    assert response.status_code == 200
    assert response.json()[0]["title"] == "Another headline"

    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_api.py -v`
Expected: FAIL on `test_list_alerts_returns_nested_companies` with `KeyError: 'in_my_holdings'` (the response dict does not yet include the key).

- [ ] **Step 3: Add `in_my_holdings` to the response**

Replace the entire contents of `backend/app/routers/alerts.py` with:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_optional
from app.models import Alert, Holding, User
from app.routers.articles import get_db

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("")
def list_alerts(
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    # Anonymous requests get an empty set -> every company is in_my_holdings=False.
    held_company_ids: set[int] = set()
    if current_user is not None:
        held_company_ids = {
            h.company_id for h in db.query(Holding).filter_by(user_id=current_user.id).all()
        }

    alerts = db.query(Alert).order_by(Alert.created_at.desc()).all()
    return [{
        "id": alert.id,
        "category": alert.category,
        "created_at": alert.created_at.isoformat(),
        "article": {"id": alert.article.id, "title": alert.article.title, "url": alert.article.url},
        "companies": [{
            "company_id": ac.company_id, "ticker": ac.company.ticker, "name": ac.company.name,
            "index_tier": ac.company.index_tier, "direction": ac.direction,
            "magnitude_low": ac.magnitude_low, "magnitude_high": ac.magnitude_high,
            "rationale": ac.rationale, "basis": ac.basis, "confidence": ac.confidence,
            "in_my_holdings": ac.company_id in held_company_ids,
        } for ac in alert.companies],
    } for alert in alerts]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest tests/test_api.py -v`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/alerts.py backend/tests/test_api.py
git commit -m "feat: flag in_my_holdings per company in the alerts API"
```

---

## Task 11: End-to-End Integration Test

**Files:**
- Modify: `backend/tests/test_end_to_end.py`

**Interfaces:**
- Consumes: the real `/api/auth/register` and `/api/holdings` endpoints (Tasks 3, 5), `fetch_new_articles` (Plan 1), `process_new_articles` (Task 9), the `/api/alerts` endpoint (Task 10), `EmailNotification` model (Task 7) — exercises the full auth → holdings → RSS → pipeline → match → send → API chain with no internal shortcuts.

- [ ] **Step 1: Add the full-chain holder-notification test**

Replace the entire contents of `backend/tests/test_end_to_end.py` with:

```python
from types import SimpleNamespace

import pytest

import app.pipeline as pipeline_module
from app.analysis.schemas import AnalysisOutput, CompanyMention
from app.ingestion.poller import fetch_new_articles
from app.models import CalibrationSample, Company, EmailNotification
from app.pipeline import process_new_articles


def test_full_pipeline_from_rss_entry_to_alert(db_session, monkeypatch):
    db_session.add(Company(
        ticker="RELIANCE.NS", name="Reliance Industries",
        sector="oil_gas", index_tier="NIFTY50", market_cap=1_800_000.0,
    ))
    db_session.commit()

    feed_entries = [{
        "link": "https://example.com/breaking-oil-news",
        "title": "US strikes Iran oil export sites",
        "summary": "Crude oil markets react sharply to the strikes.",
    }]

    def fake_parse(url):
        return SimpleNamespace(entries=feed_entries)

    monkeypatch.setattr("app.ingestion.poller.feedparser.parse", fake_parse)

    inserted = fetch_new_articles(db_session, [{"source": "test_feed", "url": "http://feed.test/rss"}])
    assert inserted == 1

    fake_output = AnalysisOutput(
        category="oil_energy",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)

    created = process_new_articles(db_session, claude_client=object())
    assert created == 1

    from app.main import app as fastapi_app
    from app.routers.articles import get_db
    from fastapi.testclient import TestClient

    fastapi_app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(fastapi_app)

    response = client.get("/api/alerts")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["article"]["title"] == "US strikes Iran oil export sites"
    assert body[0]["companies"][0]["ticker"] == "RELIANCE.NS"
    # No calibration samples exist for this pair, so it stays LLM-only.
    assert body[0]["companies"][0]["confidence"] == "llm_estimate"
    # No authenticated user on this request -> in_my_holdings is False.
    assert body[0]["companies"][0]["in_my_holdings"] is False

    fastapi_app.dependency_overrides.clear()


def test_full_pipeline_shows_calibrated_confidence_with_enough_samples(db_session, monkeypatch):
    company = Company(
        ticker="RELIANCE.NS", name="Reliance Industries",
        sector="oil_gas", index_tier="NIFTY50", market_cap=1_800_000.0,
    )
    db_session.add(company)
    db_session.commit()

    # Pre-seed 5 historical outcomes of [1, 2, 3, 4, 5] for (oil_energy, this company)
    # -> mean = 3.0, pstdev = sqrt(2) ~= 1.41421356 -> calibrated range applies.
    for i, actual in enumerate([1.0, 2.0, 3.0, 4.0, 5.0]):
        db_session.add(CalibrationSample(
            alert_company_id=i + 1, category="oil_energy", company_id=company.id,
            direction="bullish", magnitude_actual=actual, horizon_days=1,
        ))
    db_session.commit()

    feed_entries = [{
        "link": "https://example.com/breaking-oil-news-2",
        "title": "US strikes Iran oil export sites",
        "summary": "Crude oil markets react sharply to the strikes.",
    }]

    def fake_parse(url):
        return SimpleNamespace(entries=feed_entries)

    monkeypatch.setattr("app.ingestion.poller.feedparser.parse", fake_parse)

    inserted = fetch_new_articles(db_session, [{"source": "test_feed", "url": "http://feed.test/rss"}])
    assert inserted == 1

    fake_output = AnalysisOutput(
        category="oil_energy",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)

    created = process_new_articles(db_session, claude_client=object())
    assert created == 1

    from app.main import app as fastapi_app
    from app.routers.articles import get_db
    from fastapi.testclient import TestClient

    fastapi_app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(fastapi_app)

    response = client.get("/api/alerts")
    assert response.status_code == 200
    company_payload = response.json()[0]["companies"][0]
    assert company_payload["confidence"] == "calibrated"
    assert company_payload["magnitude_low"] == pytest.approx(3.0 - 2 ** 0.5)
    assert company_payload["magnitude_high"] == pytest.approx(3.0 + 2 ** 0.5)

    fastapi_app.dependency_overrides.clear()


def test_full_pipeline_notifies_holder_end_to_end(db_session, monkeypatch):
    from app.main import app as fastapi_app
    from app.routers.articles import get_db
    from fastapi.testclient import TestClient

    fastapi_app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(fastapi_app)

    # Seed the company the analysis will resolve to.
    db_session.add(Company(
        ticker="RELIANCE.NS", name="Reliance Industries",
        sector="oil_gas", index_tier="NIFTY50", market_cap=1_800_000.0,
    ))
    db_session.commit()

    # Register a real user and add a holding through the real HTTP endpoints.
    token = client.post(
        "/api/auth/register", json={"email": "e2e@example.com", "password": "pw12345"},
    ).json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}
    add_resp = client.post("/api/holdings", json={"ticker": "RELIANCE.NS", "quantity": 15}, headers=auth)
    assert add_resp.status_code == 200

    # Ingest one RSS article.
    feed_entries = [{
        "link": "https://example.com/breaking-oil-news-e2e",
        "title": "US strikes Iran oil export sites",
        "summary": "Crude oil markets react sharply to the strikes.",
    }]
    monkeypatch.setattr(
        "app.ingestion.poller.feedparser.parse",
        lambda url: SimpleNamespace(entries=feed_entries),
    )
    inserted = fetch_new_articles(db_session, [{"source": "test_feed", "url": "http://feed.test/rss"}])
    assert inserted == 1

    # Run the pipeline with a mocked Claude analysis resolving to the held company.
    fake_output = AnalysisOutput(
        category="oil_energy",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)

    created = process_new_articles(db_session, claude_client=object())
    assert created == 1

    # (a) The alerts API shows in_my_holdings True for this user's held company.
    response = client.get("/api/alerts", headers=auth)
    assert response.status_code == 200
    assert response.json()[0]["companies"][0]["in_my_holdings"] is True

    # (b) Exactly one EmailNotification row exists, marked sent (console backend).
    notifications = db_session.query(EmailNotification).all()
    assert len(notifications) == 1
    assert notifications[0].status == "sent"

    fastapi_app.dependency_overrides.clear()
```

- [ ] **Step 2: Run the full test suite**

Run: `cd backend && .venv/Scripts/pytest tests/ -v`
Expected: all tests pass — every test from Plans 1-2 plus Tasks 1-11 of this plan — with no live network calls (RSS `feedparser.parse`, Claude `analyze_article`, yfinance `yf.Ticker` are monkeypatched or unused; email goes through the console backend; no `RESEND_API_KEY` set; the scheduler never starts because `ENABLE_SCHEDULER` is unset).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_end_to_end.py
git commit -m "test: add end-to-end holder-notification integration test"
```

---

## Definition of Done (Plan 3)

- `pytest tests/ -v` passes fully with zero live network calls — RSS, Claude, and yfinance are always monkeypatched; email always routes through the console backend (no `RESEND_API_KEY` set); no real HTTP call to any email or broker provider; and the scheduler never starts during tests (`settings.enable_scheduler` defaults to `False`).
- A human can `POST /api/auth/register` with an email + password, `POST /api/auth/login` to get a JWT, and add a holding either manually (`POST /api/holdings`) or by CSV upload (`POST /api/holdings/csv`). Passwords are stored only as `bcrypt` hashes, never in plaintext.
- When a new alert (produced by the pipeline) affects a company a user holds, an `EmailNotification` row is created for that `(user, alert_company)` pair and — using the default console/log backend — is logged and marked `"sent"`. The match-and-notify step is idempotent (never double-notifies the same pair, enforced by both a pre-check query and a DB unique constraint) and resilient (one email failing is marked `"failed"` and never blocks the rest of the batch).
- `GET /api/alerts` returns `"in_my_holdings": true` for a company an authenticated caller holds, and `false` for everyone else (including anonymous callers, who never receive an error) — the backend groundwork for Plan 4's "My Demat" tab.
- This plan deliberately excludes, documented as future work (not silently dropped): the CRED-style React UI + WebSocket live push (Plan 4); real broker/demat integration (Zerodha Kite Connect) — manual/CSV entry is the built fallback path; and a real transactional email provider (Resend/SendGrid) — the console backend stands in, with a loud `NotImplementedError` stub where the real HTTP implementation would go, so it can never silently pretend to send.
