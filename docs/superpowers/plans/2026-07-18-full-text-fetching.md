# Full Article Text Fetching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fetch and extract full article body text from each article's own URL (neither ingestion source provides it today, only a one-line summary), so every downstream reasoning step works from real article text instead of a thin summary.

**Architecture:** A new `app/ingestion/full_text.py` module holds a pure fetcher (`fetch_full_text`, HTTP GET + `trafilatura` extraction, never raises) and an orchestrator (`fetch_pending_full_text`, DB-aware, one-shot-per-article). Two new nullable `Article` columns store the result and a fetch-attempted marker. `process_new_articles` calls the orchestrator as its first step, and a new `article_text()` helper in `app/pipeline.py` prefers the fetched full text over the existing summary everywhere article text is consumed.

**Tech Stack:** Python/FastAPI backend, SQLAlchemy (manual `_ADDED_COLUMNS` migration, no Alembic), `httpx` (already a dependency), `trafilatura` (new dependency), pytest.

## Global Constraints

- Design spec: `docs/superpowers/specs/2026-07-18-full-text-fetching-design.md` — every task below implements a specific section of it.
- Every new network-calling function follows this codebase's established "never raise, degrade to `None`" contract — see `app/ingestion/og_image.py::fetch_og_image` (the direct precedent this design mirrors) and `app/outcomes/price_fetcher.py`.
- A fetch is attempted **at most once** per article — `full_content_fetch_attempted_at` is set on every attempt (success or failure), and the orchestrator only ever selects articles where it's still `NULL`. Never retry a previously-attempted article.
- Any new function wired into `app/pipeline.py` that can make a real network call **must** get an autouse `conftest.py` stub before task completion — this codebase's existing pipeline tests (`test_pipeline.py`) call `process_new_articles` directly and will make real HTTP calls otherwise. This mirrors the existing `_no_real_og_image_fetch` / `_no_real_financial_snapshot_fetch` fixtures in `backend/tests/conftest.py`.
- New DB columns go in **both** places: the SQLAlchemy `Column` definition in `app/models.py` (for the ORM/fresh `create_all` databases) **and** the `_ADDED_COLUMNS` list in `app/db.py` (for the manual ALTER TABLE migration on existing databases, including production).

---

## File Structure

- Create: `backend/app/ingestion/full_text.py` — `fetch_full_text(url)`, `fetch_pending_full_text(session)`.
- Create: `backend/tests/test_full_text.py`.
- Modify: `backend/app/models.py` — `Article.full_content`, `Article.full_content_fetch_attempted_at`.
- Modify: `backend/app/db.py` — two new `_ADDED_COLUMNS` entries.
- Modify: `backend/app/pipeline.py` — `article_text()` helper, wire `fetch_pending_full_text` into `process_new_articles`, use `article_text(article)` in the `analyze_article` call.
- Modify: `backend/tests/conftest.py` — new autouse stub `_no_real_full_text_fetch`.
- Modify: `backend/tests/test_pipeline.py` — one new test confirming `article_text` is what actually reaches `analyze_article`.
- Modify: `backend/requirements.txt` — add `trafilatura`.

---

## Task 1: `fetch_full_text` — pure fetcher

**Files:**
- Create: `backend/app/ingestion/full_text.py`
- Create: `backend/tests/test_full_text.py`
- Modify: `backend/requirements.txt`

**Interfaces:**
- Produces: `fetch_full_text(url: str) -> str | None`, used by Task 2's `fetch_pending_full_text`.

- [ ] **Step 1: Add the dependency**

Add `trafilatura` to `backend/requirements.txt`, on its own line right after `beautifulsoup4` (both are HTML-processing libraries, keep them adjacent):

```
beautifulsoup4
trafilatura
```

Install it into the local dev venv so the tests in this task can actually run:

Run: `cd backend && .venv/Scripts/python.exe -m pip install trafilatura`
Expected: installs successfully (pulls in `lxml`, `courlan`, and a handful of other transitive dependencies — this is normal for this library).

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/test_full_text.py`. This mirrors `backend/tests/test_og_image.py`'s exact structure and `_fake_get` helper (same fake-response pattern, same monkeypatch style) — `trafilatura.extract` is also monkeypatched so these tests stay deterministic and don't depend on trafilatura's actual extraction algorithm:

```python
from types import SimpleNamespace

from app.ingestion.full_text import fetch_full_text


def _fake_get(html: str, status_code: int = 200):
    def get(url, timeout=None, follow_redirects=None, headers=None):
        response = SimpleNamespace(text=html, status_code=status_code)
        response.raise_for_status = lambda: None
        if status_code >= 400:
            def _raise():
                raise Exception("http error")
            response.raise_for_status = _raise
        return response
    return get


