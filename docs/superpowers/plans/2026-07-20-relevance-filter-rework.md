# Relevance Filter Rework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the narrow keyword-allowlist filter (`app/filtering/heuristic.py`) with a cheap LLM classifier that judges genuine relevance, fixing the confirmed-in-production bug where real financial news (a government infrastructure contract-win story) gets wrongly filtered out.

**Architecture:** New `app/filtering/relevance.py` fully replaces `app/filtering/heuristic.py` (deleted, not kept as a fallback). `classify_relevance(client, title, content)` makes one cheap chat-completion call against `FALLBACK_MODEL`, fails open on any error. `filter_new_articles` gains a `client` parameter, reuses the same `claude_client` object `process_new_articles` already holds.

**Tech Stack:** Python/FastAPI backend, the existing OpenAI-compatible client abstraction (`app.analysis.claude_client.build_client`), pytest.

## Global Constraints

- Design spec: `docs/superpowers/specs/2026-07-20-relevance-filter-rework-design.md`.
- `classify_relevance` fails **open** on any error (returns `True`, admits the article) — this is a deliberate, singular exception to this codebase's usual "degrade to a safe negative/empty" contract, because here the safe default is admit, not reject. Every other function in this plan follows the normal "never raise" contract otherwise.
- `article.category` is never set by the filter step — confirmed dead (write-only, always overwritten by the real LLM analysis before anything reads it).
- `app/filtering/heuristic.py` and `backend/tests/test_heuristic.py` are deleted outright in this plan, not disabled-and-kept — unlike the IndianAPI/RSS-poller precedent, there is no "revert to the old behavior" scenario here worth preserving dead code for; the keyword approach is being replaced because it structurally cannot do this job on a generic news source.
- Classification uses `article_text(article)` (full text when available, summary fallback) as input, not just the short summary — imported from `app.pipeline`, the same helper the main analysis call already uses.

---

## File Structure

- Create: `backend/app/filtering/relevance.py` — `classify_relevance(client, title, content)`, `filter_new_articles(session, client)`.
- Create: `backend/tests/test_relevance.py`.
- Delete: `backend/app/filtering/heuristic.py`, `backend/tests/test_heuristic.py`.
- Modify: `backend/app/pipeline.py` — import path update, `filter_new_articles(session)` → `filter_new_articles(session, claude_client)`.

---

## Task 1: `classify_relevance`

**Files:**
- Create: `backend/app/filtering/relevance.py`
- Create: `backend/tests/test_relevance.py`

**Interfaces:**
- Produces: `classify_relevance(client, title: str, content: str) -> bool`, used by Task 2's `filter_new_articles`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_relevance.py`. The fake-client shape mirrors this codebase's existing convention in `tests/test_claude_client.py` (`SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=...)))`), adapted for a plain content-based response (no tool_calls):

```python
from types import SimpleNamespace

from app.filtering.relevance import classify_relevance


def _fake_client(response_text: str):
    def create(**kwargs):
        message = SimpleNamespace(content=response_text)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def _raising_client():
    def create(**kwargs):
        raise RuntimeError("api error")
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_classify_relevance_true_on_yes():
    assert classify_relevance(_fake_client("YES"), "RBI hikes repo rate", "") is True


def test_classify_relevance_false_on_no():
    assert classify_relevance(_fake_client("NO"), "Cat stuck in tree", "") is False


def test_classify_relevance_tolerates_case_and_whitespace():
    assert classify_relevance(_fake_client("  yes  "), "t", "c") is True
    assert classify_relevance(_fake_client("No."), "t", "c") is False


def test_classify_relevance_fails_open_on_client_exception():
    # Load-bearing: dropping a real story silently is worse than one
    # wasted downstream analysis call on a false positive.
    assert classify_relevance(_raising_client(), "t", "c") is True


def test_classify_relevance_fails_open_on_garbled_response():
    assert classify_relevance(_fake_client(""), "t", "c") is False
    assert classify_relevance(_fake_client("maybe"), "t", "c") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_relevance.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.filtering.relevance'`

- [ ] **Step 3: Write the implementation**

Create `backend/app/filtering/relevance.py`:

