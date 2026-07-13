# Account Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace NewsFlo's logout-only account sheet with a full `/account` page covering profile, preferences, watchlist, holdings link, password change, and account deletion.

**Architecture:** Backend adds one column (`User.email_alerts_enabled`) and four endpoints under `/api/auth`. Frontend adds one page (`AccountPage.tsx`) reusing existing components (`LanguagePicker`, `ThemeToggle`, `WatchlistSettings`), wires it behind `RequireAuth` at `/account`, and repoints the mobile/desktop nav account affordances at that route instead of the current logout-only sheet/inline button.

**Tech Stack:** FastAPI + SQLAlchemy + pytest (backend), React + TypeScript + React Router + Vitest/RTL (frontend), Tailwind for styling.

## Global Constraints

- Every new i18n key must include all 10 languages: `en, hi, mr, gu, ml, te, ta, kn, pa, bn` — copy the `CATALOG` entry shape exactly (see `frontend/src/lib/i18n.ts:29-425`).
- Follow existing Tailwind class conventions verbatim: form inputs use `rounded-lg border border-hairline bg-surface px-3 py-2 text-ink outline-none focus:border-muted theme-light:border-transparent theme-light:shadow-neu-inset`; primary buttons use `rounded-lg border border-hairline bg-surface px-4 py-2 text-xs uppercase tracking-widest text-ink disabled:opacity-50 theme-light:border-transparent theme-light:bg-accent theme-light:text-page theme-light:shadow-neu`; error text uses `role="alert" className="text-xs text-bearish"`.
- Password length constraint mirrors `AuthRequest`: `min_length=1, max_length=72` (bcrypt's byte limit).
- No migration tool exists in this repo (`backend/app/db.py`: `create_all` only creates missing tables, never adds columns). Tests use a fresh in-memory sqlite DB per test (`backend/tests/conftest.py`), so this doesn't affect tests — it only means a real local dev DB file needs recreating after this change.
- Do not modify `frontend/src/components/Feed.tsx`'s existing `WatchlistSettings` mount (the "Custom tab" gear-icon flow) — the account page adds a second, independent mount of the same component.

---

### Task 1: `User.email_alerts_enabled` column + model test

**Files:**
- Modify: `backend/app/models.py:101-107` (the `User` class)
- Test: `backend/tests/test_models.py`

**Interfaces:**
- Produces: `User.email_alerts_enabled: bool`, defaults to `True` for both ORM-level default and DB-level default.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_models.py`:

```python
def test_user_email_alerts_enabled_defaults_true(db_session):
    from app.models import User
    user = User(email="prefs@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    assert user.email_alerts_enabled is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_models.py::test_user_email_alerts_enabled_defaults_true -v`
Expected: FAIL with `AttributeError: 'User' object has no attribute 'email_alerts_enabled'`

- [ ] **Step 3: Add the column**

In `backend/app/models.py`, add `Boolean` to the existing sqlalchemy import (line 3) and add the column to `User`:

```python
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
```

```python
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, nullable=False, unique=True)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    email_alerts_enabled = Column(Boolean, nullable=False, default=True, server_default="1")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_models.py::test_user_email_alerts_enabled_defaults_true -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/tests/test_models.py
git commit -m "feat: add email_alerts_enabled column to User"
```

---

### Task 2: `GET /api/auth/me` and `PATCH /api/auth/me`

**Files:**
- Modify: `backend/app/routers/auth.py`
- Test: `backend/tests/test_auth_api.py`

**Interfaces:**
- Consumes: `get_current_user` from `app.auth.dependencies` (`backend/app/auth/dependencies.py:10`), `get_db` from `app.routers.articles` (already imported in `auth.py`).
- Produces: `GET /api/auth/me` → `{id: int, email: str, created_at: str, email_alerts_enabled: bool}`. `PATCH /api/auth/me` → same shape, body `{email_alerts_enabled: bool}`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_auth_api.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_auth_api.py -k "get_me or patch_me" -v`
Expected: FAIL with 404 (routes don't exist yet)

- [ ] **Step 3: Add the endpoints**

In `backend/app/routers/auth.py`, add after the existing imports:

```python
from app.auth.dependencies import get_current_user
```

Add after the existing `TokenResponse` class:

```python
class ProfileResponse(BaseModel):
    id: int
    email: str
    created_at: str
    email_alerts_enabled: bool


class PreferencesRequest(BaseModel):
    email_alerts_enabled: bool


def _serialize_profile(user: User) -> ProfileResponse:
    return ProfileResponse(
        id=user.id,
        email=user.email,
        created_at=user.created_at.isoformat(),
        email_alerts_enabled=user.email_alerts_enabled,
    )
```

Add at the end of the file:

```python
@router.get("/me", response_model=ProfileResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return _serialize_profile(current_user)


@router.patch("/me", response_model=ProfileResponse)
def patch_me(
    payload: PreferencesRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    current_user.email_alerts_enabled = payload.email_alerts_enabled
    db.commit()
    db.refresh(current_user)
    return _serialize_profile(current_user)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_auth_api.py -k "get_me or patch_me" -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/auth.py backend/tests/test_auth_api.py
git commit -m "feat: add GET/PATCH /api/auth/me profile endpoints"
```

---

### Task 3: `POST /api/auth/me/password`

**Files:**
- Modify: `backend/app/routers/auth.py`
- Test: `backend/tests/test_auth_api.py`

**Interfaces:**
- Consumes: `hash_password`, `verify_password` from `app.auth.security` (already imported in `auth.py`).
- Produces: `POST /api/auth/me/password` → 204 on success, 401 on wrong `current_password`. Body `{current_password: str, new_password: str}`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_auth_api.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_auth_api.py -k "change_password" -v`
Expected: FAIL with 404

- [ ] **Step 3: Add the endpoint**

In `backend/app/routers/auth.py`, add after `PreferencesRequest`:

```python
class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=1, max_length=72)
```

Add at the end of the file:

```python
@router.post("/me/password", status_code=204)
def change_password(
    payload: PasswordChangeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    current_user.hashed_password = hash_password(payload.new_password)
    db.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_auth_api.py -k "change_password" -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/auth.py backend/tests/test_auth_api.py
git commit -m "feat: add POST /api/auth/me/password endpoint"
```

---

### Task 4: `DELETE /api/auth/me` with cascade

**Files:**
- Modify: `backend/app/routers/auth.py`
- Test: `backend/tests/test_auth_api.py`

**Interfaces:**
- Consumes: `Holding`, `UserWatchlistCategory`, `UserWatchlistCompany`, `EmailNotification` from `app.models`.
- Produces: `DELETE /api/auth/me` → 204 on success, 401 on wrong password. Body `{password: str}`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_auth_api.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_auth_api.py -k "delete_me" -v`
Expected: FAIL with 404

- [ ] **Step 3: Add the endpoint**

In `backend/app/routers/auth.py`, add to the `app.models` import:

```python
from app.models import EmailNotification, Holding, User, UserWatchlistCategory, UserWatchlistCompany
```

Add after `PasswordChangeRequest`:

```python
class DeleteAccountRequest(BaseModel):
    password: str
```

Add at the end of the file:

```python
@router.delete("/me", status_code=204)
def delete_me(
    payload: DeleteAccountRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(payload.password, current_user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect password")
    db.query(Holding).filter_by(user_id=current_user.id).delete()
    db.query(UserWatchlistCategory).filter_by(user_id=current_user.id).delete()
    db.query(UserWatchlistCompany).filter_by(user_id=current_user.id).delete()
    db.query(EmailNotification).filter_by(user_id=current_user.id).delete()
    db.delete(current_user)
    db.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_auth_api.py -k "delete_me" -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/auth.py backend/tests/test_auth_api.py
git commit -m "feat: add DELETE /api/auth/me with cascade delete"
```

---

### Task 5: Matcher skips users with email alerts disabled

**Files:**
- Modify: `backend/app/alerting/matcher.py`
- Test: `backend/tests/test_matcher.py`

**Interfaces:**
- Consumes: `User.email_alerts_enabled` (Task 1).
- Produces: `match_alert_to_holdings` (unchanged signature) now queues nothing for a holder whose `email_alerts_enabled` is `False`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_matcher.py`:

```python
def test_matcher_skips_users_with_email_alerts_disabled(db_session):
    alert, company, ac = _seed_alert_with_company(db_session)
    user = User(email="u@example.com", hashed_password="x", email_alerts_enabled=False)
    db_session.add(user)
    db_session.commit()
    db_session.add(Holding(user_id=user.id, company_id=company.id, quantity=5.0))
    db_session.commit()

    created = match_alert_to_holdings(db_session, alert)

    assert created == []
    assert db_session.query(EmailNotification).count() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_matcher.py::test_matcher_skips_users_with_email_alerts_disabled -v`
Expected: FAIL — `created` has 1 entry (matcher doesn't check the flag yet)

- [ ] **Step 3: Update the matcher**

Replace `backend/app/alerting/matcher.py` with:

```python
from sqlalchemy.orm import Session

from app.models import Alert, EmailNotification, Holding, User


def match_alert_to_holdings(session: Session, alert: Alert) -> list[EmailNotification]:
    """For each company in ``alert``, find every user holding that company and
    queue a pending EmailNotification for the ``(user, alert_company)`` pair,
    unless one already exists. Returns only the newly created notifications.

    The pre-check query is a second layer of idempotency on top of the DB unique
    constraint (mirrors the outcome tracker in Plan 2), so re-running the matcher
    for the same alert never double-notifies the same user for the same
    alert-company match. Users who have turned off email alerts (Account page
    preference) are skipped entirely -- no notification row is queued for them.
    """
    created: list[EmailNotification] = []
    for alert_company in alert.companies:
        holdings = (
            session.query(Holding)
            .join(User, Holding.user_id == User.id)
            .filter(Holding.company_id == alert_company.company_id)
            .filter(User.email_alerts_enabled.is_(True))
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_matcher.py -v`
Expected: PASS (all tests, including the 3 pre-existing ones)

- [ ] **Step 5: Commit**

```bash
git add backend/app/alerting/matcher.py backend/tests/test_matcher.py
git commit -m "feat: skip queuing email notifications for opted-out users"
```

---

### Task 6: Frontend API client functions

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Test: none (thin fetch wrappers, covered indirectly by `AccountPage.test.tsx` in Task 9 mocking these functions, matching the existing convention where `WatchlistSettings.test.tsx` mocks `getWatchlist`/`putWatchlist` without a separate `api.test.ts`)

**Interfaces:**
- Produces:
  - `interface Profile { id: number; email: string; created_at: string; email_alerts_enabled: boolean }`
  - `getMe(token: string): Promise<Profile>`
  - `updatePreferences(token: string, emailAlertsEnabled: boolean): Promise<Profile>`
  - `changePassword(token: string, currentPassword: string, newPassword: string): Promise<void>`
  - `deleteAccount(token: string, password: string): Promise<void>`

- [ ] **Step 1: Add the types and functions**

In `frontend/src/lib/api.ts`, add after the `Watchlist` interface (after line 111):

```typescript
export interface Profile {
  id: number;
  email: string;
  created_at: string;
  email_alerts_enabled: boolean;
}
```

Add at the end of the file:

```typescript
export async function getMe(token: string): Promise<Profile> {
  const res = await fetch('/api/auth/me', { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as Profile;
}

export async function updatePreferences(token: string, emailAlertsEnabled: boolean): Promise<Profile> {
  const res = await fetch('/api/auth/me', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({ email_alerts_enabled: emailAlertsEnabled }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as Profile;
}

export async function changePassword(
  token: string,
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  const res = await fetch('/api/auth/me/password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
  if (!res.ok) throw new Error(await parseError(res));
}

export async function deleteAccount(token: string, password: string): Promise<void> {
  const res = await fetch('/api/auth/me', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({ password }),
  });
  if (!res.ok) throw new Error(await parseError(res));
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat: add account API client functions"
```

---

### Task 7: i18n keys for the account page

**Files:**
- Modify: `frontend/src/lib/i18n.ts`

**Interfaces:**
- Produces: the following new `TranslationKey`s, consumed by `AccountPage.tsx` in Task 8: `account.pageTitle`, `account.profileHeading`, `account.memberSince`, `account.preferencesHeading`, `account.languageLabel`, `account.themeLabel`, `account.emailAlertsLabel`, `account.emailAlertsHint`, `account.watchlistHeading`, `account.holdingsHeading`, `account.viewHoldings`, `account.securityHeading`, `account.currentPasswordLabel`, `account.newPasswordLabel`, `account.updatePassword`, `account.updatingPassword`, `account.passwordUpdated`, `account.dangerZoneHeading`, `account.deleteAccount`, `account.deleteWarning`, `account.deletePasswordLabel`, `account.confirmDelete`, `account.deleting`, `account.cancel`, `account.loadFailed`.

- [ ] **Step 1: Add the catalog entries**

In `frontend/src/lib/i18n.ts`, insert the following block immediately before the closing `} as const;` (currently line 425):

```typescript
  'account.pageTitle': {
    en: 'Account', hi: 'खाता', mr: 'खाते', gu: 'ખાતું', ml: 'അക്കൗണ്ട്', te: 'ఖాతా', ta: 'கணக்கு', kn: 'ಖಾತೆ',
    pa: 'ਖਾਤਾ', bn: 'অ্যাকাউন্ট',
  },
  'account.profileHeading': {
    en: 'Profile', hi: 'प्रोफ़ाइल', mr: 'प्रोफाइल', gu: 'પ્રોફાઇલ', ml: 'പ്രൊഫൈൽ', te: 'ప్రొఫైల్',
    ta: 'சுயவிவரம்', kn: 'ಪ್ರೊಫೈಲ್', pa: 'ਪ੍ਰੋਫਾਈਲ', bn: 'প্রোফাইল',
  },
  'account.memberSince': {
    en: 'Member since {date}', hi: '{date} से सदस्य', mr: '{date} पासून सदस्य', gu: '{date} થી સભ્ય',
    ml: '{date} മുതൽ അംഗം', te: '{date} నుండి సభ్యుడు', ta: '{date} முதல் உறுப்பினர்',
    kn: '{date} ರಿಂದ ಸದಸ್ಯ', pa: '{date} ਤੋਂ ਮੈਂਬਰ', bn: '{date} থেকে সদস্য',
  },
  'account.preferencesHeading': {
    en: 'Preferences', hi: 'वरीयताएं', mr: 'प्राधान्ये', gu: 'પસંદગીઓ', ml: 'മുൻഗണനകൾ',
    te: 'ప్రాధాన్యతలు', ta: 'விருப்பங்கள்', kn: 'ಆದ್ಯತೆಗಳು', pa: 'ਤਰਜੀਹਾਂ', bn: 'পছন্দসমূহ',
  },
  'account.languageLabel': {
    en: 'Language', hi: 'भाषा', mr: 'भाषा', gu: 'ભાષા', ml: 'ഭാഷ', te: 'భాష', ta: 'மொழி', kn: 'ಭಾಷೆ',
    pa: 'ਭਾਸ਼ਾ', bn: 'ভাষা',
  },
  'account.themeLabel': {
    en: 'Theme', hi: 'थीम', mr: 'थीम', gu: 'થીમ', ml: 'തീം', te: 'థీమ్', ta: 'தீம்', kn: 'ಥೀಮ್',
    pa: 'ਥੀਮ', bn: 'থিম',
  },
  'account.emailAlertsLabel': {
    en: 'Email alerts', hi: 'ईमेल अलर्ट', mr: 'ईमेल अलर्ट', gu: 'ઇમેઇલ અલર્ટ', ml: 'ഇമെയിൽ അലേർട്ടുകൾ',
    te: 'ఇమెయిల్ అలర్ట్‌లు', ta: 'மின்னஞ்சல் விழிப்பூட்டல்கள்', kn: 'ಇಮೇಲ್ ಎಚ್ಚರಿಕೆಗಳು',
    pa: 'ਈਮੇਲ ਅਲਰਟ', bn: 'ইমেইল সতর্কতা',
  },
  'account.emailAlertsHint': {
    en: 'Get an email when a company you hold is mentioned in the news.',
    hi: 'जब आपकी होल्डिंग वाली किसी कंपनी की खबर आए तो ईमेल पाएं।',
    mr: 'तुमच्या होल्डिंगमधील कंपनीची बातमी आल्यास ईमेल मिळवा.',
    gu: 'તમારી હોલ્ડિંગની કંપનીના સમાચાર આવે ત્યારે ઇમેઇલ મેળવો.',
    ml: 'നിങ്ങളുടെ ഹോൾഡിംഗിലുള്ള ഒരു കമ്പനിയെക്കുറിച്ചുള്ള വാർത്ത വരുമ്പോൾ ഇമെയിൽ നേടുക.',
    te: 'మీ హోల్డింగ్‌లోని కంపెనీ గురించి వార్త వచ్చినప్పుడు ఇమెయిల్ పొందండి.',
    ta: 'நீங்கள் வைத்திருக்கும் நிறுவனம் பற்றிய செய்தி வரும்போது மின்னஞ்சல் பெறுங்கள்.',
    kn: 'ನಿಮ್ಮ ಹೋಲ್ಡಿಂಗ್‌ನಲ್ಲಿರುವ ಕಂಪನಿಯ ಸುದ್ದಿ ಬಂದಾಗ ಇಮೇಲ್ ಪಡೆಯಿರಿ.',
    pa: 'ਜਦੋਂ ਤੁਹਾਡੀ ਹੋਲਡਿੰਗ ਵਾਲੀ ਕੰਪਨੀ ਦੀ ਖ਼ਬਰ ਆਵੇ ਤਾਂ ਈਮੇਲ ਪ੍ਰਾਪਤ ਕਰੋ।',
    bn: 'আপনার হোল্ডিংয়ে থাকা কোম্পানির খবর এলে ইমেইল পান।',
  },
  'account.watchlistHeading': {
    en: 'Watchlist', hi: 'वॉचलिस्ट', mr: 'वॉचलिस्ट', gu: 'વોચલિસ્ટ', ml: 'വാച്ച്‌ലിസ്റ്റ്', te: 'వాచ్‌లిస్ట్',
    ta: 'கண்காணிப்பு பட்டியல்', kn: 'ವಾಚ್‌ಲಿಸ್ಟ್', pa: 'ਵਾਚਲਿਸਟ', bn: 'ওয়াচলিস্ট',
  },
  'account.holdingsHeading': {
    en: 'Holdings', hi: 'होल्डिंग्स', mr: 'होल्डिंग्स', gu: 'હોલ્ડિંગ્સ', ml: 'ഹോൾഡിംഗുകൾ',
    te: 'హోల్డింగ్‌లు', ta: 'முதலீடுகள்', kn: 'ಹೋಲ್ಡಿಂಗ್‌ಗಳು', pa: 'ਹੋਲਡਿੰਗਸ', bn: 'হোল্ডিংস',
  },
  'account.viewHoldings': {
    en: 'View holdings', hi: 'होल्डिंग्स देखें', mr: 'होल्डिंग्स पहा', gu: 'હોલ્ડિંગ્સ જુઓ',
    ml: 'ഹോൾഡിംഗുകൾ കാണുക', te: 'హోల్డింగ్‌లను చూడండి', ta: 'முதலீடுகளைப் பார்க்கவும்',
    kn: 'ಹೋಲ್ಡಿಂಗ್‌ಗಳನ್ನು ವೀಕ್ಷಿಸಿ', pa: 'ਹੋਲਡਿੰਗਸ ਵੇਖੋ', bn: 'হোল্ডিংস দেখুন',
  },
  'account.securityHeading': {
    en: 'Security', hi: 'सुरक्षा', mr: 'सुरक्षा', gu: 'સુરક્ષા', ml: 'സുരക്ഷ', te: 'భద్రత', ta: 'பாதுகாப்பு',
    kn: 'ಭದ್ರತೆ', pa: 'ਸੁਰੱਖਿਆ', bn: 'নিরাপত্তা',
  },
  'account.currentPasswordLabel': {
    en: 'Current password', hi: 'वर्तमान पासवर्ड', mr: 'सध्याचा पासवर्ड', gu: 'વર્તમાન પાસવર્ડ',
    ml: 'നിലവിലെ പാസ്‌വേഡ്', te: 'ప్రస్తుత పాస్‌వర్డ్', ta: 'தற்போதைய கடவுச்சொல்',
    kn: 'ಪ್ರಸ್ತುತ ಪಾಸ್‌ವರ್ಡ್', pa: 'ਮੌਜੂਦਾ ਪਾਸਵਰਡ', bn: 'বর্তমান পাসওয়ার্ড',
  },
  'account.newPasswordLabel': {
    en: 'New password', hi: 'नया पासवर्ड', mr: 'नवीन पासवर्ड', gu: 'નવો પાસવર્ડ', ml: 'പുതിയ പാസ്‌വേഡ്',
    te: 'కొత్త పాస్‌వర్డ్', ta: 'புதிய கடவுச்சொல்', kn: 'ಹೊಸ ಪಾಸ್‌ವರ್ಡ್', pa: 'ਨਵਾਂ ਪਾਸਵਰਡ',
    bn: 'নতুন পাসওয়ার্ড',
  },
  'account.updatePassword': {
    en: 'Update password', hi: 'पासवर्ड अपडेट करें', mr: 'पासवर्ड अपडेट करा', gu: 'પાસવર્ડ અપડેટ કરો',
    ml: 'പാസ്‌വേഡ് അപ്‌ഡേറ്റ് ചെയ്യുക', te: 'పాస్‌వర్డ్‌ను అప్‌డేట్ చేయండి', ta: 'கடவுச்சொல்லைப் புதுப்பிக்கவும்',
    kn: 'ಪಾಸ್‌ವರ್ಡ್ ನವೀಕರಿಸಿ', pa: 'ਪਾਸਵਰਡ ਅੱਪਡੇਟ ਕਰੋ', bn: 'পাসওয়ার্ড আপডেট করুন',
  },
  'account.updatingPassword': {
    en: 'Updating…', hi: 'अपडेट हो रहा है…', mr: 'अपडेट होत आहे…', gu: 'અપડેટ થઈ રહ્યું છે…',
    ml: 'അപ്‌ഡേറ്റ് ചെയ്യുന്നു…', te: 'అప్‌డేట్ అవుతోంది…', ta: 'புதுப்பிக்கிறது…',
    kn: 'ನವೀಕರಿಸಲಾಗುತ್ತಿದೆ…', pa: 'ਅੱਪਡੇਟ ਹੋ ਰਿਹਾ ਹੈ…', bn: 'আপডেট হচ্ছে…',
  },
  'account.passwordUpdated': {
    en: 'Password updated.', hi: 'पासवर्ड अपडेट हो गया।', mr: 'पासवर्ड अपडेट झाला.', gu: 'પાસવર્ડ અપડેટ થયો.',
    ml: 'പാസ്‌വേഡ് അപ്‌ഡേറ്റ് ചെയ്തു.', te: 'పాస్‌వర్డ్ అప్‌డేట్ చేయబడింది.', ta: 'கடவுச்சொல் புதுப்பிக்கப்பட்டது.',
    kn: 'ಪಾಸ್‌ವರ್ಡ್ ನವೀಕರಿಸಲಾಗಿದೆ.', pa: 'ਪਾਸਵਰਡ ਅੱਪਡੇਟ ਹੋ ਗਿਆ।', bn: 'পাসওয়ার্ড আপডেট হয়েছে।',
  },
  'account.dangerZoneHeading': {
    en: 'Danger zone', hi: 'खतरे का क्षेत्र', mr: 'धोक्याचे क्षेत्र', gu: 'જોખમી ઝોન', ml: 'അപകട മേഖല',
    te: 'ప్రమాద జోన్', ta: 'ஆபத்து மண்டலம்', kn: 'ಅಪಾಯದ ವಲಯ', pa: 'ਖ਼ਤਰੇ ਦਾ ਖੇਤਰ', bn: 'বিপজ্জনক অঞ্চল',
  },
  'account.deleteAccount': {
    en: 'Delete account', hi: 'खाता हटाएं', mr: 'खाते हटवा', gu: 'ખાતું કાઢી નાખો', ml: 'അക്കൗണ്ട് ഇല്ലാതാക്കുക',
    te: 'ఖాతాను తొలగించండి', ta: 'கணக்கை நீக்கு', kn: 'ಖಾತೆ ಅಳಿಸಿ', pa: 'ਖਾਤਾ ਮਿਟਾਓ', bn: 'অ্যাকাউন্ট মুছুন',
  },
  'account.deleteWarning': {
    en: 'This permanently deletes your holdings, watchlist, and account. This cannot be undone.',
    hi: 'यह आपकी होल्डिंग्स, वॉचलिस्ट और खाता स्थायी रूप से हटा देगा। इसे पूर्ववत नहीं किया जा सकता।',
    mr: 'हे तुमचे होल्डिंग्स, वॉचलिस्ट आणि खाते कायमचे हटवेल. हे पूर्ववत करता येणार नाही.',
    gu: 'આ તમારા હોલ્ડિંગ્સ, વોચલિસ્ટ અને ખાતું કાયમ માટે ડિલીટ કરશે. આ પાછું લઈ શકાશે નહીં.',
    ml: 'ഇത് നിങ്ങളുടെ ഹോൾഡിംഗുകൾ, വാച്ച്‌ലിസ്റ്റ്, അക്കൗണ്ട് എന്നിവ ശാശ്വതമായി ഇല്ലാതാക്കും. ഇത് പഴയപടിയാക്കാനാവില്ല.',
    te: 'ఇది మీ హోల్డింగ్‌లు, వాచ్‌లిస్ట్, ఖాతాను శాశ్వతంగా తొలగిస్తుంది. దీన్ని వెనక్కి తీసుకోలేరు.',
    ta: 'இது உங்கள் முதலீடுகள், கண்காணிப்பு பட்டியல் மற்றும் கணக்கை நிரந்தரமாக நீக்கும். இதைச் செயல்தவிர்க்க முடியாது.',
    kn: 'ಇದು ನಿಮ್ಮ ಹೋಲ್ಡಿಂಗ್‌ಗಳು, ವಾಚ್‌ಲಿಸ್ಟ್ ಮತ್ತು ಖಾತೆಯನ್ನು ಶಾಶ್ವತವಾಗಿ ಅಳಿಸುತ್ತದೆ. ಇದನ್ನು ರದ್ದುಗೊಳಿಸಲಾಗುವುದಿಲ್ಲ.',
    pa: 'ਇਹ ਤੁਹਾਡੀਆਂ ਹੋਲਡਿੰਗਸ, ਵਾਚਲਿਸਟ ਅਤੇ ਖਾਤੇ ਨੂੰ ਸਥਾਈ ਤੌਰ \'ਤੇ ਮਿਟਾ ਦੇਵੇਗਾ। ਇਸਨੂੰ ਵਾਪਸ ਨਹੀਂ ਲਿਆ ਜਾ ਸਕਦਾ।',
    bn: 'এটি আপনার হোল্ডিংস, ওয়াচলিস্ট এবং অ্যাকাউন্ট স্থায়ীভাবে মুছে ফেলবে। এটি পূর্বাবস্থায় ফেরানো যাবে না।',
  },
  'account.deletePasswordLabel': {
    en: 'Enter your password to confirm', hi: 'पुष्टि के लिए अपना पासवर्ड दर्ज करें',
    mr: 'पुष्टीसाठी तुमचा पासवर्ड टाका', gu: 'પુષ્ટિ કરવા માટે તમારો પાસવર્ડ દાખલ કરો',
    ml: 'സ്ഥിരീകരിക്കാൻ നിങ്ങളുടെ പാസ്‌വേഡ് നൽകുക', te: 'నిర్ధారించడానికి మీ పాస్‌వర్డ్‌ను నమోదు చేయండి',
    ta: 'உறுதிப்படுத்த உங்கள் கடவுச்சொல்லை உள்ளிடவும்', kn: 'ಖಚಿತಪಡಿಸಲು ನಿಮ್ಮ ಪಾಸ್‌ವರ್ಡ್ ನಮೂದಿಸಿ',
    pa: 'ਪੁਸ਼ਟੀ ਲਈ ਆਪਣਾ ਪਾਸਵਰਡ ਦਰਜ ਕਰੋ', bn: 'নিশ্চিত করতে আপনার পাসওয়ার্ড লিখুন',
  },
  'account.confirmDelete': {
    en: 'Delete my account', hi: 'मेरा खाता हटाएं', mr: 'माझे खाते हटवा', gu: 'મારું ખાતું કાઢી નાખો',
    ml: 'എന്റെ അക്കൗണ്ട് ഇല്ലാതാക്കുക', te: 'నా ఖాతాను తొలగించండి', ta: 'எனது கணக்கை நீக்கு',
    kn: 'ನನ್ನ ಖಾತೆ ಅಳಿಸಿ', pa: 'ਮੇਰਾ ਖਾਤਾ ਮਿਟਾਓ', bn: 'আমার অ্যাকাউন্ট মুছুন',
  },
  'account.deleting': {
    en: 'Deleting…', hi: 'हटाया जा रहा है…', mr: 'हटवत आहे…', gu: 'કાઢી રહ્યાં છીએ…', ml: 'ഇല്ലാതാക്കുന്നു…',
    te: 'తొలగిస్తోంది…', ta: 'நீக்குகிறது…', kn: 'ಅಳಿಸಲಾಗುತ್ತಿದೆ…', pa: 'ਮਿਟਾਇਆ ਜਾ ਰਿਹਾ ਹੈ…', bn: 'মুছে ফেলা হচ্ছে…',
  },
  'account.cancel': {
    en: 'Cancel', hi: 'रद्द करें', mr: 'रद्द करा', gu: 'રદ કરો', ml: 'റദ്ദാക്കുക', te: 'రద్దు చేయండి',
    ta: 'ரத்து செய்', kn: 'ರದ್ದುಗೊಳಿಸಿ', pa: 'ਰੱਦ ਕਰੋ', bn: 'বাতিল করুন',
  },
  'account.loadFailed': {
    en: 'Could not load your account.', hi: 'आपका खाता लोड नहीं हो सका।', mr: 'तुमचे खाते लोड करता आले नाही.',
    gu: 'તમારું ખાતું લોડ કરી શકાયું નહીં.', ml: 'നിങ്ങളുടെ അക്കൗണ്ട് ലോഡ് ചെയ്യാൻ കഴിഞ്ഞില്ല.',
    te: 'మీ ఖాతాను లోడ్ చేయలేకపోయాము.', ta: 'உங்கள் கணக்கை ஏற்ற முடியவில்லை.',
    kn: 'ನಿಮ್ಮ ಖಾತೆಯನ್ನು ಲೋಡ್ ಮಾಡಲು ಸಾಧ್ಯವಾಗಲಿಲ್ಲ.', pa: 'ਤੁਹਾਡਾ ਖਾਤਾ ਲੋਡ ਨਹੀਂ ਹੋ ਸਕਿਆ।',
    bn: 'আপনার অ্যাকাউন্ট লোড করা যায়নি।',
  },
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/i18n.ts
git commit -m "feat: add account page i18n keys"
```

---

### Task 8: `AccountPage.tsx` component

**Files:**
- Create: `frontend/src/pages/AccountPage.tsx`

**Interfaces:**
- Consumes: `useAuth()` (`frontend/src/lib/auth.tsx:69`, exposes `token: string | null`, `email: string | null`, `logout: () => void`), `useLanguage()` (`frontend/src/lib/language.tsx:43`), `getMe`/`updatePreferences`/`changePassword`/`deleteAccount` (Task 6), `Profile` type (Task 6), `LanguagePicker` (`frontend/src/components/LanguagePicker.tsx`), `ThemeToggle` (`frontend/src/components/ThemeToggle.tsx`), `WatchlistSettings` (`frontend/src/components/WatchlistSettings.tsx`).
- Produces: default export `AccountPage`, mounted at `/account` in Task 10.

- [ ] **Step 1: Write the component**

Create `frontend/src/pages/AccountPage.tsx`:

```tsx
import { useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  changePassword,
  deleteAccount,
  getMe,
  updatePreferences,
  type Profile,
} from '../lib/api';
import { useAuth } from '../lib/auth';
import { useLanguage } from '../lib/language';
import LanguagePicker from '../components/LanguagePicker';
import ThemeToggle from '../components/ThemeToggle';
import WatchlistSettings from '../components/WatchlistSettings';

function formatMemberSince(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

export default function AccountPage() {
  const { token, logout } = useAuth();
  const { t } = useLanguage();
  const navigate = useNavigate();

  const [profile, setProfile] = useState<Profile | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [togglingAlerts, setTogglingAlerts] = useState(false);

  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [passwordMessage, setPasswordMessage] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState(false);
  const [changingPassword, setChangingPassword] = useState(false);

  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deletePassword, setDeletePassword] = useState('');
  const [deleteMessage, setDeleteMessage] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (!token) return;
    let active = true;
    getMe(token)
      .then((p) => {
        if (active) setProfile(p);
      })
      .catch((err: unknown) => {
        if (active) setLoadError(err instanceof Error ? err.message : t('account.loadFailed'));
      });
    return () => {
      active = false;
    };
  }, [token, t]);

  async function toggleEmailAlerts() {
    if (!token || !profile) return;
    setTogglingAlerts(true);
    try {
      const updated = await updatePreferences(token, !profile.email_alerts_enabled);
      setProfile(updated);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : t('account.loadFailed'));
    } finally {
      setTogglingAlerts(false);
    }
  }

  async function handlePasswordSubmit(e: FormEvent) {
    e.preventDefault();
    if (!token) return;
    setChangingPassword(true);
    setPasswordMessage(null);
    try {
      await changePassword(token, currentPassword, newPassword);
      setPasswordError(false);
      setPasswordMessage(t('account.passwordUpdated'));
      setCurrentPassword('');
      setNewPassword('');
    } catch (err) {
      setPasswordError(true);
      setPasswordMessage(err instanceof Error ? err.message : t('account.loadFailed'));
    } finally {
      setChangingPassword(false);
    }
  }

  async function handleDeleteConfirm() {
    if (!token) return;
    setDeleting(true);
    setDeleteMessage(null);
    try {
      await deleteAccount(token, deletePassword);
      logout();
      navigate('/');
    } catch (err) {
      setDeleteMessage(err instanceof Error ? err.message : t('account.loadFailed'));
    } finally {
      setDeleting(false);
    }
  }

  return (
    <main className="mx-auto flex max-w-feed flex-col gap-6 px-4 py-8">
      <h1 className="font-display text-3xl font-bold text-ink">{t('account.pageTitle')}</h1>

      {loadError && <p role="alert" className="text-xs text-bearish">{loadError}</p>}

      <section className="flex flex-col gap-2 rounded-lg border border-hairline bg-surface p-6">
        <h2 className="text-xs uppercase tracking-widest text-muted">{t('account.profileHeading')}</h2>
        <p className="text-sm text-ink">{profile?.email}</p>
        {profile && (
          <p className="text-xs text-muted">
            {t('account.memberSince', { date: formatMemberSince(profile.created_at) })}
          </p>
        )}
      </section>

      <section className="flex flex-col gap-4 rounded-lg border border-hairline bg-surface p-6">
        <h2 className="text-xs uppercase tracking-widest text-muted">{t('account.preferencesHeading')}</h2>
        <div className="flex items-center justify-between">
          <span className="text-sm text-ink">{t('account.languageLabel')}</span>
          <LanguagePicker />
        </div>
        <div className="flex items-center justify-between">
          <span className="text-sm text-ink">{t('account.themeLabel')}</span>
          <ThemeToggle />
        </div>
        {profile && (
          <label className="flex cursor-pointer items-start justify-between gap-4">
            <span className="flex flex-col gap-1">
              <span className="text-sm text-ink">{t('account.emailAlertsLabel')}</span>
              <span className="text-xs text-muted">{t('account.emailAlertsHint')}</span>
            </span>
            <input
              type="checkbox"
              checked={profile.email_alerts_enabled}
              disabled={togglingAlerts}
              onChange={toggleEmailAlerts}
              aria-label={t('account.emailAlertsLabel')}
            />
          </label>
        )}
      </section>

      <section className="flex flex-col gap-4 rounded-lg border border-hairline bg-surface p-6">
        <h2 className="text-xs uppercase tracking-widest text-muted">{t('account.watchlistHeading')}</h2>
        <WatchlistSettings />
      </section>

      <section className="flex items-center justify-between rounded-lg border border-hairline bg-surface p-6">
        <h2 className="text-xs uppercase tracking-widest text-muted">{t('account.holdingsHeading')}</h2>
        <Link to="/holdings" className="text-sm text-ink underline">
          {t('account.viewHoldings')}
        </Link>
      </section>

      <section className="flex flex-col gap-4 rounded-lg border border-hairline bg-surface p-6">
        <h2 className="text-xs uppercase tracking-widest text-muted">{t('account.securityHeading')}</h2>
        <form onSubmit={handlePasswordSubmit} className="flex flex-col gap-4">
          <label className="flex flex-col gap-1">
            <span className="text-xs uppercase tracking-widest text-muted">
              {t('account.currentPasswordLabel')}
            </span>
            <input
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              className="rounded-lg border border-hairline bg-page px-3 py-2 text-ink outline-none focus:border-muted theme-light:border-transparent theme-light:shadow-neu-inset"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs uppercase tracking-widest text-muted">
              {t('account.newPasswordLabel')}
            </span>
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="rounded-lg border border-hairline bg-page px-3 py-2 text-ink outline-none focus:border-muted theme-light:border-transparent theme-light:shadow-neu-inset"
            />
          </label>
          {passwordMessage && (
            <p role="alert" className={`text-xs ${passwordError ? 'text-bearish' : 'text-bullish'}`}>
              {passwordMessage}
            </p>
          )}
          <button
            type="submit"
            disabled={changingPassword}
            className="self-start rounded-lg border border-hairline bg-surface px-4 py-2 text-xs uppercase tracking-widest text-ink disabled:opacity-50 theme-light:border-transparent theme-light:bg-accent theme-light:text-page theme-light:shadow-neu"
          >
            {changingPassword ? t('account.updatingPassword') : t('account.updatePassword')}
          </button>
        </form>
      </section>

      <section className="flex flex-col gap-4 rounded-lg border border-bearish/40 bg-surface p-6">
        <h2 className="text-xs uppercase tracking-widest text-bearish">{t('account.dangerZoneHeading')}</h2>
        {!deleteOpen ? (
          <button
            type="button"
            onClick={() => setDeleteOpen(true)}
            className="self-start rounded-lg border border-bearish px-4 py-2 text-xs uppercase tracking-widest text-bearish"
          >
            {t('account.deleteAccount')}
          </button>
        ) : (
          <div className="flex flex-col gap-3">
            <p className="text-xs text-muted">{t('account.deleteWarning')}</p>
            <label className="flex flex-col gap-1">
              <span className="text-xs uppercase tracking-widest text-muted">
                {t('account.deletePasswordLabel')}
              </span>
              <input
                type="password"
                value={deletePassword}
                onChange={(e) => setDeletePassword(e.target.value)}
                className="rounded-lg border border-hairline bg-page px-3 py-2 text-ink outline-none focus:border-muted theme-light:border-transparent theme-light:shadow-neu-inset"
              />
            </label>
            {deleteMessage && <p role="alert" className="text-xs text-bearish">{deleteMessage}</p>}
            <div className="flex gap-3">
              <button
                type="button"
                onClick={handleDeleteConfirm}
                disabled={deleting}
                className="rounded-lg border border-bearish bg-bearish px-4 py-2 text-xs uppercase tracking-widest text-page disabled:opacity-50"
              >
                {deleting ? t('account.deleting') : t('account.confirmDelete')}
              </button>
              <button
                type="button"
                onClick={() => {
                  setDeleteOpen(false);
                  setDeletePassword('');
                  setDeleteMessage(null);
                }}
                className="rounded-lg border border-hairline px-4 py-2 text-xs uppercase tracking-widest text-ink"
              >
                {t('account.cancel')}
              </button>
            </div>
          </div>
        )}
      </section>

      <button
        type="button"
        onClick={logout}
        className="self-start rounded-lg border border-hairline bg-surface px-4 py-2 text-xs uppercase tracking-widest text-ink theme-light:border-transparent theme-light:bg-accent theme-light:text-page theme-light:shadow-neu"
      >
        {t('nav.logout')}
      </button>
    </main>
  );
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/AccountPage.tsx
git commit -m "feat: add AccountPage component"
```

---

### Task 9: `AccountPage.test.tsx`

**Files:**
- Create: `frontend/src/pages/AccountPage.test.tsx`

**Interfaces:**
- Consumes: `AccountPage` (Task 8), mocks `getMe`, `updatePreferences`, `changePassword`, `deleteAccount` from `../lib/api`, and `getCategories`/`getCompanies`/`getWatchlist`/`putWatchlist` (needed because `WatchlistSettings` is rendered inside the page — same mocking approach as `WatchlistSettings.test.tsx`).

- [ ] **Step 1: Write the tests**

Create `frontend/src/pages/AccountPage.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
import AccountPage from './AccountPage';
import { AuthProvider } from '../lib/auth';
import { LanguageProvider } from '../lib/language';
import { ThemeProvider } from '../lib/theme';
import * as api from '../lib/api';
import type { Profile } from '../lib/api';

const profile: Profile = {
  id: 1,
  email: 'me@example.com',
  created_at: '2026-01-15T00:00:00Z',
  email_alerts_enabled: true,
};

function renderPage(ui: ReactElement = <AccountPage />) {
  localStorage.setItem('newsflo.token', 'tok');
  localStorage.setItem('newsflo.email', 'me@example.com');
  return render(
    <MemoryRouter>
      <ThemeProvider>
        <LanguageProvider>
          <AuthProvider>{ui}</AuthProvider>
        </LanguageProvider>
      </ThemeProvider>
    </MemoryRouter>,
  );
}

function mockWatchlistApis() {
  vi.spyOn(api, 'getCategories').mockResolvedValue([]);
  vi.spyOn(api, 'getCompanies').mockResolvedValue([]);
  vi.spyOn(api, 'getWatchlist').mockResolvedValue({ categories: [], companies: [] });
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  document.documentElement.classList.remove('light');
});

describe('AccountPage', () => {
  it('shows the profile email and member-since date', async () => {
    vi.spyOn(api, 'getMe').mockResolvedValue(profile);
    mockWatchlistApis();
    renderPage();
    expect(await screen.findByText('me@example.com')).toBeInTheDocument();
    expect(screen.getByText(/Jan 15, 2026/i)).toBeInTheDocument();
  });

  it('toggles email alerts', async () => {
    vi.spyOn(api, 'getMe').mockResolvedValue(profile);
    vi.spyOn(api, 'updatePreferences').mockResolvedValue({ ...profile, email_alerts_enabled: false });
    mockWatchlistApis();
    renderPage();
    const checkbox = await screen.findByRole('checkbox', { name: /email alerts/i });
    await userEvent.click(checkbox);
    await waitFor(() =>
      expect(api.updatePreferences).toHaveBeenCalledWith('tok', false),
    );
  });

  it('changes password successfully', async () => {
    vi.spyOn(api, 'getMe').mockResolvedValue(profile);
    vi.spyOn(api, 'changePassword').mockResolvedValue(undefined);
    mockWatchlistApis();
    renderPage();
    await screen.findByText('me@example.com');
    await userEvent.type(screen.getByLabelText(/current password/i), 'oldpass1');
    await userEvent.type(screen.getByLabelText(/new password/i), 'newpass2');
    await userEvent.click(screen.getByRole('button', { name: /update password/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/password updated/i);
  });

  it('shows an error when password change fails', async () => {
    vi.spyOn(api, 'getMe').mockResolvedValue(profile);
    vi.spyOn(api, 'changePassword').mockRejectedValue(new Error('Current password is incorrect'));
    mockWatchlistApis();
    renderPage();
    await screen.findByText('me@example.com');
    await userEvent.type(screen.getByLabelText(/current password/i), 'wrong');
    await userEvent.type(screen.getByLabelText(/new password/i), 'newpass2');
    await userEvent.click(screen.getByRole('button', { name: /update password/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Current password is incorrect');
  });

  it('deletes the account after confirming with a password', async () => {
    vi.spyOn(api, 'getMe').mockResolvedValue(profile);
    vi.spyOn(api, 'deleteAccount').mockResolvedValue(undefined);
    mockWatchlistApis();
    renderPage();
    await screen.findByText('me@example.com');
    await userEvent.click(screen.getByRole('button', { name: /^delete account$/i }));
    await userEvent.type(screen.getByLabelText(/enter your password to confirm/i), 'mypass1');
    await userEvent.click(screen.getByRole('button', { name: /delete my account/i }));
    await waitFor(() => expect(api.deleteAccount).toHaveBeenCalledWith('tok', 'mypass1'));
    expect(localStorage.getItem('newsflo.token')).toBeNull();
  });

  it('renders the watchlist settings form', async () => {
    vi.spyOn(api, 'getMe').mockResolvedValue(profile);
    mockWatchlistApis();
    renderPage();
    expect(await screen.findByRole('form', { name: /custom filters/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests**

Run: `cd frontend && npx vitest run src/pages/AccountPage.test.tsx`
Expected: PASS (6 tests)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/AccountPage.test.tsx
git commit -m "test: add AccountPage coverage"
```

---

### Task 10: Route `/account` in `App.tsx`

**Files:**
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `AccountPage` (Task 8), existing `RequireAuth` (`frontend/src/App.tsx:11-15`).

- [ ] **Step 1: Add the route**

In `frontend/src/App.tsx`, add the import:

```tsx
import AccountPage from './pages/AccountPage';
```

Add the route inside `<Routes>`, after the `/holdings` route:

```tsx
        <Route
          path="/account"
          element={
            <RequireAuth>
              <AccountPage />
            </RequireAuth>
          }
        />
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat: wire /account route"
```

---

### Task 11: Point `NavBar.tsx` at `/account`

**Files:**
- Modify: `frontend/src/components/NavBar.tsx`
- Modify: `frontend/src/components/NavBar.test.tsx`

**Interfaces:**
- Consumes: `useAuth()` (unchanged), `Link` from `react-router-dom` (already imported).

- [ ] **Step 1: Update the failing test first**

In `frontend/src/components/NavBar.test.tsx`, replace the test at lines 35-41:

```tsx
  it('links to /account when logged in', () => {
    localStorage.setItem('newsflo.token', 'tok');
    localStorage.setItem('newsflo.email', 'me@example.com');
    renderNav();
    expect(screen.getByRole('link', { name: /account/i })).toHaveAttribute('href', '/account');
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/NavBar.test.tsx`
Expected: FAIL — no `/account` link exists yet (current markup shows email text + Logout button instead)

- [ ] **Step 3: Update the component**

Replace `frontend/src/components/NavBar.tsx` lines 1-50 with:

```tsx
import { Link } from 'react-router-dom';
import { useAuth } from '../lib/auth';
import { useLanguage } from '../lib/language';
import LanguagePicker from './LanguagePicker';
import ThemeToggle from './ThemeToggle';

export default function NavBar() {
  const { token } = useAuth();
  const { t } = useLanguage();
  return (
    <nav className="border-b border-hairline bg-page">
      <div className="mx-auto flex h-14 max-w-feed items-center justify-between px-4 md:h-auto md:py-4">
        <Link to="/" className="font-display text-lg font-bold text-ink">
          NewsFlo
        </Link>
        <div className="hidden items-center gap-6 md:flex">
          <Link to="/" className="text-xs uppercase tracking-widest text-muted hover:text-ink">
            {t('nav.feed')}
          </Link>
          <Link to="/holdings" className="text-xs uppercase tracking-widest text-muted hover:text-ink">
            {t('nav.holdings')}
          </Link>
        </div>
        <div className="flex items-center gap-4 text-xs uppercase tracking-widest">
          <LanguagePicker />
          <ThemeToggle />
          <div className="hidden items-center gap-4 md:flex">
            {token ? (
              <Link to="/account" className="text-ink hover:text-muted">
                {t('nav.account')}
              </Link>
            ) : (
              <>
                <Link to="/login" className="text-ink hover:text-muted">
                  {t('nav.login')}
                </Link>
                <Link to="/register" className="text-ink hover:text-muted">
                  {t('nav.register')}
                </Link>
              </>
            )}
          </div>
        </div>
      </div>
    </nav>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/NavBar.test.tsx`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/NavBar.tsx frontend/src/components/NavBar.test.tsx
git commit -m "feat: point desktop nav account link at /account"
```

---

### Task 12: Point `BottomNav.tsx` at `/account`, remove the logout-only sheet

**Files:**
- Modify: `frontend/src/components/BottomNav.tsx`
- Modify: `frontend/src/components/BottomNav.test.tsx`

**Interfaces:**
- Consumes: `useAuth()` (only `token` needed now — `email`/`logout` move to `AccountPage`), `Link` from `react-router-dom`.

- [ ] **Step 1: Update the failing tests first**

Replace `frontend/src/components/BottomNav.test.tsx` lines 41-61 with:

```tsx
  it('links Account to /login when logged out', () => {
    renderNav();
    expect(screen.getByRole('link', { name: /account/i })).toHaveAttribute('href', '/login');
  });

  it('links Account to /account when logged in', () => {
    setToken();
    renderNav();
    expect(screen.getByRole('link', { name: /account/i })).toHaveAttribute('href', '/account');
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/BottomNav.test.tsx`
Expected: FAIL — logged-in state currently renders a `<button>`, not a `<link>`

- [ ] **Step 3: Update the component**

Replace `frontend/src/components/BottomNav.tsx` with:

```tsx
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../lib/auth';
import type { TranslationKey } from '../lib/i18n';
import { useLanguage } from '../lib/language';

const LINKS: { to: string; labelKey: TranslationKey }[] = [
  { to: '/', labelKey: 'nav.feed' },
  { to: '/holdings', labelKey: 'nav.holdings' },
];

export default function BottomNav() {
  const { pathname } = useLocation();
  const { token } = useAuth();
  const { t } = useLanguage();

  const itemClass = (activeCondition: boolean) =>
    `flex flex-1 items-center justify-center text-xs uppercase tracking-widest ${
      activeCondition ? 'text-ink' : 'text-muted'
    }`;

  return (
    <nav className="fixed inset-x-0 bottom-0 z-40 flex h-14 border-t border-hairline bg-page md:hidden">
      {LINKS.map((l) => (
        <Link key={l.to} to={l.to} className={itemClass(pathname === l.to)}>
          {t(l.labelKey)}
        </Link>
      ))}
      <Link
        to={token ? '/account' : '/login'}
        className={itemClass(pathname === '/account' || pathname === '/login')}
      >
        {t('nav.account')}
      </Link>
    </nav>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/BottomNav.test.tsx`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/BottomNav.tsx frontend/src/components/BottomNav.test.tsx
git commit -m "feat: point mobile nav account link at /account, drop logout-only sheet"
```

---

### Task 13: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend suite**

Run: `cd backend && python -m pytest -v`
Expected: all tests PASS, no regressions

- [ ] **Step 2: Run the full frontend suite**

Run: `cd frontend && npx vitest run`
Expected: all tests PASS, no regressions

- [ ] **Step 3: Type-check the frontend**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 4: Manually verify in the browser**

Start both servers per the project's existing dev workflow, register/log in, and confirm:
- Desktop: clicking "Account" in `NavBar` navigates to `/account`.
- Mobile viewport: tapping "Account" in `BottomNav` navigates to `/account` (not a sheet).
- The account page shows email + member-since, language/theme controls work, watchlist form loads and saves, "View holdings" navigates to `/holdings`, password change round-trips (change then log out/in with the new password), and delete-account (on a throwaway test account) logs the user out and redirects to `/`.

No commit for this task — it's a verification gate before considering the plan complete.