def test_returns_extracted_text_on_success(monkeypatch):
    html = "<html><body><article>Full article body text.</article></body></html>"
    monkeypatch.setattr("app.ingestion.full_text.httpx.get", _fake_get(html))
    monkeypatch.setattr("app.ingestion.full_text.trafilatura.extract", lambda h: "Full article body text.")
    assert fetch_full_text("https://example.com/a") == "Full article body text."


def test_returns_none_when_extraction_finds_nothing(monkeypatch):
    html = "<html><body></body></html>"
    monkeypatch.setattr("app.ingestion.full_text.httpx.get", _fake_get(html))
    monkeypatch.setattr("app.ingestion.full_text.trafilatura.extract", lambda h: None)
    assert fetch_full_text("https://example.com/a") is None


def test_returns_none_on_http_error(monkeypatch):
    monkeypatch.setattr("app.ingestion.full_text.httpx.get", _fake_get("", status_code=404))
    assert fetch_full_text("https://example.com/missing") is None


def test_returns_none_on_network_exception(monkeypatch):
    def boom(*args, **kwargs):
        raise ConnectionError("no route")
    monkeypatch.setattr("app.ingestion.full_text.httpx.get", boom)
    assert fetch_full_text("https://example.com/down") is None


def test_returns_none_when_extraction_raises(monkeypatch):
    html = "<html><body>malformed</body></html>"
    monkeypatch.setattr("app.ingestion.full_text.httpx.get", _fake_get(html))
    def boom(h):
        raise ValueError("parse error")
    monkeypatch.setattr("app.ingestion.full_text.trafilatura.extract", boom)
    assert fetch_full_text("https://example.com/a") is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_full_text.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ingestion.full_text'`

- [ ] **Step 4: Write the implementation**

Create `backend/app/ingestion/full_text.py`:

```python
import httpx
import trafilatura

_TIMEOUT = 10.0
_USER_AGENT = "Mozilla/5.0 (compatible; NewsFloBot/1.0)"


def fetch_full_text(url: str) -> str | None:
    """Fetch the article's own page and extract its main body text, or
    None on any failure (timeout, non-2xx, paywall, JS-rendered page
    trafilatura can't parse, no extractable content). Never raises -- same
    "degrade to None" contract as app.ingestion.og_image.fetch_og_image.
    10s timeout (double fetch_og_image's 5s) since this reads the full
    page body, not just <head> meta tags.
    """
    try:
        response = httpx.get(
            url, timeout=_TIMEOUT, follow_redirects=True, headers={"User-Agent": _USER_AGENT},
        )
        response.raise_for_status()
        return trafilatura.extract(response.text)
    except Exception:
        return None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_full_text.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/ingestion/full_text.py backend/tests/test_full_text.py backend/requirements.txt
git commit -m "feat: add fetch_full_text, scrapes+extracts an article's full body text"
```

---

## Task 2: DB columns + `fetch_pending_full_text` orchestrator

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/db.py`
- Modify: `backend/app/ingestion/full_text.py`
- Modify: `backend/tests/test_full_text.py`

**Interfaces:**
- Consumes: `fetch_full_text(url) -> str | None` from Task 1 (same module).
- Produces: `fetch_pending_full_text(session: Session) -> None`, used by Task 3's `process_new_articles` wiring. Reads/writes the new `Article.full_content` / `Article.full_content_fetch_attempted_at` columns.

- [ ] **Step 1: Add the new columns**

In `backend/app/models.py`, in the `Article` class (after the existing `image_url` column, before the `alerts` relationship):

```python
    image_url = Column(String, nullable=True)  # og:image / twitter:image scraped from the article page
    full_content = Column(Text, nullable=True)  # scraped+extracted full body text, see app/ingestion/full_text.py
    full_content_fetch_attempted_at = Column(DateTime(timezone=True), nullable=True)
```

In `backend/app/db.py`, append to the end of `_ADDED_COLUMNS` (after the existing `"parent_company_id"` entry):

```python
    ("alert_companies", "parent_company_id", "INTEGER"),
    ("articles", "full_content", "TEXT"),
    ("articles", "full_content_fetch_attempted_at", "TIMESTAMP"),
]
```

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/test_full_text.py` (add these imports at the top of the file, alongside the existing `from types import SimpleNamespace` and `from app.ingestion.full_text import fetch_full_text` lines):

```python
from app.ingestion.full_text import fetch_full_text, fetch_pending_full_text
from app.models import Article
```

