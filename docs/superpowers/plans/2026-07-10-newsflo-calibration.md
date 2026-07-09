# NewsFlo Calibration & Outcome Tracking Implementation Plan (Plan 2 of 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make NewsFlo's magnitude estimates improve over time: record actual post-alert price moves (yfinance) into a calibration-samples database via a scheduled outcome tracker, and once a (category, company) pair has enough samples, blend those empirical outcomes into future alerts' magnitude ranges — flagging each alert company as `llm_estimate` or `calibrated`.

**Architecture:** Extends the Plan 1 modular monolith. Adds two new modules — `app.outcomes` (price fetcher + scheduled tracker) and `app.calibration` (blending math) — plus a new `CalibrationSample` model and a `confidence` column on `AlertCompany`. An APScheduler `BackgroundScheduler` (strictly opt-in) drives the tracker at 1d/3d/7d horizons. The existing `process_new_articles` pipeline gains a calibration lookup between company resolution and alert-company creation. No Alembic — SQLAlchemy `create_all` handles the new table/column in tests, as in Plan 1.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, Pydantic v2, `yfinance` + `pandas` (price data), `apscheduler` (scheduled outcome tracker), `pytest` (testing). Calibration blending uses `statistics.pstdev` from the stdlib.

## Global Constraints

- Database schema must stay portable between SQLite (tests) and PostgreSQL (production) — no native Postgres-only column types (no `ENUM`, no `ARRAY`); enums are plain `String` columns validated in Python.
- No live network calls in any test — news fetching, Claude API calls, and price lookups are always mocked/monkeypatched. This now also covers yfinance: `app.outcomes.price_fetcher.yf` must always be monkeypatched in tests, never hitting real Yahoo Finance servers.
- News sources for v1 are free RSS/APIs only (per spec) — no paid data sources.
- Market focus is Indian stocks (NSE/BSE) for v1 — tickers use `.NS` suffix.
- Claude structured output must go through forced tool-use (a `record_analysis` tool), never free-text JSON parsing.
- Company sector values are constrained to a fixed taxonomy (`oil_gas`, `banking`, `auto`, `it`, `pharma`, `fmcg`, `metals`, `telecom`, `infra`, `other`) so sector-based company resolution is an exact match, not fuzzy text matching.
- Frontend for this plan is a single static HTML/JS page (no React/build step) — the full CRED-style UI is Plan 4.
- The scheduler must never start automatically during tests or default `uvicorn app.main:app` runs — it is strictly opt-in via `ENABLE_SCHEDULER=true`.
- Calibration blending uses **population** standard deviation (`statistics.pstdev`), not sample standard deviation (`statistics.stdev`) — this must be exact, since a task reviewer will hand-verify the arithmetic.
- One commit per task, at the end of that task's steps.

---

## Task 1: Calibration DB Models

**Files:**
- Modify: `backend/app/models.py`
- Test: `backend/tests/test_calibration_models.py`

**Interfaces:**
- Consumes: `Base` (`app.db`), `utcnow` helper and `Company`/`Article`/`Alert`/`AlertCompany` models (`app.models`, Plan 1).
- Produces: `AlertCompany.confidence` column (`String`, not null, default `"llm_estimate"`, values `"llm_estimate"` | `"calibrated"`) and a new `CalibrationSample` model (`app.models`) with columns `id`, `alert_company_id`, `category`, `company_id`, `direction`, `magnitude_actual`, `horizon_days`, `sampled_at`, and a unique constraint on `(alert_company_id, horizon_days)`. Task 3 (blender), Task 4 (tracker), Task 6 (pipeline), Task 7 (API) all rely on these exact names.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_calibration_models.py`:

```python
import pytest

from app.models import Alert, AlertCompany, Article, CalibrationSample, Company