```python
from app.analysis.claude_client import FALLBACK_MODEL

_PROMPT_TEMPLATE = (
    "Does this news plausibly affect any financial, business, or economic "
    "sector -- directly or indirectly -- anywhere in the world? Consider "
    "stock markets, companies, government spending, infrastructure, "
    "policy, trade, or the broader economy relevant. Answer with exactly "
    "one word: YES or NO.\n\n"
    "Title: {title}\n\n"
    "Content: {content}"
)


def classify_relevance(client, title: str, content: str) -> bool:
    """Ask a cheap, fast model whether this article could plausibly
    affect any financial/business/economic sector, directly or
    indirectly, anywhere. Never raises -- any failure (API error,
    unparseable response) fails OPEN (returns True, admit the article):
    silently dropping a real story is worse than one wasted downstream
    analysis call on a false positive.
    """
    try:
        response = client.chat.completions.create(
            model=FALLBACK_MODEL,
            messages=[{"role": "user", "content": _PROMPT_TEMPLATE.format(title=title, content=content)}],
            max_tokens=5,
        )
        answer = response.choices[0].message.content
    except Exception:
        return True

    return "yes" in (answer or "").strip().lower()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_relevance.py -v`
Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/filtering/relevance.py backend/tests/test_relevance.py
git commit -m "feat: add classify_relevance, cheap LLM relevance classifier"
```

---

## Task 2: `filter_new_articles` rewrite + delete the old filter

**Files:**
- Modify: `backend/app/filtering/relevance.py`
- Modify: `backend/tests/test_relevance.py`
- Delete: `backend/app/filtering/heuristic.py`
- Delete: `backend/tests/test_heuristic.py`

**Interfaces:**
- Consumes: `classify_relevance(client, title, content) -> bool` from Task 1 (same module). `article_text(article) -> str` from `app.pipeline` (already shipped by the full-text-fetching sub-project).
- Produces: `filter_new_articles(session: Session, client) -> None`, used by Task 3's `process_new_articles` wiring.

- [ ] **Step 1: Delete the old filter and its tests**

```bash
git rm backend/app/filtering/heuristic.py backend/tests/test_heuristic.py
```

- [ ] **Step 2: Write the failing tests**

Add to `backend/tests/test_relevance.py` (new imports needed at the top of the file — add `from sqlalchemy.orm import Session` is not needed since `db_session` fixture provides a ready session; add `from app.filtering.relevance import classify_relevance, filter_new_articles` — extend the existing import line — and `from app.models import Article`):

```python
def test_filter_new_articles_categorizes_relevant_and_filters_irrelevant(db_session, monkeypatch):
    relevant = Article(source="test", url="https://example.com/1", title="RBI hikes repo rate", content="")
    irrelevant = Article(source="test", url="https://example.com/2", title="Cat stuck in tree", content="")
    db_session.add_all([relevant, irrelevant])
    db_session.commit()

    def fake_classify(client, title, content):
        return title == "RBI hikes repo rate"
    monkeypatch.setattr("app.filtering.relevance.classify_relevance", fake_classify)

    filter_new_articles(db_session, client=object())

    db_session.refresh(relevant)
    db_session.refresh(irrelevant)
    assert relevant.status == "CATEGORIZED"
    assert relevant.category is None
    assert irrelevant.status == "FILTERED"


def test_filter_new_articles_uses_full_content_when_available(db_session, monkeypatch):
    article = Article(
        source="test", url="https://example.com/1", title="t",
        content="short summary", full_content="the real full article text",
    )
    db_session.add(article)
    db_session.commit()

    captured = {}
    def fake_classify(client, title, content):
        captured["content"] = content
        return True
    monkeypatch.setattr("app.filtering.relevance.classify_relevance", fake_classify)

    filter_new_articles(db_session, client=object())

    assert captured["content"] == "the real full article text"


def test_filter_new_articles_only_touches_new_articles(db_session, monkeypatch):
    already_analyzed = Article(
        source="test", url="https://example.com/1", title="t", content="c", status="ANALYZED",
    )
    db_session.add(already_analyzed)
    db_session.commit()

    call_count = {"n": 0}
    def counting_classify(client, title, content):
        call_count["n"] += 1
        return True
    monkeypatch.setattr("app.filtering.relevance.classify_relevance", counting_classify)

    filter_new_articles(db_session, client=object())

    assert call_count["n"] == 0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_relevance.py -v`
Expected: FAIL with `ImportError: cannot import name 'filter_new_articles'`

- [ ] **Step 4: Write the implementation**

In `backend/app/filtering/relevance.py`, add these imports at the top (alongside the existing `from app.analysis.claude_client import FALLBACK_MODEL` line):

```python
from sqlalchemy.orm import Session

