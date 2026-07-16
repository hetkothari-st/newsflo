# Financial Grounding & Contradiction Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ground AI reasoning in real price/return data and replace the Confidence Engine's hardcoded `reasoning_consistent=True` with a real deterministic contradiction check comparing reasoning direction against actual recent price momentum.

**Architecture:** A new `app/reasoning/financial_context.py` module (pure fetch/contradiction functions + a DB-backed cache function, mirroring the existing `app/calibration/blender.py` pattern of mixing pure and DB-dependent functions in one small file) plugs into `pipeline.py::_persist_alert` at the same point the existing calibration-health lookup already runs. Reuses two existing yfinance call sites unchanged (`price_series.fetch_price_series`, `outcomes/price_fetcher.fetch_price_change_pct`) — no new third-party dependency.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, pytest (backend); React + TypeScript, Vitest (frontend).

## Global Constraints

- No Alembic — new columns go through `app/db.py`'s `_ADDED_COLUMNS` guarded-ALTER-TABLE list; a new table (`financial_snapshots`) needs no such entry since `Base.metadata.create_all` creates missing tables automatically.
- Every yfinance-touching function must follow this codebase's established "never raise, degrade to `None`" contract — a single ticker's fetch failure must never block the rest of the pipeline.
- Contradiction threshold is exactly 5.0 percentage points, as a named constant (`CONTRADICTION_THRESHOLD_PCT`), not inlined.
- Cache TTL is exactly 1 hour (`SNAPSHOT_CACHE_HOURS`), as a named constant.
- All new `AlertCompany`/`Alert`-adjacent fields exposed via API/frontend types must be optional/nullable — legacy alerts (persisted before this feature) have none of them.
- Match existing test style exactly: `db_session` fixture (in-memory SQLite) for DB-touching backend tests, `monkeypatch.setattr(module, "yf", ...)`-equivalent mocking pattern already used in `test_price_fetcher.py`/`test_price_series.py` for anything touching yfinance-wrapping functions, Vitest + React Testing Library for frontend.

---

### Task 1: Financial snapshot fetcher and contradiction detector (pure functions)

**Files:**
- Create: `backend/app/reasoning/financial_context.py`
- Test: `backend/tests/test_financial_context.py`

**Interfaces:**
- Consumes: `fetch_price_series(ticker, period)` from `app.companies.price_series` (existing, unmodified), `fetch_price_change_pct(ticker, start_date, horizon_days)` from `app.outcomes.price_fetcher` (existing, unmodified)
- Produces: `fetch_financial_snapshot(ticker: str) -> dict | None` (keys `price`, `return_1m`, `return_3m`), `detect_price_contradiction(direction: str, return_1m: float | None) -> str | None`, `CONTRADICTION_THRESHOLD_PCT: float`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_financial_context.py
from datetime import datetime, timedelta, timezone

import pytest

from app.reasoning import financial_context


def test_fetch_financial_snapshot_returns_price_and_returns(monkeypatch):
    monkeypatch.setattr(
        financial_context, "fetch_price_series",
        lambda ticker, period: [{"date": "2026-07-15", "close": 2500.5}],
    )

    def fake_change(ticker, start_date, horizon_days):
        return 8.3 if horizon_days == 30 else -2.1

    monkeypatch.setattr(financial_context, "fetch_price_change_pct", fake_change)

    result = financial_context.fetch_financial_snapshot("RELIANCE.NS")

    assert result == {"price": 2500.5, "return_1m": 8.3, "return_3m": -2.1}