Add these tests to the same file:

```python
def test_fetch_pending_full_text_populates_content_on_success(db_session, monkeypatch):
    article = Article(source="test", url="https://example.com/a", title="t", content="summary")
    db_session.add(article)
    db_session.commit()

    monkeypatch.setattr("app.ingestion.full_text.fetch_full_text", lambda url: "The full article body.")

    fetch_pending_full_text(db_session)

    refreshed = db_session.query(Article).filter_by(id=article.id).one()
    assert refreshed.full_content == "The full article body."
    assert refreshed.full_content_fetch_attempted_at is not None


def test_fetch_pending_full_text_marks_attempt_even_on_failure(db_session, monkeypatch):
    article = Article(source="test", url="https://example.com/a", title="t", content="summary")
    db_session.add(article)
    db_session.commit()

    monkeypatch.setattr("app.ingestion.full_text.fetch_full_text", lambda url: None)

    fetch_pending_full_text(db_session)

    refreshed = db_session.query(Article).filter_by(id=article.id).one()
    assert refreshed.full_content is None
    assert refreshed.full_content_fetch_attempted_at is not None


def test_fetch_pending_full_text_never_retries_an_attempted_article(db_session, monkeypatch):
    article = Article(source="test", url="https://example.com/a", title="t", content="summary")
    db_session.add(article)
    db_session.commit()

    call_count = {"n": 0}
    def counting_fetch(url):
        call_count["n"] += 1
        return None
    monkeypatch.setattr("app.ingestion.full_text.fetch_full_text", counting_fetch)

    fetch_pending_full_text(db_session)
    fetch_pending_full_text(db_session)

    assert call_count["n"] == 1


def test_fetch_pending_full_text_ignores_non_new_articles(db_session, monkeypatch):
    article = Article(
        source="test", url="https://example.com/a", title="t", content="summary", status="ANALYZED",
    )
    db_session.add(article)
    db_session.commit()

    call_count = {"n": 0}
    def counting_fetch(url):
        call_count["n"] += 1
        return None
    monkeypatch.setattr("app.ingestion.full_text.fetch_full_text", counting_fetch)

    fetch_pending_full_text(db_session)

    assert call_count["n"] == 0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_full_text.py -v`
Expected: FAIL with `ImportError: cannot import name 'fetch_pending_full_text'`

- [ ] **Step 4: Write the implementation**

Append to `backend/app/ingestion/full_text.py` (add these imports at the top of the file, alongside the existing `httpx`/`trafilatura` imports):

```python
from sqlalchemy.orm import Session

from app.models import Article, utcnow
```

Add this function at the end of the file:

```python
def fetch_pending_full_text(session: Session) -> None:
    """For every NEW article that hasn't had a full-text fetch attempted
    yet, try once to fetch and extract its body text. Always marks the
    attempt timestamp regardless of success, so a permanently-unreachable
    URL (dead link, hard paywall) is never retried -- it just proceeds
    with summary-only text for the rest of the pipeline. Commits after
    each article (not batched) so a mid-run crash doesn't lose already-
    fetched articles.
    """
    articles = (
        session.query(Article)
        .filter_by(status="NEW")
        .filter(Article.full_content_fetch_attempted_at.is_(None))
        .all()
    )
    for article in articles:
        article.full_content = fetch_full_text(article.url)
        article.full_content_fetch_attempted_at = utcnow()
        session.commit()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_full_text.py -v`
Expected: All 9 tests PASS (5 from Task 1 + 4 new).

- [ ] **Step 6: Commit**

```bash
git add backend/app/models.py backend/app/db.py backend/app/ingestion/full_text.py backend/tests/test_full_text.py
git commit -m "feat: add fetch_pending_full_text orchestrator with one-shot retry guard"
```

---

## Task 3: Wire into the pipeline