def _make_alert_company(session):
    company = Company(
        ticker="RELIANCE.NS", name="Reliance Industries",
        sector="oil_gas", index_tier="NIFTY50", market_cap=1.0,
    )
    article = Article(source="test", url="https://example.com/cal-model", title="Oil news", content="")
    session.add_all([company, article])
    session.commit()

    alert = Alert(article_id=article.id, category="oil_energy")
    session.add(alert)
    session.commit()

    ac = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=2.0, magnitude_high=4.0, rationale="margin", basis="direct_mention",
    )
    session.add(ac)
    session.commit()
    return ac


def test_alert_company_confidence_defaults_to_llm_estimate(db_session):
    ac = _make_alert_company(db_session)
    fetched = db_session.query(AlertCompany).filter_by(id=ac.id).one()
    assert fetched.confidence == "llm_estimate"


def test_create_calibration_sample(db_session):
    ac = _make_alert_company(db_session)
    sample = CalibrationSample(
        alert_company_id=ac.id, category="oil_energy", company_id=ac.company_id,
        direction="bullish", magnitude_actual=3.2, horizon_days=3,
    )
    db_session.add(sample)
    db_session.commit()

    fetched = db_session.query(CalibrationSample).one()
    assert fetched.magnitude_actual == 3.2
    assert fetched.horizon_days == 3
    assert fetched.sampled_at is not None


def test_calibration_sample_unique_on_alert_company_and_horizon(db_session):
    ac = _make_alert_company(db_session)
    db_session.add(CalibrationSample(
        alert_company_id=ac.id, category="oil_energy", company_id=ac.company_id,
        direction="bullish", magnitude_actual=1.0, horizon_days=1,
    ))
    db_session.commit()

    db_session.add(CalibrationSample(
        alert_company_id=ac.id, category="oil_energy", company_id=ac.company_id,
        direction="bearish", magnitude_actual=-2.0, horizon_days=1,
    ))
    with pytest.raises(Exception):
        db_session.commit()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_calibration_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'CalibrationSample' from 'app.models'`.

- [ ] **Step 3: Implement the model changes**

Replace the entire contents of `backend/app/models.py` with:

```python
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True)
    ticker = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)
    sector = Column(String, nullable=False)
    index_tier = Column(String, nullable=False)  # NIFTY50 | NIFTY100 | NIFTY500 | OTHER
    market_cap = Column(Float, nullable=True)


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (UniqueConstraint("url", name="uq_articles_url"),)

    id = Column(Integer, primary_key=True)
    source = Column(String, nullable=False)
    url = Column(String, nullable=False)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False, default="")
    published_at = Column(DateTime(timezone=True), nullable=True)
    fetched_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    status = Column(String, nullable=False, default="NEW")  # NEW|FILTERED|CATEGORIZED|ANALYZED|ANALYSIS_FAILED
    category = Column(String, nullable=True)

    alerts = relationship("Alert", back_populates="article")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False)
    category = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    article = relationship("Article", back_populates="alerts")
    companies = relationship("AlertCompany", back_populates="alert")


