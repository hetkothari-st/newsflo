# Finnhub Ingestion Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace thenewsapi.com with finnhub.io as the active news ingestion source, polling `general` + `merger` categories.

**Architecture:** New `app/ingestion/finnhub.py` module (`fetch_new_finnhub_articles`) mirrors the existing `fetch_new_thenewsapi_articles` shape (poll, dedupe by URL, insert `Article` rows with `status="NEW"`, never raise). thenewsapi is disabled-not-deleted in `scheduler.py`, following the same precedent already used for the indianapi→thenewsapi swap.

**Tech Stack:** Python, httpx, SQLAlchemy, pytest, APScheduler.

## Global Constraints

- Design doc: `docs/superpowers/specs/2026-07-21-finnhub-ingestion-source-design.md` — read for full rationale.
- Auth: Finnhub uses query param `token=` (already covered by `app/log_redaction.py`'s `_SECRET_QUERY_PARAM_PATTERN` — no redaction change needed).
- Endpoint: `https://finnhub.io/api/v1/news`, param `category` (one value per request, no comma-separated multi-category support) — call once for `category=general`, once for `category=merger`.
- Response: bare top-level JSON **list** (not `{"data": [...]}` like thenewsapi), items have `headline`, `summary`, `url`, `image`, `datetime` (Unix epoch **seconds**, not ISO-8601), `source`.
- `app/db.py:16`'s production `SessionLocal` is `autoflush=False` — a same-URL item returned by both categories in one call MUST be deduped via an in-memory `set()` tracked across both category loops, NOT by relying on `session.query(...)` seeing a same-call, not-yet-committed `session.add(...)` (it won't, under `autoflush=False`).
- thenewsapi stays in the codebase, disabled via comment-out in `scheduler.py` (same convention as `app/ingestion/indianapi.py`) — never delete `app/ingestion/thenewsapi.py` or its test file.
- `FINNHUB_API_KEY` must be set as a Railway env var on the `newsflo-app` service before/at deploy — never commit it, never echo it in any command output.
- Finnhub's webhook secret is explicitly out of scope — nothing in this plan reads or stores it.

---

### Task 1: `app/ingestion/finnhub.py` — fetch + insert logic

**Files:**
- Create: `backend/app/ingestion/finnhub.py`
- Test: `backend/tests/test_finnhub.py`

**Interfaces:**
- Produces: `fetch_new_finnhub_articles(session: Session, api_key: str) -> int` — polls both categories, inserts new `Article` rows (deduped by `url`, across both categories AND against existing DB rows), returns count inserted. Missing `api_key` → returns `0`, zero HTTP calls. Any request/parse failure for one category is caught and skipped; the other category still runs. Never raises.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_finnhub.py`:

```python
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.ingestion.finnhub import fetch_new_finnhub_articles
from app.models import Article


def _fake_response(items, status_ok=True):
    def raise_for_status():
        if not status_ok:
            raise httpx.HTTPStatusError("500", request=None, response=None)
    return SimpleNamespace(raise_for_status=raise_for_status, json=lambda: items)


def _item(**overrides):
    item = {
        "headline": "Reliance Industries Q1 Results Live",
        "summary": "RIL Q1FY27 results announced today.",
        "url": "https://www.livemint.com/market/ril-q1-results",
        "image": "https://www.livemint.com/img/ril.jpg",
        "datetime": int(datetime(2026, 7, 20, 5, 13, tzinfo=timezone.utc).timestamp()),
        "source": "livemint.com",
        "category": "general",
    }
    item.update(overrides)
    return item


def _autoflush_false_session():
    # Mirrors app/db.py's production SessionLocal (autoflush=False) --
    # tests/conftest.py's db_session fixture uses plain sessionmaker()
    # (autoflush=True by default), which would NOT catch a cross-category
    # dedup bug the way production actually behaves. Use this dedicated
    # session for any test that exercises dedup across the two category
    # requests within one fetch_new_finnhub_articles call.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    return Session()