from app.models import Article
```

Note: do NOT add a top-level `from app.pipeline import article_text` here. `app/pipeline.py` imports `filter_new_articles` from this module near the top of its own file (before it defines `article_text`), so a top-level import the other way round would be circular and fail with `ImportError: cannot import name 'article_text' from partially initialized module 'app.pipeline'` the moment `pipeline.py` loads. Import `article_text` locally inside the function instead — by the time `filter_new_articles` actually runs, `app.pipeline` has finished loading, so the circular dependency at import time never triggers.

Add this function at the end of the file:

```python
def filter_new_articles(session: Session, client) -> None:
    from app.pipeline import article_text

    for article in session.query(Article).filter_by(status="NEW").all():
        if classify_relevance(client, article.title, article_text(article)):
            article.status = "CATEGORIZED"
        else:
            article.status = "FILTERED"
    session.commit()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_relevance.py -v`
Expected: All 9 tests PASS (6 from Task 1 + 3 new).

- [ ] **Step 6: Commit**

```bash
git add backend/app/filtering/relevance.py backend/tests/test_relevance.py
git rm backend/app/filtering/heuristic.py backend/tests/test_heuristic.py
git commit -m "feat: replace the keyword filter with filter_new_articles + classify_relevance"
```

(If `git rm` was already committed in Step 1 as its own commit, this step just adds/commits the remaining new-file changes — either a single combined commit or two sequential ones is fine, as long as the final state has both the deletion and the new implementation.)

---

## Task 3: Wire into the pipeline

**Files:**
- Modify: `backend/app/pipeline.py`

**Interfaces:**
- Consumes: `filter_new_articles(session, client)` from Task 2's `app.filtering.relevance`.
- Produces: `process_new_articles` calls the new filter with the same `claude_client` object it already holds.

- [ ] **Step 1: Write the failing test**

Add this test to `backend/tests/test_pipeline.py` (place it after the existing `test_process_new_articles_uses_full_content_over_summary_when_available` test):

```python
def test_process_new_articles_passes_the_same_client_to_the_filter(db_session, monkeypatch):
    article = Article(
        source="test", url="https://example.com/a", title="t", content="c",
    )
    db_session.add(article)
    db_session.commit()

    sentinel_client = object()
    captured = {}
    def fake_filter(session, client):
        captured["client"] = client
    monkeypatch.setattr(pipeline_module, "filter_new_articles", fake_filter)

    process_new_articles(db_session, claude_client=sentinel_client)

    assert captured["client"] is sentinel_client
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_pipeline.py::test_process_new_articles_passes_the_same_client_to_the_filter -v`
Expected: FAIL — `TypeError: filter_new_articles() missing 1 required positional argument: 'client'` (the current call site only passes `session`).

- [ ] **Step 3: Write the implementation**

In `backend/app/pipeline.py`, change the import (currently `from app.filtering.heuristic import filter_new_articles`) to:

```python
from app.filtering.relevance import filter_new_articles
```

In `process_new_articles`, change:

```python
    filter_new_articles(session)
```

to:

```python
    filter_new_articles(session, claude_client)
```

- [ ] **Step 4: Run the new test to verify it passes**

Run: `cd backend && python -m pytest tests/test_pipeline.py::test_process_new_articles_passes_the_same_client_to_the_filter -v`
Expected: PASS.

- [ ] **Step 5: Run the full backend test suite**

Run: `cd backend && python -m pytest -v`
Expected: All tests PASS — in particular, every pre-existing `test_pipeline.py` test must still pass (they already mock `analyze_article`, and the filter now calls `classify_relevance` for real against whatever fake/mock `claude_client` object those tests pass in — check whether any existing test needs `classify_relevance` mocked too, since a real `object()`-as-client passed to `classify_relevance` would raise `AttributeError` on `.chat.completions.create` and — per the fail-open contract — correctly degrade to `True`/admit, so existing tests should keep passing without needing new mocks; confirm this is actually true by running the suite rather than assuming it).

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipeline.py backend/tests/test_pipeline.py
git commit -m "feat: wire the relevance-filter rework into process_new_articles"
```

---

## Task 4: Full suite verification

**Files:** none (verification-only task).

- [ ] **Step 1: Run the full backend test suite**

Run: `cd backend && python -m pytest -v`
Expected: All tests PASS (0 failures), including all of `test_relevance.py` and the modified `test_pipeline.py`. Confirm `test_heuristic.py` no longer exists and nothing references `app.filtering.heuristic` anywhere (`grep -rn "filtering.heuristic\|classify_category" backend --include="*.py"` should return no matches).

- [ ] **Step 2: Confirm the app still imports cleanly**

Run: `cd backend && python -c "from app import main; print('import OK')"`
Expected: `import OK`.

This step has no separate pass/fail beyond re-confirming Task 3's Step 5 result — report the full suite's pass count and confirm the plan is complete.