**Files:**
- Modify: `backend/app/pipeline.py`
- Modify: `backend/tests/conftest.py`
- Modify: `backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `fetch_pending_full_text(session)` from Task 2's `app.ingestion.full_text`.
- Produces: `article_text(article: Article) -> str` in `app.pipeline`, and `process_new_articles` now fetches full text before filtering, using it preferentially wherever article text is sent to `analyze_article`.

- [ ] **Step 1: Write the failing test**

Add this test to `backend/tests/test_pipeline.py` (place it after the existing `test_process_new_articles_creates_alert_end_to_end` test, following that test's exact seeding pattern):

```python
def test_process_new_articles_uses_full_content_over_summary_when_available(db_session, monkeypatch):
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    article = Article(
        source="test", url="https://example.com/a",
        title="US strikes Iran oil export sites", content="crude oil markets react",
        full_content="The full scraped article body, much richer than the summary.",
        full_content_fetch_attempted_at=pipeline_module.utcnow(),
    )
    db_session.add(article)
    db_session.commit()

    fake_output = AnalysisOutput(
        category="oil_gas",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
            key_points=["Crude eases"], confidence_score=85, time_horizon="Short-Term",
        )],
    )
    captured = {}
    def fake_analyze(client, title, content):
        captured["content"] = content
        return fake_output
    monkeypatch.setattr(pipeline_module, "analyze_article", fake_analyze)

    process_new_articles(db_session, claude_client=object())

    assert captured["content"] == "The full scraped article body, much richer than the summary."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_pipeline.py::test_process_new_articles_uses_full_content_over_summary_when_available -v`
Expected: FAIL — `captured["content"]` is `"crude oil markets react"` (the summary), not the full content, since `process_new_articles` doesn't yet prefer `full_content`.

- [ ] **Step 3: Add the autouse conftest stub FIRST, before wiring**

In `backend/tests/conftest.py`, add this fixture after the existing `_no_real_og_image_fetch` fixture (same file, same autouse pattern) — added now, before Step 4 wires `fetch_pending_full_text` into `process_new_articles`, so no existing pipeline test ever makes a real network call once the wiring lands:

```python
@pytest.fixture(autouse=True)
def _no_real_full_text_fetch(monkeypatch):
    # process_new_articles now calls fetch_pending_full_text for every NEW
    # article, which would otherwise make a real HTTP GET (see
    # app/ingestion/full_text.py). Stub it everywhere by default so the
    # suite never makes network calls; app/ingestion/full_text.py's own
    # tests exercise the real function directly and are unaffected since
    # they don't go through app.pipeline.
    monkeypatch.setattr("app.pipeline.fetch_pending_full_text", lambda session: None)
```

- [ ] **Step 4: Write the implementation**

In `backend/app/pipeline.py`, add the import (alongside the existing `from app.ingestion.og_image import fetch_og_image` line):

```python
from app.ingestion.full_text import fetch_pending_full_text
```

Add this helper function near the other small helpers at the top of the file (alongside `_decode_json_list`/`decode_key_points`/`_as_aware_utc`):

```python
def article_text(article: Article) -> str:
    return article.full_content or article.content
```

In `process_new_articles`, add the call as the very first line of the function body (before the existing `filter_new_articles(session)` line):

```python
def process_new_articles(session: Session, claude_client, throttle_seconds: float = 0) -> int:
    """..."""  # existing docstring unchanged
    fetch_pending_full_text(session)
    filter_new_articles(session)
    ...  # rest of the function unchanged up to the analyze_article call below
```

Change the existing `analyze_article(claude_client, article.title, article.content)` call to:

```python
            analysis = analyze_article(claude_client, article.title, article_text(article))
```

- [ ] **Step 5: Run the new test to verify it passes**

Run: `cd backend && python -m pytest tests/test_pipeline.py::test_process_new_articles_uses_full_content_over_summary_when_available -v`
Expected: PASS.

- [ ] **Step 6: Run the full backend test suite**

Run: `cd backend && python -m pytest -v`
Expected: All tests PASS — in particular, every pre-existing `test_pipeline.py` test (which call `process_new_articles` directly) must still pass with zero real network calls, confirming the Step 3 conftest stub is doing its job.

- [ ] **Step 7: Commit**

```bash
git add backend/app/pipeline.py backend/tests/conftest.py backend/tests/test_pipeline.py
git commit -m "feat: fetch full article text before filtering, prefer it over the summary"
```

---

## Task 4: Full suite verification

**Files:** none (verification-only task).

- [ ] **Step 1: Run the full backend test suite**

Run: `cd backend && python -m pytest -v`
Expected: All tests PASS (0 failures), including all of `test_full_text.py` and the modified `test_pipeline.py`.

- [ ] **Step 2: Confirm no real network calls happen in the suite**

Run: `cd backend && python -m pytest -v -m "not network" 2>&1 | grep -i "ConnectionError\|timeout\|network"` (or simply re-read the Step 1 output) to confirm no test failed or hung on an actual outbound HTTP request — every test touching `fetch_pending_full_text`/`fetch_full_text` should be fully mocked per the tasks above.
Expected: no matches (clean run, already confirmed by Task 3 Step 6 — this step is a final sanity re-check, not new work).

This step has no separate pass/fail beyond re-confirming Task 3's Step 6 result — report the full suite's pass count and confirm the plan is complete.