def test_fetch_new_finnhub_articles_inserts_and_dedupes(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.finnhub.httpx.get",
        lambda url, params=None, timeout=None: _fake_response([_item()]),
    )

    inserted = fetch_new_finnhub_articles(db_session, "fake-key")
    # Same item returned for both "general" and "merger" categories in this
    # fake -- dedup must collapse it to 1, not insert twice.
    assert inserted == 1

    article = db_session.query(Article).one()
    assert article.source == "livemint.com"
    assert article.url == "https://www.livemint.com/market/ril-q1-results"
    assert article.title == "Reliance Industries Q1 Results Live"
    assert article.content == "RIL Q1FY27 results announced today."
    assert article.image_url == "https://www.livemint.com/img/ril.jpg"
    assert article.status == "NEW"
    assert article.published_at.hour == 5
    assert article.published_at.minute == 13

    inserted_again = fetch_new_finnhub_articles(db_session, "fake-key")
    assert inserted_again == 0


def test_fetch_new_finnhub_articles_dedupes_same_url_across_categories_under_autoflush_false():
    session = _autoflush_false_session()
    try:
        import app.ingestion.finnhub as finnhub_module
        orig_get = finnhub_module.httpx.get
        finnhub_module.httpx.get = lambda url, params=None, timeout=None: _fake_response([_item()])
        try:
            inserted = fetch_new_finnhub_articles(session, "fake-key")
        finally:
            finnhub_module.httpx.get = orig_get
        assert inserted == 1
        assert session.query(Article).count() == 1
    finally:
        session.close()


def test_fetch_new_finnhub_articles_calls_both_categories(db_session, monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params["category"])
        return _fake_response([])

    monkeypatch.setattr("app.ingestion.finnhub.httpx.get", fake_get)
    fetch_new_finnhub_articles(db_session, "fake-key")

    assert calls == ["general", "merger"]


def test_fetch_new_finnhub_articles_falls_back_to_generic_source_name(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.finnhub.httpx.get",
        lambda url, params=None, timeout=None: _fake_response([_item(source=None)]),
    )

    fetch_new_finnhub_articles(db_session, "fake-key")

    assert db_session.query(Article).one().source == "finnhub"


def test_fetch_new_finnhub_articles_skips_items_without_url(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.finnhub.httpx.get",
        lambda url, params=None, timeout=None: _fake_response([_item(url=None)]),
    )

    assert fetch_new_finnhub_articles(db_session, "fake-key") == 0