def test_fetch_financial_snapshot_returns_none_when_price_unavailable(monkeypatch):
    monkeypatch.setattr(financial_context, "fetch_price_series", lambda ticker, period: None)
    monkeypatch.setattr(
        financial_context, "fetch_price_change_pct",
        lambda ticker, start_date, horizon_days: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    assert financial_context.fetch_financial_snapshot("UNKNOWN.NS") is None


def test_fetch_financial_snapshot_degrades_individual_return_to_none(monkeypatch):
    monkeypatch.setattr(
        financial_context, "fetch_price_series",
        lambda ticker, period: [{"date": "2026-07-15", "close": 100.0}],
    )

    def fake_change(ticker, start_date, horizon_days):
        return None if horizon_days == 30 else 4.0

    monkeypatch.setattr(financial_context, "fetch_price_change_pct", fake_change)

    result = financial_context.fetch_financial_snapshot("PARTIAL.NS")

    assert result == {"price": 100.0, "return_1m": None, "return_3m": 4.0}


def test_threshold_is_five_percent():
    assert financial_context.CONTRADICTION_THRESHOLD_PCT == 5.0


def test_detect_price_contradiction_bullish_at_threshold_triggers():
    note = financial_context.detect_price_contradiction("bullish", -5.0)
    assert note is not None
    assert "bullish" in note.lower()
    assert "5.0%" in note


def test_detect_price_contradiction_bullish_just_under_threshold_no_trigger():
    assert financial_context.detect_price_contradiction("bullish", -4.9) is None


def test_detect_price_contradiction_bearish_at_threshold_triggers():
    note = financial_context.detect_price_contradiction("bearish", 5.0)
    assert note is not None
    assert "bearish" in note.lower()


def test_detect_price_contradiction_bearish_just_under_threshold_no_trigger():
    assert financial_context.detect_price_contradiction("bearish", 4.9) is None


def test_detect_price_contradiction_none_return_never_triggers():
    assert financial_context.detect_price_contradiction("bullish", None) is None
    assert financial_context.detect_price_contradiction("bearish", None) is None


def test_detect_price_contradiction_ignores_unrecognized_direction():
    assert financial_context.detect_price_contradiction("neutral", -50.0) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_financial_context.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.reasoning.financial_context'`

- [ ] **Step 3: Implement the pure functions**

```python
# backend/app/reasoning/financial_context.py
"""Grounds AI reasoning in real financial data and detects when reasoning
contradicts actual recent price momentum. See docs/superpowers/specs/
2026-07-16-financial-grounding-contradiction-detection-design.md.

fetch_financial_snapshot and detect_price_contradiction are pure (no DB, no
Session) -- get_or_fetch_financial_snapshot (added in a later task) is the
DB-backed caching layer on top, mirroring how app.calibration.blender mixes
pure and DB-dependent functions in one small file.
"""

from datetime import timedelta

from app.companies.price_series import fetch_price_series
from app.models import utcnow
from app.outcomes.price_fetcher import fetch_price_change_pct

# How large a mismatch between reasoning direction and actual 1-month price
# momentum counts as a real contradiction, not normal noise. Named constant,
# not inlined, so it can be retuned like the Confidence Engine's weights.
CONTRADICTION_THRESHOLD_PCT = 5.0


def fetch_financial_snapshot(ticker: str) -> dict | None:
    """Fetch {"price", "return_1m", "return_3m"} for `ticker`, backward-
    looking from now. Returns None only if the current price itself is
    unavailable (a snapshot with no price is useless); a missing individual
    return degrades to None for that field alone -- same "never raise,
    degrade to None" contract as every other yfinance-touching function in
    this codebase.
    """
    series = fetch_price_series(ticker, period="5d")
    if not series:
        return None
    price = series[-1]["close"]

    return_1m = fetch_price_change_pct(ticker, utcnow() - timedelta(days=30), 30)
    return_3m = fetch_price_change_pct(ticker, utcnow() - timedelta(days=90), 90)

    return {"price": price, "return_1m": return_1m, "return_3m": return_3m}


def detect_price_contradiction(direction: str, return_1m: float | None) -> str | None:
    """Returns a human-readable contradiction note, or None if there is no
    contradiction -- including when return_1m is unavailable (absence of
    data is not evidence of a contradiction) or direction is anything other
    than "bullish"/"bearish".
    """
    if return_1m is None:
        return None
    if direction == "bullish" and return_1m <= -CONTRADICTION_THRESHOLD_PCT:
        return f"Price down {abs(return_1m):.1f}% over the past month despite bullish call."
    if direction == "bearish" and return_1m >= CONTRADICTION_THRESHOLD_PCT:
        return f"Price up {return_1m:.1f}% over the past month despite bearish call."
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_financial_context.py -v`
Expected: PASS (11 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/reasoning/financial_context.py backend/tests/test_financial_context.py
git commit -m "feat: add financial snapshot fetcher and contradiction detector"
```

---

### Task 2: Schema — FinancialSnapshot table and AlertCompany columns

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/db.py`
- Test: `backend/tests/test_models.py` (append)

**Interfaces:**
- Produces: `FinancialSnapshot` model (`ticker` unique, `price`, `return_1m`, `return_3m`, `fetched_at`); `AlertCompany` gains `price_at_analysis`, `return_1m`, `return_3m` (Float, nullable), `contradiction_note` (Text, nullable)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_models.py`:

```python
from app.models import FinancialSnapshot


def test_financial_snapshot_table_exists_and_enforces_unique_ticker(db_session):
    db_session.add(FinancialSnapshot(ticker="RELIANCE.NS", price=2500.5, return_1m=8.3, return_3m=-2.1))
    db_session.commit()  # must not raise

    row = db_session.query(FinancialSnapshot).filter_by(ticker="RELIANCE.NS").one()
    assert row.price == 2500.5
    assert row.return_1m == 8.3
    assert row.return_3m == -2.1
    assert row.fetched_at is not None


def test_alert_company_has_financial_context_columns(db_session):
    article = Article(source="test", url="https://example.com/financial-columns", title="t")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()
    company = Company(ticker="X.NS", name="X", sector="oil_gas", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()

    ac = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="x", basis="direct_mention",
        price_at_analysis=2500.5, return_1m=8.3, return_3m=-2.1,
        contradiction_note="Price down 12.0% over the past month despite bullish call.",
    )
    db_session.add(ac)
    db_session.commit()  # must not raise
    db_session.refresh(ac)

    assert ac.price_at_analysis == 2500.5
    assert ac.contradiction_note == "Price down 12.0% over the past month despite bullish call."


def test_alert_company_financial_context_columns_are_nullable(db_session):
    article = Article(source="test", url="https://example.com/financial-columns-null", title="t")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()
    company = Company(ticker="Y.NS", name="Y", sector="oil_gas", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()

    ac = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="x", basis="direct_mention",
    )
    db_session.add(ac)
    db_session.commit()  # must not raise
    db_session.refresh(ac)

    assert ac.price_at_analysis is None
    assert ac.contradiction_note is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'FinancialSnapshot'`

- [ ] **Step 3: Add the model and columns**

```python
# backend/app/models.py -- add this new class, e.g. directly after CalibrationSample:
class FinancialSnapshot(Base):
    """Cached price/return data for a ticker, refreshed on a TTL by
    app.reasoning.financial_context.get_or_fetch_financial_snapshot -- avoids
    re-hitting yfinance for the same company across multiple alerts in a
    short window."""
    __tablename__ = "financial_snapshots"
    __table_args__ = (UniqueConstraint("ticker", name="uq_financial_snapshot_ticker"),)

    id = Column(Integer, primary_key=True)
    ticker = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    return_1m = Column(Float, nullable=True)
    return_3m = Column(Float, nullable=True)
    fetched_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
```

```python
# backend/app/models.py -- add to the end of the AlertCompany class (after rulebook_ids_json):
    # Financial grounding + contradiction detection (see docs/superpowers/
    # specs/2026-07-16-financial-grounding-contradiction-detection-design.md).
    # Null for rows persisted before this feature shipped, or when the
    # underlying yfinance fetch failed for this company.
    price_at_analysis = Column(Float, nullable=True)
    return_1m = Column(Float, nullable=True)
    return_3m = Column(Float, nullable=True)
    contradiction_note = Column(Text, nullable=True)
```

- [ ] **Step 4: Register the new columns for production/dev migration**

```python
# backend/app/db.py -- append to _ADDED_COLUMNS:
    ("alert_companies", "price_at_analysis", "FLOAT"),
    ("alert_companies", "return_1m", "FLOAT"),
    ("alert_companies", "return_3m", "FLOAT"),
    ("alert_companies", "contradiction_note", "TEXT"),
```

(`financial_snapshots` is a brand-new table, not a new column on an existing table — `Base.metadata.create_all` creates it automatically; no `_ADDED_COLUMNS` entry needed.)

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_models.py -v`
Expected: PASS (3 new tests)

- [ ] **Step 6: Run the full suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: PASS (all tests — `db_session`'s in-memory SQLite creates the new table/columns directly from the model definitions; `_ADDED_COLUMNS` only matters for pre-existing production/dev database files)

- [ ] **Step 7: Commit**

```bash
git add backend/app/models.py backend/app/db.py backend/tests/test_models.py
git commit -m "feat: add FinancialSnapshot table and AlertCompany financial context columns"
```

---

### Task 3: Cache-then-fetch layer

**Files:**
- Modify: `backend/app/reasoning/financial_context.py`
- Modify: `backend/tests/test_financial_context.py`

**Interfaces:**
- Consumes: `fetch_financial_snapshot` (Task 1, same file), `FinancialSnapshot` model (Task 2)
- Produces: `get_or_fetch_financial_snapshot(session: Session, ticker: str) -> dict | None`, `SNAPSHOT_CACHE_HOURS: int`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_financial_context.py`:

```python
from app.models import FinancialSnapshot, utcnow


def test_cache_ttl_is_one_hour():
    assert financial_context.SNAPSHOT_CACHE_HOURS == 1


def test_get_or_fetch_creates_a_row_when_none_exists(db_session, monkeypatch):
    monkeypatch.setattr(
        financial_context, "fetch_financial_snapshot",
        lambda ticker: {"price": 2500.5, "return_1m": 8.3, "return_3m": -2.1},
    )

    result = financial_context.get_or_fetch_financial_snapshot(db_session, "RELIANCE.NS")

    assert result == {"price": 2500.5, "return_1m": 8.3, "return_3m": -2.1}
    row = db_session.query(FinancialSnapshot).filter_by(ticker="RELIANCE.NS").one()
    assert row.price == 2500.5


def test_get_or_fetch_reuses_a_fresh_cached_row_without_refetching(db_session, monkeypatch):
    db_session.add(FinancialSnapshot(
        ticker="RELIANCE.NS", price=100.0, return_1m=1.0, return_3m=2.0, fetched_at=utcnow(),
    ))
    db_session.commit()
    monkeypatch.setattr(
        financial_context, "fetch_financial_snapshot",
        lambda ticker: (_ for _ in ()).throw(AssertionError("should not refetch a fresh cache entry")),
    )

    result = financial_context.get_or_fetch_financial_snapshot(db_session, "RELIANCE.NS")

    assert result == {"price": 100.0, "return_1m": 1.0, "return_3m": 2.0}


def test_get_or_fetch_refetches_a_stale_cached_row(db_session, monkeypatch):
    stale_time = utcnow() - timedelta(hours=2)
    db_session.add(FinancialSnapshot(
        ticker="RELIANCE.NS", price=100.0, return_1m=1.0, return_3m=2.0, fetched_at=stale_time,
    ))
    db_session.commit()
    monkeypatch.setattr(
        financial_context, "fetch_financial_snapshot",
        lambda ticker: {"price": 200.0, "return_1m": 9.0, "return_3m": 10.0},
    )

    result = financial_context.get_or_fetch_financial_snapshot(db_session, "RELIANCE.NS")

    assert result == {"price": 200.0, "return_1m": 9.0, "return_3m": 10.0}
    row = db_session.query(FinancialSnapshot).filter_by(ticker="RELIANCE.NS").one()
    assert row.price == 200.0


def test_get_or_fetch_falls_back_to_stale_cache_when_refetch_fails(db_session, monkeypatch):
    stale_time = utcnow() - timedelta(hours=2)
    db_session.add(FinancialSnapshot(
        ticker="RELIANCE.NS", price=100.0, return_1m=1.0, return_3m=2.0, fetched_at=stale_time,
    ))
    db_session.commit()
    monkeypatch.setattr(financial_context, "fetch_financial_snapshot", lambda ticker: None)

    result = financial_context.get_or_fetch_financial_snapshot(db_session, "RELIANCE.NS")

    assert result == {"price": 100.0, "return_1m": 1.0, "return_3m": 2.0}


def test_get_or_fetch_returns_none_when_no_cache_and_fetch_fails(db_session, monkeypatch):
    monkeypatch.setattr(financial_context, "fetch_financial_snapshot", lambda ticker: None)

    result = financial_context.get_or_fetch_financial_snapshot(db_session, "UNKNOWN.NS")

    assert result is None
    assert db_session.query(FinancialSnapshot).count() == 0
```

Add `from datetime import timedelta` to the top of `backend/tests/test_financial_context.py` if not already present from Task 1's imports (check first).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_financial_context.py -v`
Expected: FAIL with `AttributeError: module 'app.reasoning.financial_context' has no attribute 'get_or_fetch_financial_snapshot'`

- [ ] **Step 3: Implement the cache layer**

Add to `backend/app/reasoning/financial_context.py`. First, replace the existing `from app.models import utcnow` import line (added in Task 1) with:

```python
from app.models import FinancialSnapshot, utcnow
```

and add a new import line for `Session`:

```python
from sqlalchemy.orm import Session
```

(`utcnow` was already imported for Task 1's use in `fetch_financial_snapshot` — this just widens that same import to also bring in `FinancialSnapshot`, rather than adding a second, duplicate `from app.models import ...` line.)

Then add, after `detect_price_contradiction`:

```python
# How long a cached snapshot stays fresh before a company's price/return
# data is refetched.
SNAPSHOT_CACHE_HOURS = 1


def _as_aware_utc(dt):
    """SQLite (used by the test suite) silently drops tzinfo on
    ``DateTime(timezone=True)`` columns when a row is reloaded after commit
    -- Postgres (production) does not have this quirk. Mirrors
    app.pipeline._as_aware_utc -- duplicated rather than imported to avoid a
    circular import (app.pipeline imports this module).
    """
    from datetime import timezone
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def get_or_fetch_financial_snapshot(session: Session, ticker: str) -> dict | None:
    """Cache-then-fetch: reuse a FinancialSnapshot row younger than
    SNAPSHOT_CACHE_HOURS, otherwise fetch fresh and upsert. If a fresh fetch
    fails but a stale cached row exists, the stale data is returned rather
    than dropping the Facts block entirely for one bad fetch cycle. Returns
    None only when there is no cached row AND the fetch failed.
    """
    existing = session.query(FinancialSnapshot).filter_by(ticker=ticker).one_or_none()
    if existing is not None:
        age_hours = (utcnow() - _as_aware_utc(existing.fetched_at)).total_seconds() / 3600
        if age_hours < SNAPSHOT_CACHE_HOURS:
            return {"price": existing.price, "return_1m": existing.return_1m, "return_3m": existing.return_3m}

    fresh = fetch_financial_snapshot(ticker)
    if fresh is None:
        if existing is not None:
            return {"price": existing.price, "return_1m": existing.return_1m, "return_3m": existing.return_3m}
        return None

    if existing is not None:
        existing.price = fresh["price"]
        existing.return_1m = fresh["return_1m"]
        existing.return_3m = fresh["return_3m"]
        existing.fetched_at = utcnow()
    else:
        session.add(FinancialSnapshot(
            ticker=ticker, price=fresh["price"], return_1m=fresh["return_1m"],
            return_3m=fresh["return_3m"], fetched_at=utcnow(),
        ))
    session.flush()

    return fresh
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_financial_context.py -v`
Expected: PASS (all tests, including the 6 new ones)

- [ ] **Step 5: Run the full suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/reasoning/financial_context.py backend/tests/test_financial_context.py
git commit -m "feat: add cache-then-fetch layer for financial snapshots"
```

---

### Task 4: Wire into the pipeline

**Files:**
- Modify: `backend/app/pipeline.py`
- Modify: `backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `get_or_fetch_financial_snapshot`, `detect_price_contradiction` from `app.reasoning.financial_context` (Tasks 1/3); `Company` from `app.models`
- Produces: `_persist_alert` now populates `price_at_analysis`/`return_1m`/`return_3m`/`contradiction_note` on every `AlertCompany`, and `compute_confidence`'s `reasoning_consistent` argument reflects the real contradiction check instead of a hardcoded `True`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_pipeline.py`:

```python
def test_process_new_articles_persists_financial_snapshot_and_contradiction(db_session, monkeypatch):
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    article = Article(
        source="test", url="https://example.com/financial-context",
        title="Oil prices spike", content="crude oil markets react",
    )
    db_session.add(article)
    db_session.commit()

    fake_output = AnalysisOutput(
        category="oil_energy", event_type="crude_oil",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
            time_horizon="Short-Term", reasons=["Refining margins widen."], evidence_refs=[],
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)
    monkeypatch.setattr(
        pipeline_module, "get_or_fetch_financial_snapshot",
        lambda session, ticker: {"price": 2500.0, "return_1m": -12.0, "return_3m": -20.0},
    )

    created = process_new_articles(db_session, claude_client=object())
    assert created == 1

    ac = db_session.query(AlertCompany).one()
    assert ac.price_at_analysis == 2500.0
    assert ac.return_1m == -12.0
    assert ac.return_3m == -20.0
    # Bullish call + -12% over a month (past the 5% threshold) -> a real contradiction.
    assert ac.contradiction_note is not None
    assert "bullish" in ac.contradiction_note.lower()
    assert ac.confidence_band in {"LOW", "MODERATE", "HIGH", "VERY_HIGH"}


def test_process_new_articles_no_contradiction_when_snapshot_unavailable(db_session, monkeypatch):
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()
    article = Article(
        source="test", url="https://example.com/financial-context-none",
        title="Oil prices spike", content="crude oil markets react",
    )
    db_session.add(article)
    db_session.commit()

    fake_output = AnalysisOutput(
        category="oil_energy",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="x",
            time_horizon="Short-Term",
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)
    monkeypatch.setattr(pipeline_module, "get_or_fetch_financial_snapshot", lambda session, ticker: None)

    created = process_new_articles(db_session, claude_client=object())
    assert created == 1

    ac = db_session.query(AlertCompany).one()
    assert ac.price_at_analysis is None
    assert ac.return_1m is None
    assert ac.contradiction_note is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_pipeline.py -v -k "financial_snapshot or snapshot_unavailable"`
Expected: FAIL — `AlertCompany.price_at_analysis` stays `None` even when the test monkeypatches `get_or_fetch_financial_snapshot` to return real data, because `_persist_alert` doesn't call it yet.

- [ ] **Step 3: Update pipeline.py**

```python
# backend/app/pipeline.py -- update imports:
from app.models import Alert, AlertCompany, Article, Company, utcnow
from app.reasoning.confidence import compute_confidence, source_credibility
from app.reasoning.financial_context import detect_price_contradiction, get_or_fetch_financial_snapshot
from app.reasoning.rulebook import get_rule
```

(Only `Company` is newly added to the `app.models` import list; `app.reasoning.financial_context` is a newly added import line.)

In `_alert_broadcast_payload`'s per-company dict, add the four new fields (after `"alternative_hypothesis": ac.alternative_hypothesis,`):

```python
            "alternative_hypothesis": ac.alternative_hypothesis,
            "price_at_analysis": ac.price_at_analysis,
            "return_1m": ac.return_1m,
            "return_3m": ac.return_3m,
            "contradiction_note": ac.contradiction_note,
```

In `_persist_alert`'s per-entry loop, right after the existing `health = get_calibration_health(...)` line and before the `result = compute_confidence(...)` call:

```python
        company_obj = session.get(Company, entry["company_id"])
        snapshot = get_or_fetch_financial_snapshot(session, company_obj.ticker) if company_obj else None
        contradiction_note = detect_price_contradiction(
            entry["direction"], snapshot["return_1m"] if snapshot else None,
        )
```

Then change the `compute_confidence(...)` call's `reasoning_consistent` argument:

```python
        result = compute_confidence(
            calibration_sample_count=health["sample_count"],
            calibration_hit_rate=health["hit_rate"],
            claim_count=len(reasons),
            evidence_ref_count=len(evidence_refs),
            rule_matched=bool(matched_rule_ids),
            source_credibility=source_credibility(article.source),
            reasoning_consistent=contradiction_note is None,
            article_age_hours=article_age_hours,
        )
```

(This replaces the old `reasoning_consistent=True,` line and its explanatory comment — the comment is no longer accurate now that a real check exists.)

Finally, add the four new fields to the `AlertCompany(...)` construction (after `rulebook_ids_json=json.dumps(matched_rule_ids),`):

```python
            rulebook_ids_json=json.dumps(matched_rule_ids),
            price_at_analysis=snapshot["price"] if snapshot else None,
            return_1m=snapshot["return_1m"] if snapshot else None,
            return_3m=snapshot["return_3m"] if snapshot else None,
            contradiction_note=contradiction_note,
        ))
```

No changes are needed to `process_new_articles`'s dedup-reuse branch — `_persist_alert`'s docstring already documents that calibration and confidence are "always looked up/computed fresh" regardless of which path called it, and this financial-context lookup follows the same rule automatically since it lives inside `_persist_alert` itself, not in the `entries` dicts passed into it.

- [ ] **Step 4: Run the two new tests in isolation to verify they pass**

Run: `cd backend && python -m pytest tests/test_pipeline.py -v -k "financial_snapshot_and_contradiction or snapshot_unavailable"`
Expected: PASS (both new tests — they each monkeypatch `get_or_fetch_financial_snapshot` themselves, so they never touch the network regardless of what the rest of the file does)

**Do not run the whole file yet.** Every pre-existing test in `test_pipeline.py` calls `process_new_articles`, which now calls `get_or_fetch_financial_snapshot` for every resolved company — none of those pre-existing tests monkeypatch it, so without the fix in the next step, running the full file would make real yfinance network calls from dozens of tests.

- [ ] **Step 4a: Add an autouse fixture stub so pre-existing tests never hit the network**

Add to `backend/tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def _no_real_financial_snapshot_fetch(monkeypatch):
    # process_new_articles now calls get_or_fetch_financial_snapshot for
    # every resolved company, which would otherwise make a real yfinance
    # network call in every pipeline test that doesn't care about this
    # feature. Stub it to "no data" by default -- individual tests that DO
    # care about financial-context behavior override this via their own
    # monkeypatch.setattr, which takes precedence over this autouse default.
    monkeypatch.setattr("app.pipeline.get_or_fetch_financial_snapshot", lambda session, ticker: None)
```

This follows the exact same pattern already used in that file for `_no_real_og_image_fetch` and `_no_real_feed_fetch`.

- [ ] **Step 5: Run the full `test_pipeline.py` file now that the network stub is in place**

Run: `cd backend && python -m pytest tests/test_pipeline.py -v`
Expected: PASS (all tests, including every pre-existing one — now that the autouse fixture stubs `get_or_fetch_financial_snapshot` to `None` by default, no test makes a real network call unless it explicitly overrides the stub, as the two new tests in this task do)

- [ ] **Step 6: Run the full suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: PASS (all tests; the suite's wall-clock time should be roughly the same as before this task — a slowdown would indicate the network stub isn't actually being applied somewhere)

- [ ] **Step 7: Commit**

```bash
git add backend/app/pipeline.py backend/tests/test_pipeline.py backend/tests/conftest.py
git commit -m "feat: wire financial grounding and contradiction detection into the pipeline"
```

---

### Task 5: Expose via the alerts API

**Files:**
- Modify: `backend/app/routers/alerts.py`
- Modify: `backend/tests/test_api.py`

**Interfaces:**
- Produces: each company object in `GET /api/alerts`/`GET /api/alerts/{id}` responses gains `price_at_analysis`, `return_1m`, `return_3m`, `contradiction_note`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_api.py`:

```python
def test_list_alerts_includes_financial_context_fields(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    article = Article(source="test", url="https://example.com/financial-fields", title="Test headline", status="ANALYZED", category="oil_energy")
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
        price_at_analysis=2500.5, return_1m=-12.0, return_3m=-20.0,
        contradiction_note="Price down 12.0% over the past month despite bullish call.",
    ))
    db_session.commit()

    response = client.get("/api/alerts")

    assert response.status_code == 200
    body = response.json()
    company_payload = body[0]["companies"][0]
    assert company_payload["price_at_analysis"] == 2500.5
    assert company_payload["return_1m"] == -12.0
    assert company_payload["return_3m"] == -20.0
    assert company_payload["contradiction_note"] == "Price down 12.0% over the past month despite bullish call."

    app.dependency_overrides.clear()


def test_list_alerts_defaults_financial_context_fields_for_legacy_rows(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    article = Article(source="test", url="https://example.com/financial-fields-legacy", title="Legacy", status="ANALYZED", category="oil_energy")
    db_session.add(article)
    db_session.commit()
    company = Company(ticker="LEGACY.NS", name="Legacy Co", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="legacy row",
        basis="direct_mention", confidence="llm_estimate",
    ))
    db_session.commit()

    response = client.get("/api/alerts")

    assert response.status_code == 200
    company_payload = response.json()[0]["companies"][0]
    assert company_payload["price_at_analysis"] is None
    assert company_payload["contradiction_note"] is None

    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_api.py -v -k financial_context`
Expected: FAIL — `KeyError: 'price_at_analysis'` (not yet in the response body)

- [ ] **Step 3: Update `_serialize_alert`**

```python
# backend/app/routers/alerts.py -- in _serialize_alert's per-company dict, add after "alternative_hypothesis": ac.alternative_hypothesis,:
            "alternative_hypothesis": ac.alternative_hypothesis,
            "price_at_analysis": ac.price_at_analysis,
            "return_1m": ac.return_1m,
            "return_3m": ac.return_3m,
            "contradiction_note": ac.contradiction_note,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_api.py -v`
Expected: PASS (all tests, including pre-existing ones — every new response field is additive)

- [ ] **Step 5: Run the full suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/alerts.py backend/tests/test_api.py
git commit -m "feat: expose financial context and contradiction fields via the alerts API"
```

---

### Task 6: Frontend types

**Files:**
- Modify: `frontend/src/lib/api.ts`

**Interfaces:**
- Produces: `AlertCompany` gains `price_at_analysis?: number | null`, `return_1m?: number | null`, `return_3m?: number | null`, `contradiction_note?: string | null`

This task has no runtime behavior of its own (types only) — no test file. Verification is that the whole frontend still typechecks.

- [ ] **Step 1: Edit the interface**

```ts
// frontend/src/lib/api.ts -- add to the end of the AlertCompany interface (after confidence_penalties?: string[];):
  confidence_contributors?: string[];
  confidence_penalties?: string[];
  // Financial grounding + contradiction detection (see docs/superpowers/
  // specs/2026-07-16-financial-grounding-contradiction-detection-design.md).
  // Optional/nullable for the same reason as the reasoning-engine fields
  // above: legacy alerts and existing test fixtures don't have these.
  price_at_analysis?: number | null;
  return_1m?: number | null;
  return_3m?: number | null;
  contradiction_note?: string | null;
}
```

(This shows the last existing field plus the four new ones — only add the four new lines; `confidence_contributors`/`confidence_penalties` already exist and are shown here purely as the anchor point.)

- [ ] **Step 2: Typecheck the whole frontend**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 3: Run the full frontend test suite**

Run: `cd frontend && npm test -- --run`
Expected: all existing tests still pass (this task changes types only)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat: add financial context fields to AlertCompany type"
```

---

### Task 7: i18n keys

**Files:**
- Modify: `frontend/src/lib/i18n.ts`

**Interfaces:**
- Produces: new `TranslationKey` values: `reasoning.factsHeading`, `reasoning.oneMonthReturnLabel`, `reasoning.threeMonthReturnLabel`

- [ ] **Step 1: Add the new catalog entries**

Insert into the `CATALOG` object in `frontend/src/lib/i18n.ts`, immediately after the existing `'reasoning.evidenceHistorical'` entry (the most recently added `reasoning.*` key), following the exact same all-English-for-now pattern (and the same justifying comment reference) as every other `reasoning.*` key added by the prior two features:

```ts
  'reasoning.factsHeading': {
    en: 'Facts', hi: 'Facts', mr: 'Facts', gu: 'Facts', ml: 'Facts', te: 'Facts', ta: 'Facts', kn: 'Facts',
    pa: 'Facts', bn: 'Facts',
  },
  'reasoning.oneMonthReturnLabel': {
    en: '1M return', hi: '1M return', mr: '1M return', gu: '1M return', ml: '1M return', te: '1M return',
    ta: '1M return', kn: '1M return', pa: '1M return', bn: '1M return',
  },
  'reasoning.threeMonthReturnLabel': {
    en: '3M return', hi: '3M return', mr: '3M return', gu: '3M return', ml: '3M return', te: '3M return',
    ta: '3M return', kn: '3M return', pa: '3M return', bn: '3M return',
  },
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 3: Run the full frontend test suite**

Run: `cd frontend && npm test -- --run`
Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/i18n.ts
git commit -m "feat: add i18n keys for the Facts section"
```

---

### Task 8: ReasoningPanel — Facts section

**Files:**
- Modify: `frontend/src/components/ReasoningPanel.tsx`
- Modify: `frontend/src/components/ReasoningPanel.test.tsx`

**Interfaces:**
- Consumes: `AlertCompany.price_at_analysis`/`return_1m`/`return_3m`/`contradiction_note` (Task 6), the 3 new i18n keys (Task 7)
- Produces: `ReasoningPanel` renders a Facts block whenever `company.price_at_analysis` is non-null, independent of the existing `hasEvidenceSection` gate

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/components/ReasoningPanel.test.tsx`:

```tsx
describe('ReasoningPanel Facts section', () => {
  it('omits the Facts section for a legacy alert with no price data', () => {
    render(<ReasoningPanel company={base} />);
    expect(screen.queryByText('Facts')).not.toBeInTheDocument();
  });

  it('shows price and returns for an Indian company using the rupee symbol', () => {
    const withFacts: AlertCompany = {
      ...base, market: 'IN',
      price_at_analysis: 2500.5, return_1m: 8.3, return_3m: -2.1,
    };
    render(<ReasoningPanel company={withFacts} />);
    expect(screen.getByText('Facts')).toBeInTheDocument();
    expect(screen.getByText('₹2500.50')).toBeInTheDocument();
    expect(screen.getByText(/1M return: \+8\.3%/)).toBeInTheDocument();
    expect(screen.getByText(/3M return: -2\.1%/)).toBeInTheDocument();
  });

  it('uses the dollar symbol for a global company', () => {
    const withFacts: AlertCompany = { ...base, market: 'GLOBAL', price_at_analysis: 150.25 };
    render(<ReasoningPanel company={withFacts} />);
    expect(screen.getByText('$150.25')).toBeInTheDocument();
  });

  it('omits an individual return line when that return is null', () => {
    const withFacts: AlertCompany = { ...base, price_at_analysis: 100.0, return_1m: null, return_3m: 4.0 };
    render(<ReasoningPanel company={withFacts} />);
    expect(screen.queryByText(/1M return/)).not.toBeInTheDocument();
    expect(screen.getByText(/3M return: \+4\.0%/)).toBeInTheDocument();
  });

  it('shows a prominent contradiction warning when present', () => {
    const withContradiction: AlertCompany = {
      ...base, price_at_analysis: 2500.0, return_1m: -12.0,
      contradiction_note: 'Price down 12.0% over the past month despite bullish call.',
    };
    render(<ReasoningPanel company={withContradiction} />);
    expect(screen.getByText('Price down 12.0% over the past month despite bullish call.')).toBeInTheDocument();
  });

  it('omits the contradiction line when contradiction_note is absent', () => {
    const withFacts: AlertCompany = { ...base, price_at_analysis: 2500.0, return_1m: 3.0 };
    render(<ReasoningPanel company={withFacts} />);
    expect(screen.queryByText(/despite/)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/ReasoningPanel.test.tsx`
Expected: FAIL — no "Facts" text exists yet

- [ ] **Step 3: Implement the Facts section**

Insert into `frontend/src/components/ReasoningPanel.tsx`, immediately after the existing `<p className="mt-2 text-xs text-muted">{precedentLine(company, language)}</p>` line and before the existing `{hasEvidenceSection && (...)}` block:

```tsx
      {company.price_at_analysis != null && (
        <div className="mt-3 border-t border-hairline pt-2">
          <p className="text-xs uppercase tracking-widest text-muted">{t('reasoning.factsHeading')}</p>
          <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink">
            <span>{company.market === 'IN' ? '₹' : '$'}{company.price_at_analysis.toFixed(2)}</span>
            {company.return_1m != null && (
              <span className={company.return_1m >= 0 ? 'text-bullish' : 'text-bearish'}>
                {t('reasoning.oneMonthReturnLabel')}: {company.return_1m >= 0 ? '+' : ''}
                {company.return_1m.toFixed(1)}%
              </span>
            )}
            {company.return_3m != null && (
              <span className={company.return_3m >= 0 ? 'text-bullish' : 'text-bearish'}>
                {t('reasoning.threeMonthReturnLabel')}: {company.return_3m >= 0 ? '+' : ''}
                {company.return_3m.toFixed(1)}%
              </span>
            )}
          </div>
          {company.contradiction_note && (
            <p className="mt-1.5 flex items-start gap-1.5 text-bearish">
              <span aria-hidden="true">⚠</span>
              <span>{company.contradiction_note}</span>
            </p>
          )}
        </div>
      )}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/ReasoningPanel.test.tsx`
Expected: PASS (all tests, including every pre-existing one — the Facts block is a pure addition gated on a field that's `undefined`/`null` for every pre-existing fixture, so it never renders for those)

- [ ] **Step 5: Run the full frontend test suite**

Run: `cd frontend && npm test -- --run`
Expected: all tests pass (this also re-confirms `CompanyChip.test.tsx` and `ConfidenceTree.test.tsx` still pass unmodified, since neither of their fixtures set `price_at_analysis`)

- [ ] **Step 6: Typecheck one more time**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/ReasoningPanel.tsx frontend/src/components/ReasoningPanel.test.tsx
git commit -m "feat: add Facts section (price, returns, contradiction warning) to ReasoningPanel"
```

---

## Explicitly out of scope for this plan

`Company.market_cap` backfill. Merging with the Zerodha Kite live-price system. `CompanyPage.tsx`'s separate "Latest Signal" section. Sub-projects 2-5 of the reasoning-quality roadmap (pgvector historical retrieval, curated company relationship data, automated flywheel tuning) — each gets its own design/plan/build cycle.