class AlertCompany(Base):
    __tablename__ = "alert_companies"

    id = Column(Integer, primary_key=True)
    alert_id = Column(Integer, ForeignKey("alerts.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    direction = Column(String, nullable=False)  # bullish | bearish
    magnitude_low = Column(Float, nullable=False)
    magnitude_high = Column(Float, nullable=False)
    rationale = Column(Text, nullable=False)
    basis = Column(String, nullable=False)  # direct_mention | sector_inference
    confidence = Column(String, nullable=False, default="llm_estimate")  # llm_estimate | calibrated

    alert = relationship("Alert", back_populates="companies")
    company = relationship("Company")


class CalibrationSample(Base):
    __tablename__ = "calibration_samples"
    __table_args__ = (
        UniqueConstraint("alert_company_id", "horizon_days", name="uq_calibration_alert_company_horizon"),
    )

    id = Column(Integer, primary_key=True)
    alert_company_id = Column(Integer, ForeignKey("alert_companies.id"), nullable=False)
    category = Column(String, nullable=False)  # copied from the Alert's category at sample time
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    direction = Column(String, nullable=False)  # bullish | bearish (sign of magnitude_actual)
    magnitude_actual = Column(Float, nullable=False)  # actual % price move over the horizon
    horizon_days = Column(Integer, nullable=False)  # 1 | 3 | 7
    sampled_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest tests/test_calibration_models.py -v`
Expected: `3 passed`

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `cd backend && .venv/Scripts/pytest tests/ -v`
Expected: all previously-passing tests still pass, plus the 3 new ones.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models.py backend/tests/test_calibration_models.py
git commit -m "feat: add CalibrationSample model and AlertCompany.confidence column"
```

---

## Task 2: Price Fetcher

**Files:**
- Create: `backend/app/outcomes/__init__.py`
- Create: `backend/app/outcomes/price_fetcher.py`
- Modify: `backend/requirements.txt`
- Test: `backend/tests/test_price_fetcher.py`

**Interfaces:**
- Produces: `fetch_price_change_pct(ticker: str, start_date: datetime, horizon_days: int) -> float | None` (`app.outcomes.price_fetcher`) and a module-level `yf` (aliased `import yfinance as yf`) that tests monkeypatch via `app.outcomes.price_fetcher.yf`. Task 4 (tracker) imports `fetch_price_change_pct` as its default `fetch_fn`.

- [ ] **Step 1: Add dependencies**

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
```

Install into the existing venv:

```bash
cd backend
.venv/Scripts/pip install -r requirements.txt
```

- [ ] **Step 2: Write the failing test**

`backend/tests/test_price_fetcher.py`:

```python
from datetime import datetime, timezone

import pandas as pd
import pytest

from app.outcomes import price_fetcher


class FakeTicker:
    def __init__(self, df):
        self._df = df

    def history(self, start, end):
        return self._df


def test_fetch_price_change_pct_computes_positive_move(monkeypatch):
    df = pd.DataFrame({"Close": [100.0, 105.0]})
    monkeypatch.setattr(price_fetcher.yf, "Ticker", lambda ticker: FakeTicker(df))

    result = price_fetcher.fetch_price_change_pct(
        "RELIANCE.NS", datetime(2026, 1, 1, tzinfo=timezone.utc), 1,
    )

    assert result == pytest.approx(5.0)


def test_fetch_price_change_pct_returns_none_for_empty(monkeypatch):
    df = pd.DataFrame({"Close": []})
    monkeypatch.setattr(price_fetcher.yf, "Ticker", lambda ticker: FakeTicker(df))

    result = price_fetcher.fetch_price_change_pct(
        "RELIANCE.NS", datetime(2026, 1, 1, tzinfo=timezone.utc), 3,
    )

    assert result is None


def test_fetch_price_change_pct_returns_none_on_exception(monkeypatch):
    def boom(ticker):
        raise RuntimeError("network down")

    monkeypatch.setattr(price_fetcher.yf, "Ticker", boom)

    result = price_fetcher.fetch_price_change_pct(
        "RELIANCE.NS", datetime(2026, 1, 1, tzinfo=timezone.utc), 7,
    )

    assert result is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_price_fetcher.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.outcomes'`.

- [ ] **Step 4: Implement the price fetcher**

`backend/app/outcomes/__init__.py`: empty file.

`backend/app/outcomes/price_fetcher.py`:

```python
from datetime import datetime, timedelta

import yfinance as yf


def fetch_price_change_pct(ticker: str, start_date: datetime, horizon_days: int) -> float | None:
    """Return the % price change for ``ticker`` over ``horizon_days`` starting at
    ``start_date``, or ``None`` if data is unavailable or the fetch fails.

    A ``None`` result means "skip, retry on the next scheduled run" — a single
    ticker failure never blocks the rest of a batch (see spec error handling).
    """
    try:
        history = yf.Ticker(ticker).history(
            start=start_date.date(),
            end=(start_date + timedelta(days=horizon_days + 1)).date(),
        )
        close = history["Close"]
        if len(close) < 2:
            return None
        first = close.iloc[0]
        last = close.iloc[-1]
        return float((last - first) / first * 100)
    except Exception:
        return None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest tests/test_price_fetcher.py -v`
Expected: `3 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/requirements.txt backend/app/outcomes/__init__.py backend/app/outcomes/price_fetcher.py backend/tests/test_price_fetcher.py
git commit -m "feat: add yfinance-backed price-change fetcher"
```

---

## Task 3: Calibration Blender

**Files:**
- Create: `backend/app/calibration/__init__.py`
- Create: `backend/app/calibration/blender.py`
- Test: `backend/tests/test_blender.py`

**Interfaces:**
- Consumes: `CalibrationSample` model (`app.models`, Task 1).
- Produces: `CALIBRATION_SAMPLE_THRESHOLD = 5` (module constant) and `get_calibrated_magnitude(session: Session, category: str, company_id: int) -> tuple[float, float] | None` (`app.calibration.blender`). Returns `(low, high)` where `low = mean - pstdev` and `high = mean + pstdev` over `magnitude_actual` of all matching samples, or `None` when fewer than the threshold. Task 6 (pipeline) calls this per resolved company.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_blender.py`:

```python
import pytest

from app.calibration.blender import CALIBRATION_SAMPLE_THRESHOLD, get_calibrated_magnitude
from app.models import CalibrationSample


def _add_sample(session, category, company_id, magnitude_actual, alert_company_id, horizon_days):
    session.add(CalibrationSample(
        alert_company_id=alert_company_id, category=category, company_id=company_id,
        direction="bullish" if magnitude_actual >= 0 else "bearish",
        magnitude_actual=magnitude_actual, horizon_days=horizon_days,
    ))


def test_threshold_is_five():
    assert CALIBRATION_SAMPLE_THRESHOLD == 5


def test_returns_none_below_threshold(db_session):
    for i, value in enumerate([1.0, 2.0, 3.0, 4.0]):  # 4 samples, below threshold
        _add_sample(db_session, "oil_energy", 1, value, alert_company_id=i + 1, horizon_days=1)
    db_session.commit()

    assert get_calibrated_magnitude(db_session, category="oil_energy", company_id=1) is None


def test_returns_mean_plus_minus_pstdev_at_threshold(db_session):
    # 5 samples of [1, 2, 3, 4, 5] -> mean = 3.0, pstdev = sqrt(2) ~= 1.41421356
    for i, value in enumerate([1.0, 2.0, 3.0, 4.0, 5.0]):
        _add_sample(db_session, "oil_energy", 1, value, alert_company_id=i + 1, horizon_days=1)
    db_session.commit()

    result = get_calibrated_magnitude(db_session, category="oil_energy", company_id=1)

    assert result is not None
    low, high = result
    assert low == pytest.approx(3.0 - 2 ** 0.5)
    assert high == pytest.approx(3.0 + 2 ** 0.5)


def test_excludes_other_category_and_company(db_session):
    # 5 matching samples of [10, 10, 10, 10, 10] -> mean = 10.0, pstdev = 0 -> (10.0, 10.0)
    for i, value in enumerate([10.0, 10.0, 10.0, 10.0, 10.0]):
        _add_sample(db_session, "oil_energy", 1, value, alert_company_id=i + 1, horizon_days=1)
    # noise that must NOT be included in the (oil_energy, company 1) calculation
    _add_sample(db_session, "banking", 1, -50.0, alert_company_id=100, horizon_days=1)
    _add_sample(db_session, "oil_energy", 2, -50.0, alert_company_id=101, horizon_days=1)
    db_session.commit()

    result = get_calibrated_magnitude(db_session, category="oil_energy", company_id=1)

    assert result == pytest.approx((10.0, 10.0))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_blender.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.calibration'`.

- [ ] **Step 3: Implement the blender**

`backend/app/calibration/__init__.py`: empty file.

`backend/app/calibration/blender.py`:

```python
import statistics

from sqlalchemy.orm import Session

from app.models import CalibrationSample

CALIBRATION_SAMPLE_THRESHOLD = 5


def get_calibrated_magnitude(session: Session, category: str, company_id: int) -> tuple[float, float] | None:
    """Blend historical outcomes for a (category, company) pair into a magnitude
    range. Returns ``(low, high)`` = ``(mean - pstdev, mean + pstdev)`` over the
    actual moves once at least ``CALIBRATION_SAMPLE_THRESHOLD`` samples exist,
    else ``None`` (caller keeps the LLM's own estimate).
    """
    samples = (
        session.query(CalibrationSample)
        .filter(CalibrationSample.category == category)
        .filter(CalibrationSample.company_id == company_id)
        .all()
    )
    if len(samples) < CALIBRATION_SAMPLE_THRESHOLD:
        return None

    values = [s.magnitude_actual for s in samples]
    mean = statistics.mean(values)
    pstdev = statistics.pstdev(values)  # population stdev — full sample set, not a sample of a larger population
    if pstdev == 0:
        return (mean, mean)
    return (mean - pstdev, mean + pstdev)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest tests/test_blender.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/calibration/__init__.py backend/app/calibration/blender.py backend/tests/test_blender.py
git commit -m "feat: add calibration blender (mean +/- population stdev)"
```

---

## Task 4: Outcome Tracker

**Files:**
- Create: `backend/app/outcomes/tracker.py`
- Test: `backend/tests/test_tracker.py`

**Interfaces:**
- Consumes: `Alert`/`AlertCompany`/`CalibrationSample` models (Task 1), `fetch_price_change_pct` (Task 2).
- Produces: `check_pending_outcomes(session: Session, horizon_days: int, fetch_fn=fetch_price_change_pct) -> int` (`app.outcomes.tracker`) — samples every not-yet-sampled `AlertCompany` whose `Alert.created_at <= now - horizon_days`, writes a `CalibrationSample` per successful fetch, returns the count created. Idempotent via the `(alert_company_id, horizon_days)` unique constraint. Task 5 (scheduler) calls this per horizon.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_tracker.py`:

```python
from datetime import datetime, timedelta, timezone

from app.models import Alert, AlertCompany, Article, CalibrationSample, Company
from app.outcomes.tracker import check_pending_outcomes


def _seed_alert_company(session, ticker, url, days_old):
    company = Company(ticker=ticker, name=f"Co {ticker}", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    article = Article(source="test", url=url, title="Oil news", content="")
    session.add_all([company, article])
    session.commit()

    alert = Alert(
        article_id=article.id, category="oil_energy",
        created_at=datetime.now(timezone.utc) - timedelta(days=days_old),
    )
    session.add(alert)
    session.commit()

    ac = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="x", basis="direct_mention",
    )
    session.add(ac)
    session.commit()
    return ac


def test_check_pending_outcomes_creates_sample(db_session):
    _seed_alert_company(db_session, "RELIANCE.NS", "https://example.com/1", days_old=2)

    created = check_pending_outcomes(db_session, horizon_days=1, fetch_fn=lambda t, s, h: 5.0)

    assert created == 1
    sample = db_session.query(CalibrationSample).one()
    assert sample.direction == "bullish"
    assert sample.magnitude_actual == 5.0
    assert sample.horizon_days == 1
    assert sample.category == "oil_energy"


def test_check_pending_outcomes_is_idempotent(db_session):
    _seed_alert_company(db_session, "RELIANCE.NS", "https://example.com/1", days_old=2)

    first = check_pending_outcomes(db_session, horizon_days=1, fetch_fn=lambda t, s, h: 5.0)
    second = check_pending_outcomes(db_session, horizon_days=1, fetch_fn=lambda t, s, h: 5.0)

    assert first == 1
    assert second == 0
    assert db_session.query(CalibrationSample).count() == 1


def test_check_pending_outcomes_skips_alerts_younger_than_horizon(db_session):
    _seed_alert_company(db_session, "RELIANCE.NS", "https://example.com/1", days_old=2)

    created = check_pending_outcomes(db_session, horizon_days=7, fetch_fn=lambda t, s, h: 5.0)

    assert created == 0
    assert db_session.query(CalibrationSample).count() == 0


def test_check_pending_outcomes_skips_none_but_continues_batch(db_session):
    _seed_alert_company(db_session, "GOOD.NS", "https://example.com/good", days_old=2)
    _seed_alert_company(db_session, "BAD.NS", "https://example.com/bad", days_old=2)

    def fetch_fn(ticker, start_date, horizon_days):
        if ticker == "BAD.NS":
            return None
        return 3.0

    created = check_pending_outcomes(db_session, horizon_days=1, fetch_fn=fetch_fn)

    assert created == 1
    samples = db_session.query(CalibrationSample).all()
    assert len(samples) == 1
    assert samples[0].magnitude_actual == 3.0  # the GOOD ticker was sampled; BAD (None) was skipped
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_tracker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.outcomes.tracker'`.

- [ ] **Step 3: Implement the tracker**

`backend/app/outcomes/tracker.py`:

```python
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import Alert, AlertCompany, CalibrationSample
from app.outcomes.price_fetcher import fetch_price_change_pct


def check_pending_outcomes(session: Session, horizon_days: int, fetch_fn=fetch_price_change_pct) -> int:
    """For every AlertCompany whose Alert is at least ``horizon_days`` old and has
    no CalibrationSample yet for this horizon, fetch the actual price move and
    record a sample. A ``None`` fetch result is skipped (retried next run) and
    never blocks the rest of the batch. Returns the number of samples created.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=horizon_days)

    already_sampled_ids = (
        session.query(CalibrationSample.alert_company_id)
        .filter(CalibrationSample.horizon_days == horizon_days)
    )

    pending = (
        session.query(AlertCompany)
        .join(AlertCompany.alert)
        .filter(Alert.created_at <= cutoff)
        .filter(~AlertCompany.id.in_(already_sampled_ids))
        .all()
    )

    created = 0
    for ac in pending:
        result = fetch_fn(ac.company.ticker, ac.alert.created_at, horizon_days)
        if result is None:
            continue
        session.add(CalibrationSample(
            alert_company_id=ac.id,
            category=ac.alert.category,
            company_id=ac.company_id,
            direction="bullish" if result >= 0 else "bearish",
            magnitude_actual=result,
            horizon_days=horizon_days,
        ))
        session.commit()
        created += 1

    return created
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest tests/test_tracker.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/outcomes/tracker.py backend/tests/test_tracker.py
git commit -m "feat: add idempotent outcome tracker that samples actual price moves"
```

---

## Task 5: Scheduler Wiring

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/app/config.py`
- Create: `backend/app/scheduler.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Consumes: `SessionLocal` (`app.db`, Plan 1), `check_pending_outcomes` (Task 4), `settings` (`app.config`).
- Produces: `settings.enable_scheduler: bool` (`app.config`, default `False`) and `start_scheduler() -> None` (`app.scheduler`) — a strictly opt-in `BackgroundScheduler` running the outcome tracker for horizons 1/3/7 every 60 minutes, each job opening and closing its own `SessionLocal()` and swallowing/logging exceptions. `app.main` starts it only when `settings.enable_scheduler` is true.

- [ ] **Step 1: Add the apscheduler dependency**

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
```

Install into the existing venv:

```bash
cd backend
.venv/Scripts/pip install -r requirements.txt
```

- [ ] **Step 2: Add the `enable_scheduler` setting**

Replace the entire contents of `backend/app/config.py` with:

```python
import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = os.environ.get("DATABASE_URL", "sqlite:///./newsflo.db")
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    enable_scheduler: bool = os.environ.get("ENABLE_SCHEDULER", "false").lower() == "true"


settings = Settings()
```

- [ ] **Step 3: Implement the scheduler module**

`backend/app/scheduler.py`:

```python
import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.db import SessionLocal
from app.outcomes.tracker import check_pending_outcomes

logger = logging.getLogger(__name__)

# Module-level reference so the scheduler thread is not garbage-collected.
_scheduler: BackgroundScheduler | None = None

HORIZONS = (1, 3, 7)


def _run_horizon(horizon_days: int) -> None:
    """Open a fresh session, run the outcome tracker for one horizon, and always
    close the session. Any error is logged, never raised, so one failing run does
    not crash the scheduler thread."""
    session = SessionLocal()
    try:
        check_pending_outcomes(session, horizon_days)
    except Exception:
        logger.exception("Outcome tracker run failed for horizon_days=%s", horizon_days)
    finally:
        session.close()


def start_scheduler() -> None:
    global _scheduler
    scheduler = BackgroundScheduler()
    for horizon in HORIZONS:
        scheduler.add_job(
            _run_horizon,
            trigger="interval",
            minutes=60,
            args=[horizon],
            id=f"outcome_tracker_{horizon}d",
        )
    scheduler.start()
    _scheduler = scheduler
```

- [ ] **Step 4: Wire it into `main.py` (opt-in only)**

Replace the entire contents of `backend/app/main.py` with:

```python
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import init_db
from app.routers import alerts, articles
from app.scheduler import start_scheduler

app = FastAPI(title="NewsFlo")

app.include_router(articles.router)
app.include_router(alerts.router)

init_db()

if settings.enable_scheduler:
    start_scheduler()

app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
```

- [ ] **Step 5: Confirm the module imports cleanly without starting a thread**

Run: `cd backend && .venv/Scripts/python -c "from app.scheduler import start_scheduler; print('scheduler import ok')"`
Expected: prints `scheduler import ok` with no error (importing does NOT start the scheduler).

- [ ] **Step 6: Confirm the full suite still passes with the scheduler defaulting off**

Run: `cd backend && .venv/Scripts/pytest tests/ -v`
Expected: all tests pass. Because `ENABLE_SCHEDULER` is unset, `settings.enable_scheduler` is `False`, so importing `app.main` in `test_api.py` / `test_end_to_end.py` never starts a real background thread.

> **Manual/opt-in note for deployers:** to actually run the tracker in production, start the app with `ENABLE_SCHEDULER=true uvicorn app.main:app`. It is off by default everywhere else.

- [ ] **Step 7: Commit**

```bash
git add backend/requirements.txt backend/app/config.py backend/app/scheduler.py backend/app/main.py
git commit -m "feat: add opt-in APScheduler wiring for the outcome tracker"
```

---

## Task 6: Wire Calibration into the Pipeline

**Files:**
- Modify: `backend/app/pipeline.py`
- Test: `backend/tests/test_pipeline.py`

**Interfaces:**
- Consumes: `get_calibrated_magnitude` (Task 3), `resolve_companies` (Plan 1), `Alert`/`AlertCompany`/`Article` models (Task 1).
- Produces: unchanged `process_new_articles(session: Session, claude_client) -> int` signature, but each created `AlertCompany` now carries a `confidence` of `"calibrated"` (with `magnitude_low`/`magnitude_high` overwritten by the blended range) when 5+ samples exist for its `(category, company_id)`, else `"llm_estimate"`. Task 7 (API) and Task 8 (e2e) rely on this.

- [ ] **Step 1: Update the pipeline tests**

Replace the entire contents of `backend/tests/test_pipeline.py` with:

```python
import pytest

import app.pipeline as pipeline_module
from app.analysis.schemas import AnalysisOutput, CompanyMention
from app.models import Alert, AlertCompany, Article, CalibrationSample, Company
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

- [ ] **Step 2: Run tests to verify the two calibration assertions fail**

Run: `cd backend && .venv/Scripts/pytest tests/test_pipeline.py -v`
Expected: FAIL — `test_process_new_articles_creates_alert_end_to_end` fails on `AttributeError`/missing `confidence` behavior is fine, but specifically `test_process_new_articles_uses_calibrated_magnitude_when_enough_samples` fails because the pipeline does not yet consult the blender (confidence would be unset/`llm_estimate` and magnitudes unchanged).

- [ ] **Step 3: Wire calibration into the pipeline**

Replace the entire contents of `backend/app/pipeline.py` with:

```python
from sqlalchemy.orm import Session

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

    return alerts_created
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/pytest tests/test_pipeline.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline.py backend/tests/test_pipeline.py
git commit -m "feat: blend calibrated magnitude into pipeline alert companies"
```

---

## Task 7: Expose Confidence in the API

**Files:**
- Modify: `backend/app/routers/alerts.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `AlertCompany.confidence` (Task 1), `Alert` model (Plan 1).
- Produces: each company dict in `GET /api/alerts` now includes a `"confidence"` key. Task 8 (e2e) asserts this key round-trips.

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
    assert body[0]["article"]["title"] == "Test headline"

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
Expected: FAIL on `test_list_alerts_returns_nested_companies` with `KeyError: 'confidence'` (the response dict does not yet include the key).

- [ ] **Step 3: Add `confidence` to the response**

Replace the entire contents of `backend/app/routers/alerts.py` with:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.models import Alert
from app.routers.articles import get_db

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("")
def list_alerts(db: Session = Depends(get_db)):
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
        } for ac in alert.companies],
    } for alert in alerts]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest tests/test_api.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/alerts.py backend/tests/test_api.py
git commit -m "feat: expose alert-company confidence in the alerts API"
```

---

## Task 8: End-to-End Calibration Integration Test

**Files:**
- Modify: `backend/tests/test_end_to_end.py`

**Interfaces:**
- Consumes: `fetch_new_articles` (Plan 1), `process_new_articles` (Task 6), `CalibrationSample` model (Task 1), API endpoints (Task 7) — exercises RSS → pipeline → calibration → API in one full chain with no internal shortcuts.

- [ ] **Step 1: Add the calibrated full-chain test**

Replace the entire contents of `backend/tests/test_end_to_end.py` with:

```python
from types import SimpleNamespace

import pytest

import app.pipeline as pipeline_module
from app.analysis.schemas import AnalysisOutput, CompanyMention
from app.ingestion.poller import fetch_new_articles
from app.models import CalibrationSample, Company
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
```

- [ ] **Step 2: Run the full test suite**

Run: `cd backend && .venv/Scripts/pytest tests/ -v`
Expected: all tests pass — every test from Plan 1 plus Tasks 1-8 of this plan — with no live network calls (RSS `feedparser.parse`, Claude `analyze_article`, and yfinance `yf.Ticker` are all monkeypatched or unused).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_end_to_end.py
git commit -m "test: add end-to-end calibrated-confidence integration test"
```

---

## Definition of Done (Plan 2)

- `pytest tests/ -v` passes fully with zero live network calls — RSS, Claude, and yfinance are always monkeypatched, and the scheduler never starts during tests (`settings.enable_scheduler` defaults to `False`).
- A human with a real `ANTHROPIC_API_KEY` can run the app (`uvicorn app.main:app`), and once 5+ calibration samples exist for some `(category, company)` pair — accumulated automatically by the opt-in outcome tracker (`ENABLE_SCHEDULER=true`, which fetches real 1d/3d/7d price moves via yfinance and writes `CalibrationSample` rows) — subsequent alerts for that pair show `"confidence": "calibrated"` at `/api/alerts`, with a `magnitude_low`/`magnitude_high` range blended (`mean ± population stdev`) from those real historical outcomes. Pairs below the threshold keep the LLM's own estimate, flagged `"llm_estimate"`.
- The outcome tracker is idempotent (never re-samples the same `(alert_company_id, horizon_days)` twice, enforced by a unique constraint) and resilient (a single ticker's fetch failure returns `None` and is skipped, never blocking the rest of the batch, and a failing scheduled run is logged rather than crashing the scheduler thread).
- This plan deliberately excludes: holdings/auth/email alerts (Plan 3) and the CRED-style React UI + WebSocket live push (Plan 4).
```

