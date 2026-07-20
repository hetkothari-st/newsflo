# TheNewsAPI Ingestion Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace IndianAPI (currently quota-exhausted, production feed empty) with `thenewsapi.com` as the active news ingestion source.

**Architecture:** New `app/ingestion/thenewsapi.py` mirrors the existing `app/ingestion/indianapi.py::fetch_new_indianapi_articles` closely (same dedupe-by-url insert loop, same "never raise, degrade to 0" contract), differing only in auth mechanism (query param vs header) and response shape (`{"data": [...]}` wrapper vs bare array). `scheduler.py` swaps the IndianAPI job for a new `thenewsapi` job, disabling (not deleting) IndianAPI's wiring — the same convention already used in this file for the disabled RSS poller.

**Tech Stack:** Python/FastAPI backend, `httpx` (already a dependency), SQLAlchemy, `pydantic-settings`, `apscheduler`, pytest.

## Global Constraints

- Design spec: `docs/superpowers/specs/2026-07-20-thenewsapi-ingestion-source-design.md`.
- Every new network-calling function follows this codebase's "never raise, degrade to a safe default" contract — see `app/ingestion/indianapi.py`, the direct precedent this mirrors.
- A missing/empty API token must return `0` **without making an HTTP request** — the 100-request/day free tier makes an accidental unauthenticated call worth guarding against explicitly (same as IndianAPI's own key check).
- `categories=business,politics,general,tech` only — do not broaden to the full generic category set (sports/entertainment/health/science/food/travel) in this plan; that's explicitly deferred to the relevance-filter rework (a separate, not-yet-started sub-project).
- IndianAPI is disabled, not deleted — comment out its import and scheduler wiring with an explanatory note pointing at this design doc, exactly mirroring how `scheduler.py` already disables the RSS poller (comment block right above the RSS import).
- The real `THENEWSAPI_API_KEY` value is never written to any file in this plan (tests use a fake token string) — it gets set directly as a Railway environment variable as a deploy step, not committed to git.

---

## File Structure

- Create: `backend/app/ingestion/thenewsapi.py` — `fetch_new_thenewsapi_articles(session, api_token)`.
- Create: `backend/tests/test_thenewsapi.py`.
- Modify: `backend/app/config.py` — `thenewsapi_api_key`, `thenewsapi_poll_interval_minutes`.
- Modify: `backend/app/scheduler.py` — disable IndianAPI wiring, add `_run_thenewsapi_ingestion` + its job registration.

---

## Task 1: `fetch_new_thenewsapi_articles`

**Files:**
- Create: `backend/app/ingestion/thenewsapi.py`
- Create: `backend/tests/test_thenewsapi.py`

**Interfaces:**
- Produces: `fetch_new_thenewsapi_articles(session: Session, api_token: str) -> int`, used by Task 2's `_run_thenewsapi_ingestion`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_thenewsapi.py`. This mirrors `backend/tests/test_indianapi.py`'s exact structure — same `_fake_response`/`_item` helper pattern — adapted for thenewsapi's two real mechanical differences: auth via `params=` (not `headers=`), and the response body being `{"meta": {...}, "data": [...]}` (not a bare array):

```python
from types import SimpleNamespace

import httpx

from app.ingestion.thenewsapi import fetch_new_thenewsapi_articles
from app.models import Article


def _fake_response(data, status_ok=True):
    def raise_for_status():
        if not status_ok:
            raise httpx.HTTPStatusError("500", request=None, response=None)
    body = {"meta": {"found": len(data), "returned": len(data), "limit": 3, "page": 1}, "data": data}
    return SimpleNamespace(raise_for_status=raise_for_status, json=lambda: body)


def _item(**overrides):
    item = {
        "title": "Reliance Industries Q1 Results Live",
        "description": "RIL Q1FY27 results announced today.",
        "url": "https://www.livemint.com/market/ril-q1-results",
        "image_url": "https://www.livemint.com/img/ril.jpg",
        "published_at": "2026-07-20T05:13:00.000000Z",
        "source": "livemint.com",
    }
    item.update(overrides)
    return item


def test_fetch_new_thenewsapi_articles_inserts_and_dedupes(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.thenewsapi.httpx.get",
        lambda url, params=None, timeout=None: _fake_response([_item()]),
    )

    inserted = fetch_new_thenewsapi_articles(db_session, "fake-token")
    assert inserted == 1

    article = db_session.query(Article).one()
    assert article.source == "livemint.com"
    assert article.url == "https://www.livemint.com/market/ril-q1-results"
    assert article.title == "Reliance Industries Q1 Results Live"
    assert article.content == "RIL Q1FY27 results announced today."
    assert article.image_url == "https://www.livemint.com/img/ril.jpg"
    assert article.status == "NEW"
    # 2026-07-20T05:13:00.000000Z is already UTC -- no offset inference needed.
    assert article.published_at.hour == 5
    assert article.published_at.minute == 13

    inserted_again = fetch_new_thenewsapi_articles(db_session, "fake-token")
    assert inserted_again == 0


def test_fetch_new_thenewsapi_articles_falls_back_to_generic_source_name(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.thenewsapi.httpx.get",
        lambda url, params=None, timeout=None: _fake_response([_item(source=None)]),
    )

    fetch_new_thenewsapi_articles(db_session, "fake-token")

    assert db_session.query(Article).one().source == "thenewsapi"


def test_fetch_new_thenewsapi_articles_skips_items_without_url(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.thenewsapi.httpx.get",
        lambda url, params=None, timeout=None: _fake_response([_item(url=None)]),
    )

    assert fetch_new_thenewsapi_articles(db_session, "fake-token") == 0


def test_fetch_new_thenewsapi_articles_returns_zero_without_an_api_token(db_session, monkeypatch):
    # Load-bearing: free tier is capped at 100 requests/day -- a missing
    # token must never silently fall through to a wasted call.
    called = {"n": 0}
    monkeypatch.setattr(
        "app.ingestion.thenewsapi.httpx.get",
        lambda *a, **k: called.__setitem__("n", called["n"] + 1),
    )

    assert fetch_new_thenewsapi_articles(db_session, "") == 0
    assert called["n"] == 0


def test_fetch_new_thenewsapi_articles_swallows_a_request_failure(db_session, monkeypatch):
    def raise_timeout(url, params=None, timeout=None):
        raise httpx.TimeoutException("connect timeout")

    monkeypatch.setattr("app.ingestion.thenewsapi.httpx.get", raise_timeout)

    assert fetch_new_thenewsapi_articles(db_session, "fake-token") == 0


def test_fetch_new_thenewsapi_articles_swallows_an_error_status(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.thenewsapi.httpx.get",
        lambda url, params=None, timeout=None: _fake_response([_item()], status_ok=False),
    )

    assert fetch_new_thenewsapi_articles(db_session, "fake-token") == 0


def test_fetch_new_thenewsapi_articles_swallows_a_malformed_response(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.thenewsapi.httpx.get",
        lambda url, params=None, timeout=None: SimpleNamespace(
            raise_for_status=lambda: None, json=lambda: {"error": "invalid api key"},
        ),
    )

    assert fetch_new_thenewsapi_articles(db_session, "bad-token") == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_thenewsapi.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ingestion.thenewsapi'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/ingestion/thenewsapi.py`:

```python
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.models import Article

THENEWSAPI_NEWS_URL = "https://api.thenewsapi.com/v1/news/all"
FETCH_TIMEOUT_SECONDS = 10
# Financially-relevant categories only, for now -- the full generic
# category set (sports, entertainment, health, science, food, travel) is
# deferred until the relevance-filter rework ships (see the design doc's
# "Explicitly out of scope" section); today's narrow keyword filter isn't
# equipped to reject that volume of genuinely irrelevant content cleanly.
CATEGORIES = "business,politics,general,tech"


def _parse_pub_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fetch_new_thenewsapi_articles(session: Session, api_token: str) -> int:
    """Poll thenewsapi.com's /v1/news/all endpoint for new articles across
    CATEGORIES, insert any not already seen (deduped by url, same
    convention as every other ingestion source in this package).

    A request/parse failure never raises -- skip this cycle, retry next,
    same contract as every other ingestion source. A missing api_token
    returns 0 without making a request -- the 100-request/day free-tier
    cap makes an accidental unauthenticated/wasted call worth guarding
    against explicitly, same as fetch_new_indianapi_articles's own key
    check.
    """
    if not api_token:
        return 0

    try:
        response = httpx.get(
            THENEWSAPI_NEWS_URL,
            params={"api_token": api_token, "categories": CATEGORIES, "language": "en"},
            timeout=FETCH_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError):
        return 0

    items = body.get("data") if isinstance(body, dict) else None
    if not isinstance(items, list):
        return 0

    inserted = 0
    for item in items:
        url = item.get("url")
        if not url:
            continue
        if session.query(Article).filter_by(url=url).one_or_none():
            continue
        session.add(Article(
            source=item.get("source") or "thenewsapi",
            url=url,
            title=item.get("title", ""),
            content=item.get("description", ""),
            published_at=_parse_pub_date(item.get("published_at")),
            image_url=item.get("image_url"),
            status="NEW",
        ))
        inserted += 1
    session.commit()
    return inserted
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_thenewsapi.py -v`
Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/thenewsapi.py backend/tests/test_thenewsapi.py
git commit -m "feat: add thenewsapi.com ingestion source"
```

---

## Task 2: Config + scheduler wiring (swap IndianAPI for thenewsapi)

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/scheduler.py`

**Interfaces:**
- Consumes: `fetch_new_thenewsapi_articles(session, api_token) -> int` from Task 1.
- Produces: the running scheduler polls thenewsapi on its own interval instead of IndianAPI.

- [ ] **Step 1: Add the new settings**

In `backend/app/config.py`, add these two lines right after the existing `indianapi_poll_interval_minutes` line (keep the IndianAPI settings block completely untouched — its comment accurately documents a real historical decision, not a bug):

```python
    indianapi_poll_interval_minutes: int = int(os.environ.get("INDIANAPI_POLL_INTERVAL_MINUTES", "1"))
    # News ingestion source -- replaces IndianAPI (disabled, not deleted --
    # see app/scheduler.py). See docs/superpowers/specs/2026-07-20-
    # thenewsapi-ingestion-source-design.md. Free tier: 100 requests/day,
    # 3 articles/request -- 20-minute default interval is 72 requests/day,
    # comfortably under the cap.
    thenewsapi_api_key: str = os.environ.get("THENEWSAPI_API_KEY", "")
    thenewsapi_poll_interval_minutes: int = int(os.environ.get("THENEWSAPI_POLL_INTERVAL_MINUTES", "20"))
```

- [ ] **Step 2: Disable IndianAPI's wiring in the scheduler**

In `backend/app/scheduler.py`, change the import block. Replace:

```python
from app.ingestion.indianapi import fetch_new_indianapi_articles
```

with:

```python
# IndianAPI is disabled (not deleted) -- replaced by thenewsapi.com, see
# docs/superpowers/specs/2026-07-20-thenewsapi-ingestion-source-design.md.
# Swap the fetch_new_indianapi_articles(...) call back in (and re-enable
# this import and the _run_indianapi_ingestion function below) to revert.
# from app.ingestion.indianapi import fetch_new_indianapi_articles
from app.ingestion.thenewsapi import fetch_new_thenewsapi_articles
```

Then comment out the entire `_run_indianapi_ingestion` function (find it — it's the function with the docstring starting "Poll IndianAPI's /news endpoint for fresh Indian market news") by prefixing every line with `# `, and add a new function directly after it (same file, same section):

```python
def _run_thenewsapi_ingestion() -> None:
    """Poll thenewsapi.com's /v1/news/all endpoint for fresh business/
    politics/general/tech news. Runs on its own, much longer interval
    (thenewsapi_poll_interval_minutes) rather than the fast per-minute
    analysis cycle -- this key is capped at 100 requests/day. Any failure
    is logged, never raised, same as every other scheduler job."""
    session = SessionLocal()
    try:
        inserted = fetch_new_thenewsapi_articles(session, settings.thenewsapi_api_key)
        logger.info("thenewsapi poll: %s new articles", inserted)
    except Exception:
        logger.exception("thenewsapi ingestion poll failed")
    finally:
        session.close()
```

- [ ] **Step 3: Swap the job registration**

In `backend/app/scheduler.py`'s `start_scheduler` function, replace:

```python
    scheduler.add_job(
        _run_indianapi_ingestion,
        trigger="interval",
        minutes=settings.indianapi_poll_interval_minutes,
        id="indianapi_poll",
    )
```

with:

```python
    # IndianAPI job disabled -- see the import comment above. Restore this
    # block (and re-enable _run_indianapi_ingestion) to revert.
    # scheduler.add_job(
    #     _run_indianapi_ingestion,
    #     trigger="interval",
    #     minutes=settings.indianapi_poll_interval_minutes,
    #     id="indianapi_poll",
    # )
    scheduler.add_job(
        _run_thenewsapi_ingestion,
        trigger="interval",
        minutes=settings.thenewsapi_poll_interval_minutes,
        id="thenewsapi_poll",
    )
```

- [ ] **Step 4: Run the full backend test suite**

Run: `cd backend && python -m pytest -v`
Expected: All tests PASS — in particular, confirm no test imports/calls `_run_indianapi_ingestion` or otherwise breaks from the commenting-out (a quick `grep -rn "_run_indianapi_ingestion\|fetch_new_indianapi_articles" backend --include="*.py"` before running should show only `scheduler.py`'s own now-commented lines and `indianapi.py`/`test_indianapi.py` themselves — nothing else references the disabled function).

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/app/scheduler.py
git commit -m "feat: swap thenewsapi.com in for IndianAPI as the active news source"
```

---

## Task 3: Full suite verification

**Files:** none (verification-only task).

- [ ] **Step 1: Run the full backend test suite**

Run: `cd backend && python -m pytest -v`
Expected: All tests PASS (0 failures), including all 7 of `test_thenewsapi.py` and the full `test_indianapi.py` (still present and passing, since the module itself is untouched — only its scheduler wiring is disabled).

- [ ] **Step 2: Confirm the disabled IndianAPI wiring doesn't break import/startup**

Run: `cd backend && python -c "from app import scheduler; print('import OK')"`
Expected: `import OK` — confirms the commented-out `_run_indianapi_ingestion` function and its now-unused import don't cause a syntax or `NameError` at module load time.

This step has no separate pass/fail beyond re-confirming Task 2's Step 4 result — report the full suite's pass count and confirm the plan is complete. Setting the real `THENEWSAPI_API_KEY` value as a Railway environment variable and verifying the live feed populates is a deployment step the controller (not a dispatched subagent) handles after this plan's tasks are done, per the plan's Global Constraints.