def test_fetch_new_finnhub_articles_returns_zero_without_an_api_key(db_session, monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(
        "app.ingestion.finnhub.httpx.get",
        lambda *a, **k: called.__setitem__("n", called["n"] + 1),
    )

    assert fetch_new_finnhub_articles(db_session, "") == 0
    assert called["n"] == 0


def test_fetch_new_finnhub_articles_swallows_one_category_failure_without_blocking_other(db_session, monkeypatch):
    def fake_get(url, params=None, timeout=None):
        if params["category"] == "general":
            raise httpx.TimeoutException("connect timeout")
        return _fake_response([_item()])

    monkeypatch.setattr("app.ingestion.finnhub.httpx.get", fake_get)

    assert fetch_new_finnhub_articles(db_session, "fake-key") == 1


def test_fetch_new_finnhub_articles_swallows_an_error_status(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.finnhub.httpx.get",
        lambda url, params=None, timeout=None: _fake_response([_item()], status_ok=False),
    )

    assert fetch_new_finnhub_articles(db_session, "fake-key") == 0


def test_fetch_new_finnhub_articles_swallows_a_malformed_response(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.ingestion.finnhub.httpx.get",
        lambda url, params=None, timeout=None: SimpleNamespace(
            raise_for_status=lambda: None, json=lambda: {"error": "invalid api key"},
        ),
    )

    assert fetch_new_finnhub_articles(db_session, "fake-key") == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `python -m pytest tests/test_finnhub.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ingestion.finnhub'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/ingestion/finnhub.py`:

```python
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.models import Article

FINNHUB_NEWS_URL = "https://finnhub.io/api/v1/news"
FETCH_TIMEOUT_SECONDS = 10
CATEGORIES = ("general", "merger")


def fetch_new_finnhub_articles(session: Session, api_key: str) -> int:
    """Poll finnhub.io's /v1/news endpoint across CATEGORIES, insert any
    article not already seen (deduped by url, same convention as every
    other ingestion source in this package).

    A request/parse failure for one category never raises and never
    blocks the other category -- skip that category this cycle, retry
    next, same contract as every other ingestion source. A missing
    api_key returns 0 without making any request.

    Dedup must catch a same-url item returned by both categories within
    one call, not just against previously-committed rows: production's
    SessionLocal runs with autoflush=False (app/db.py), so a
    same-call session.add(...) from an earlier category is not visible
    to a later session.query(...) in this same call. seen_urls tracks
    that in-memory.
    """
    if not api_key:
        return 0

    inserted = 0
    seen_urls: set[str] = set()
    for category in CATEGORIES:
        try:
            response = httpx.get(
                FINNHUB_NEWS_URL,
                params={"category": category, "token": api_key},
                timeout=FETCH_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            items = response.json()
        except (httpx.HTTPError, ValueError):
            continue

        if not isinstance(items, list):
            continue

        for item in items:
            url = item.get("url")
            if not url or url in seen_urls:
                continue
            if session.query(Article).filter_by(url=url).one_or_none():
                continue

            timestamp = item.get("datetime")
            published_at = (
                datetime.fromtimestamp(timestamp, tz=timezone.utc)
                if isinstance(timestamp, (int, float))
                else None
            )
            session.add(Article(
                source=item.get("source") or "finnhub",
                url=url,
                title=item.get("headline", ""),
                content=item.get("summary", ""),
                published_at=published_at,
                image_url=item.get("image"),
                status="NEW",
            ))
            seen_urls.add(url)
            inserted += 1

    session.commit()
    return inserted
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_finnhub.py -v`
Expected: PASS, all 9 tests.

- [ ] **Step 5: Run the full backend suite**

Run: `python -m pytest -q`
Expected: PASS, no regressions (all previously-passing tests still pass).

- [ ] **Step 6: Commit**

```bash
git add backend/app/ingestion/finnhub.py backend/tests/test_finnhub.py
git commit -m "feat: add fetch_new_finnhub_articles, polls finnhub.io general+merger news"
```

---

### Task 2: Config + scheduler wiring (disable thenewsapi, enable finnhub)

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/scheduler.py`

**Interfaces:**
- Consumes: `fetch_new_finnhub_articles(session: Session, api_key: str) -> int` from Task 1 (`app.ingestion.finnhub`).
- Produces: `settings.finnhub_api_key: str`, `settings.finnhub_poll_interval_minutes: int` (both read from env, same pattern as every other `Settings` field). `_run_finnhub_ingestion()` registered on the scheduler as job id `finnhub_poll`; `_run_thenewsapi_ingestion` and its `thenewsapi_poll` job are commented out (not deleted).

- [ ] **Step 1: Add Finnhub settings to `app/config.py`**

In `backend/app/config.py`, add immediately after the existing `thenewsapi_poll_interval_minutes` line (currently line 72):

```python
    # News ingestion source -- replaces thenewsapi (disabled, not deleted --
    # see app/scheduler.py). thenewsapi's 100/day cap kept exhausting
    # mid-day in production; Finnhub's free tier is 60 calls/min. See
    # docs/superpowers/specs/2026-07-21-finnhub-ingestion-source-design.md.
    finnhub_api_key: str = os.environ.get("FINNHUB_API_KEY", "")
    finnhub_poll_interval_minutes: int = int(os.environ.get("FINNHUB_POLL_INTERVAL_MINUTES", "1"))
```

`thenewsapi_api_key`/`thenewsapi_poll_interval_minutes` (lines 62-72) stay completely untouched -- their comments accurately document history and the module is disabled, not deleted.

- [ ] **Step 2: Verify config loads**

Run (from `backend/`): `python -c "from app.config import settings; print(settings.finnhub_api_key, settings.finnhub_poll_interval_minutes)"`
Expected: `` `` and `1` printed (empty key, default interval — no `FINNHUB_API_KEY` set locally).

- [ ] **Step 3: Disable thenewsapi in `app/scheduler.py`, wire in finnhub**

In `backend/app/scheduler.py`, replace this import line:

```python
from app.ingestion.thenewsapi import fetch_new_thenewsapi_articles
```

with:

```python
# thenewsapi is disabled (not deleted) -- replaced by finnhub.io, see
# docs/superpowers/specs/2026-07-21-finnhub-ingestion-source-design.md.
# Swap the fetch_new_thenewsapi_articles(...) call back in (and re-enable
# this import and the _run_thenewsapi_ingestion function below) to revert.
# from app.ingestion.thenewsapi import fetch_new_thenewsapi_articles
from app.ingestion.finnhub import fetch_new_finnhub_articles
```

Replace the entire `_run_thenewsapi_ingestion` function (currently lines 75-88):

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

with:

```python
# def _run_thenewsapi_ingestion() -> None:
#     """Poll thenewsapi.com's /v1/news/all endpoint for fresh business/
#     politics/general/tech news. Runs on its own, much longer interval
#     (thenewsapi_poll_interval_minutes) rather than the fast per-minute
#     analysis cycle -- this key is capped at 100 requests/day. Any failure
#     is logged, never raised, same as every other scheduler job."""
#     session = SessionLocal()
#     try:
#         inserted = fetch_new_thenewsapi_articles(session, settings.thenewsapi_api_key)
#         logger.info("thenewsapi poll: %s new articles", inserted)
#     except Exception:
#         logger.exception("thenewsapi ingestion poll failed")
#     finally:
#         session.close()


def _run_finnhub_ingestion() -> None:
    """Poll finnhub.io's /v1/news endpoint (general + merger categories)
    for fresh market news. Runs on its own interval
    (finnhub_poll_interval_minutes) rather than the fast per-minute
    analysis cycle. Any failure is logged, never raised, same as every
    other scheduler job."""
    session = SessionLocal()
    try:
        inserted = fetch_new_finnhub_articles(session, settings.finnhub_api_key)
        logger.info("finnhub poll: %s new articles", inserted)
    except Exception:
        logger.exception("finnhub ingestion poll failed")
    finally:
        session.close()
```

Replace the `thenewsapi_poll` job registration inside `start_scheduler`:

```python
    scheduler.add_job(
        _run_thenewsapi_ingestion,
        trigger="interval",
        minutes=settings.thenewsapi_poll_interval_minutes,
        id="thenewsapi_poll",
    )
```

with:

```python
    # thenewsapi job disabled -- see the import comment above. Restore
    # this block (and re-enable _run_thenewsapi_ingestion) to revert.
    # scheduler.add_job(
    #     _run_thenewsapi_ingestion,
    #     trigger="interval",
    #     minutes=settings.thenewsapi_poll_interval_minutes,
    #     id="thenewsapi_poll",
    # )
    scheduler.add_job(
        _run_finnhub_ingestion,
        trigger="interval",
        minutes=settings.finnhub_poll_interval_minutes,
        id="finnhub_poll",
    )
```

- [ ] **Step 4: Verify the scheduler module imports cleanly and registers the right jobs**

Run (from `backend/`):

```bash
python -c "
from app.scheduler import start_scheduler, _scheduler
start_scheduler()
print(sorted(j.id for j in _scheduler.get_jobs()))
"
```

Expected output includes `'finnhub_poll'` and does NOT include `'thenewsapi_poll'`:
`['finnhub_poll', 'outcome_tracker_1d', 'outcome_tracker_3d', 'outcome_tracker_7d', 'rss_poll', 'translation_job']`

- [ ] **Step 5: Run the full backend suite**

Run: `python -m pytest -q`
Expected: PASS, no regressions. `tests/test_thenewsapi.py` still passes unchanged (module untouched, only unwired from the scheduler).

- [ ] **Step 6: Commit**

```bash
git add backend/app/config.py backend/app/scheduler.py
git commit -m "feat: switch active news ingestion from thenewsapi to finnhub"
```

- [ ] **Step 7: Set the Railway env var (manual, not part of the commit)**

Set `FINNHUB_API_KEY` on the `newsflo-app` service via `railway variable set FINNHUB_API_KEY=<key> --service newsflo-app` (or the Railway dashboard) — the key was provided directly by the user in chat and must never be committed or echoed in any command output/logs. This step has no automated test; confirm via `railway variable list --service newsflo-app --json` that the key name is present (do not print its value).

---

## Explicitly out of scope (per design doc)

Webhook push ingestion, running thenewsapi and finnhub concurrently, deleting `thenewsapi.py`, pulling `forex`/`crypto` categories. See the design doc's "Explicitly out of scope" section.
