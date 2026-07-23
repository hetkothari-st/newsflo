# Measurement-First Impact Architecture — Phase 8 (CAR Review) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the CAR (Cumulative Abnormal Return) review feature per `docs/NEWS_IMPACT_APP_SPEC.md` §4.6 and the task brief's Phase 8 section — the final phase of the 8-phase rebuild. For every alert whose flagged company has a real measured reaction, compute the sum of (stock return − benchmark return) over trading days −1 through +3 once the market has actually traded that far, and expose a review screen showing whether the reaction *held* or *reversed*. This is the "did the flag turn out to be right" check that back-validates the whole measurement pipeline — a genuinely new capability (§4.6's own "not live — completes days later" framing means this is the one feature in the whole build that necessarily lags real time by up to a week).

**Architecture:** New `app/outcomes/price_fetcher.py` function computes CAR directly from live price history (the same "fetch AND compute in one function" style that file already uses for horizon returns). A new scheduled job — following the exact `app/outcomes/tracker.py`/`app.scheduler` pattern already established for 1/3/7-day outcome sampling — finds AlertCompany rows old enough for the window to have fully traded, computes CAR, and persists one row per (alert, company) to a new `CarOutcome` table. A new router exposes a list endpoint and a threshold-gated aggregate-summary endpoint (mirroring `app.calibration.track_record`'s existing `WIN_RATE_SAMPLE_THRESHOLD` convention). A new frontend page, reachable only by URL (no nav link, per this build's own precedent for internal/discovery-only screens), gated behind the existing `RequireAuth` wrapper — any logged-in user, since this app has no admin/staff tier to reuse and adding one is out of scope for a single internal screen (confirmed with the user).

**Tech Stack:** Same as Phases 1-7 — FastAPI + SQLAlchemy backend, React + TypeScript + Vite + Tailwind frontend, Vitest + Testing Library, Playwright.

## Global Constraints

- **CAR is computed once, never revisited.** Same "one row per (alert, company), unique-constrained, immutable once written" discipline as `MarketMove` — a `CarOutcome` row is created exactly once, when the −1..+3 window has fully traded; there is no re-computation or update path.
- **Never fabricate a number. A CAR value only ever comes from a real fetched price series.** If the market hasn't yet traded far enough past the alert for the full window to exist, the fetch returns `None` and the row is skipped this run, retried next run — the exact "skip, retry on the next scheduled run" contract `app.outcomes.price_fetcher.fetch_price_change_pct` and `app.outcomes.tracker.check_pending_outcomes` already use. An alert that was never measured (`MarketMove.measurement_status != "ok"`) is never eligible for CAR at all — there is no baseline reaction to validate against.
- **CAR reuses the alert's own original `benchmark_ticker`**, not a freshly-resolved one — the whole point is validating the SAME sector-adjustment that produced the original `excess_move_pct`, not a different one computed later.
- **"Held" vs "reversed" is a same-sign comparison between `day0_excess_move_pct` (frozen at CAR-sample time, copied from the alert's own `MarketMove`) and `car_pct`**, with a small dead-zone around zero classified as `"FLAT"` (neither) — threshold in config, not hardcoded, per this codebase's established "weights and thresholds in config" discipline. This is a literal, simple reading of spec §4.6's "held or reversed" — no magnitude-retention refinement, flagged here as the interpretive choice it is.
- **`CarOutcome` intentionally does NOT persist intensity, breadth, or verdict.** Those are correctly derived-on-read elsewhere in this codebase (`app.market.intensity`/`app.market.breadth`/`app.market.verdict`) and recomputing them at CAR-sample time (potentially days or weeks after the alert, against a peer group that has since grown) would NOT reproduce what was actually shown to the user live — storing a mismatched "historical" intensity would be worse than not storing one. `CarOutcome` stores only what changed (the actual outcome) plus enough keys (`alert_company_id`, `company_id`, `category`) to join back to `MarketMove`/`AlertCompany` for any future retuning work, matching `CalibrationSample`'s own existing "copy category at sample time, join back for the rest" convention exactly.
- **This is a genuinely new, unprecedented decision in this codebase**: the app has zero existing admin/staff/internal-tooling concept. Per direct confirmation with the user: the review screen requires being logged in (reuses `RequireAuth`/`get_current_user`, no new permission tier) and is reachable by URL only — no link from `NavBar`/`BottomNav`/`FeedV2`'s own header, unlike Phase 7's Directory link. If a real admin tier is ever needed, that's a separate, later decision — out of scope here.
- **No LLM involvement anywhere in this phase.** Every number in a `CarOutcome` row is arithmetic on fetched close prices — CAR review is the spine validating itself, not a place the LLM cascade touches at all.
- Full backend and frontend test suites must both pass with zero regressions at the end. This phase has a UI component, so the HARD RULE applies: Playwright screenshots, actually looked at, before this phase is done.

---

## File Structure

```
backend/app/models.py                           MODIFY — add CarOutcome
backend/app/config.py                           MODIFY — add CAR_FLAT_THRESHOLD_PCT, CAR_SUMMARY_SAMPLE_THRESHOLD
backend/app/outcomes/price_fetcher.py           MODIFY — add fetch_cumulative_excess_return
backend/app/outcomes/car.py                     NEW — compute_car_outcome_label, check_pending_car_outcomes
backend/app/scheduler.py                        MODIFY — register the CAR job
backend/app/routers/car_review.py               NEW — GET /api/car-review, GET /api/car-review/summary
backend/app/main.py                             MODIFY — register car_review.router
backend/seed_car_review_demo.py                 NEW — deterministic demo CarOutcome rows

backend/tests/test_price_fetcher.py             MODIFY — cover fetch_cumulative_excess_return
backend/tests/test_car.py                       NEW — compute_car_outcome_label, check_pending_car_outcomes
backend/tests/test_car_review_router.py         NEW
backend/tests/test_scheduler.py                 MODIFY (if it exists — check first) — cover the new job registration

frontend/src/lib/carReviewApi.ts                NEW — CarReviewRow, CarReviewSummary types, getCarReview, getCarReviewSummary
frontend/src/pages/CarReviewPage.tsx            NEW
frontend/src/pages/CarReviewPage.test.tsx        NEW
frontend/src/App.tsx                            MODIFY — register the RequireAuth-wrapped route

frontend/e2e/car-review-screenshots.spec.ts     NEW
```

---

## Task 1: `CarOutcome` model + config thresholds

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/config.py`

**Interfaces:**
- Produces: `CarOutcome` model (columns below). `config.CAR_FLAT_THRESHOLD_PCT: float`, `config.CAR_SUMMARY_SAMPLE_THRESHOLD: int`.

- [ ] **Step 1: Add the config constants**

In `backend/app/config.py`, add near the other product/algorithm constants (alongside `INTENSITY_WEIGHTS_LIVE`/`VERDICT_EXCESS_THRESHOLD_PCT` — same "tuned via CAR back-validation, not a per-deployment secret" comment block):

```python
# CAR (Cumulative Abnormal Return, spec §4.6) review thresholds.
CAR_FLAT_THRESHOLD_PCT = 0.5  # |car_pct| below this counts as FLAT (neither held nor reversed)
CAR_SUMMARY_SAMPLE_THRESHOLD = 5  # matches calibration/track_record.py's WIN_RATE_SAMPLE_THRESHOLD convention
```

- [ ] **Step 2: Add the model**

In `backend/app/models.py`, add after `CalibrationSample`:

```python
class CarOutcome(Base):
    """Cumulative Abnormal Return outcome (docs/NEWS_IMPACT_APP_SPEC.md
    §4.6) -- one row per (alert, company), written exactly once by
    app.outcomes.car.check_pending_car_outcomes once trading days -1..+3
    around the alert have fully traded. Never updated afterward, same
    immutable-snapshot discipline as MarketMove. day0_excess_move_pct is
    copied from that alert/company's own MarketMove.excess_move_pct at
    sample time (the original flagged reaction); car_pct is the actual
    Sum(ticker return - benchmark return) over the window (app.outcomes.
    price_fetcher.fetch_cumulative_excess_return). category is copied
    from Alert.category at sample time, same reclassification-safety
    reason CalibrationSample already documents for its own category
    column."""
    __tablename__ = "car_outcomes"
    __table_args__ = (UniqueConstraint("alert_company_id", name="uq_car_outcome_alert_company"),)

    id = Column(Integer, primary_key=True)
    alert_company_id = Column(Integer, ForeignKey("alert_companies.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    category = Column(String, nullable=False)
    day0_excess_move_pct = Column(Float, nullable=False)
    car_pct = Column(Float, nullable=False)
    computed_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
```

- [ ] **Step 3: Verify the table is created**

Run: `cd backend && python -c "from app.db import init_db; init_db(); print('ok')"`
Expected: prints `ok` with no error — `Base.metadata.create_all` picks up the new table automatically (this codebase's `_ADDED_COLUMNS` mechanism in `app/db.py` is only for adding columns to already-existing tables against an older DB file; a brand-new table needs no entry there).

- [ ] **Step 4: Commit**

```bash
git add backend/app/models.py backend/app/config.py
git commit -m "feat: add CarOutcome model + CAR config thresholds"
```

---

## Task 2: `fetch_cumulative_excess_return` — the CAR computation

**Files:**
- Modify: `backend/app/outcomes/price_fetcher.py`
- Modify: `backend/tests/test_price_fetcher.py` (read the current file first for its existing `yf.Ticker` mocking pattern — follow it exactly)

**Interfaces:**
- Produces: `fetch_cumulative_excess_return(ticker: str, benchmark_ticker: str, event_date: datetime, days_before: int = 1, days_after: int = 3) -> float | None`. Consumed by `app/outcomes/car.py` (Task 3).

- [ ] **Step 1: Write the failing tests**

Read `backend/tests/test_price_fetcher.py` in full first to copy its exact `monkeypatch.setattr` mocking convention for `yf.Ticker` (it must return an object whose `.history(start=, end=)` returns a pandas DataFrame with a `DatetimeIndex` and a `Close` column — mirror whatever fixture-building helper that file already uses, if any, rather than inventing a new one).

Append (adapting the exact mock style already in that file):

```python
import pandas as pd
from datetime import datetime, timezone

from app.outcomes.price_fetcher import fetch_cumulative_excess_return


def _history_df(dates, closes):
    return pd.DataFrame({"Close": closes}, index=pd.DatetimeIndex(dates))


def test_fetch_cumulative_excess_return_sums_daily_excess_over_window(monkeypatch):
    # 6 trading days needed for a -1..+3 window (5 daily returns): day-2
    # through day+3. Event date = day 0 = 2026-01-08.
    dates = ["2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09", "2026-01-12", "2026-01-13"]
    ticker_closes = [100.0, 101.0, 103.0, 104.03, 106.11, 107.17]  # +1%, +2%, +1%, +2%, +1%
    benchmark_closes = [200.0, 202.0, 204.02, 204.02, 204.02, 206.06]  # +1%, +1%, 0%, 0%, +1%

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, start=None, end=None):
            if self.symbol == "STOCK.NS":
                return _history_df(dates, ticker_closes)
            return _history_df(dates, benchmark_closes)

    monkeypatch.setattr("app.outcomes.price_fetcher.yf.Ticker", FakeTicker)

    result = fetch_cumulative_excess_return(
        "STOCK.NS", "^BENCH", datetime(2026, 1, 8, tzinfo=timezone.utc),
    )

    # daily excess = ticker_return - benchmark_return for days -1,0,+1,+2,+3:
    # day-1: 1% - 1% = 0%% ; day0: ~1.98% - ~1% = ~0.98%% ; day+1: 1% - 0% = 1%%
    # day+2: ~2% - 0% = ~2%% ; day+3: ~1% - 1% = 0%%
    assert result is not None
    assert round(result, 1) == round(0.0 + 0.9803 + 1.0 + 1.9993 + 0.0, 1)


def test_fetch_cumulative_excess_return_returns_none_when_window_not_fully_traded_yet(monkeypatch):
    # Only 4 trading days available -- day+2 and day+3 haven't happened yet.
    dates = ["2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09"]
    closes = [100.0, 101.0, 103.0, 104.0]

    class FakeTicker:
        def __init__(self, symbol):
            pass

        def history(self, start=None, end=None):
            return _history_df(dates, closes)

    monkeypatch.setattr("app.outcomes.price_fetcher.yf.Ticker", FakeTicker)

    result = fetch_cumulative_excess_return(
        "STOCK.NS", "^BENCH", datetime(2026, 1, 8, tzinfo=timezone.utc),
    )

    assert result is None


def test_fetch_cumulative_excess_return_returns_none_when_no_data(monkeypatch):
    class FakeTicker:
        def __init__(self, symbol):
            pass

        def history(self, start=None, end=None):
            return pd.DataFrame({"Close": []})

    monkeypatch.setattr("app.outcomes.price_fetcher.yf.Ticker", FakeTicker)

    result = fetch_cumulative_excess_return(
        "STOCK.NS", "^BENCH", datetime(2026, 1, 8, tzinfo=timezone.utc),
    )

    assert result is None


def test_fetch_cumulative_excess_return_returns_none_on_exception(monkeypatch):
    class FakeTicker:
        def __init__(self, symbol):
            raise RuntimeError("network error")

    monkeypatch.setattr("app.outcomes.price_fetcher.yf.Ticker", FakeTicker)

    result = fetch_cumulative_excess_return(
        "STOCK.NS", "^BENCH", datetime(2026, 1, 8, tzinfo=timezone.utc),
    )

    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_price_fetcher.py -v -k cumulative_excess`
Expected: FAIL — `ImportError: cannot import name 'fetch_cumulative_excess_return'`.

- [ ] **Step 3: Implement**

Add to the top of `backend/app/outcomes/price_fetcher.py` (alongside its existing imports — read the file first to see exactly what's already imported and merge rather than duplicate):

```python
import math
from datetime import timedelta

import pandas as pd
```

Then append:

```python
def fetch_cumulative_excess_return(
    ticker: str, benchmark_ticker: str, event_date: datetime,
    days_before: int = 1, days_after: int = 3,
) -> float | None:
    """Cumulative Abnormal Return (docs/NEWS_IMPACT_APP_SPEC.md §4.6): the
    sum of (ticker daily return - benchmark daily return) over trading
    days [event_date - days_before .. event_date + days_after] (default
    -1..+3, 5 trading days -- 6 closes needed since each daily return
    requires the prior day's close too). Returns a percentage (matching
    MarketMove.excess_move_pct's own convention: 1.5 means 1.5%, not
    0.015). Returns None -- "not ready yet, retry on the next scheduled
    run" -- if the market hasn't yet traded far enough past event_date
    to fill the whole window, or if data is unavailable/the fetch fails.
    Same "never raise, degrade to None" contract as
    fetch_price_change_pct in this same module.
    """
    try:
        start = event_date - timedelta(days=14)
        end = event_date + timedelta(days=14)

        ticker_closes = yf.Ticker(ticker).history(start=start.date(), end=end.date())["Close"]
        if len(ticker_closes) == 0:
            return None

        event_ts = pd.Timestamp(event_date.date())
        on_or_after = ticker_closes.index[ticker_closes.index >= event_ts]
        if len(on_or_after) == 0:
            return None
        day0_pos = ticker_closes.index.get_loc(on_or_after[0])

        first_pos = day0_pos - days_before - 1
        last_pos = day0_pos + days_after
        if first_pos < 0 or last_pos >= len(ticker_closes):
            return None

        window_dates = ticker_closes.index[first_pos:last_pos + 1]
        window_ticker_closes = ticker_closes.iloc[first_pos:last_pos + 1]

        benchmark_closes = yf.Ticker(benchmark_ticker).history(start=start.date(), end=end.date())["Close"]
        benchmark_by_date = {
            ts.date(): float(v) for ts, v in benchmark_closes.items() if math.isfinite(float(v))
        }

        cumulative_excess = 0.0
        for i in range(1, len(window_dates)):
            prev_close = float(window_ticker_closes.iloc[i - 1])
            curr_close = float(window_ticker_closes.iloc[i])
            if prev_close == 0 or not math.isfinite(prev_close) or not math.isfinite(curr_close):
                return None
            ticker_return = curr_close / prev_close - 1

            prev_date = window_dates[i - 1].date()
            curr_date = window_dates[i].date()
            if prev_date not in benchmark_by_date or curr_date not in benchmark_by_date:
                return None
            benchmark_prev = benchmark_by_date[prev_date]
            benchmark_curr = benchmark_by_date[curr_date]
            if benchmark_prev == 0:
                return None
            benchmark_return = benchmark_curr / benchmark_prev - 1

            cumulative_excess += (ticker_return - benchmark_return) * 100

        return cumulative_excess
    except Exception:
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_price_fetcher.py -v`
Expected: all PASS (existing tests plus the 4 new ones).

- [ ] **Step 5: Commit**

```bash
git add backend/app/outcomes/price_fetcher.py backend/tests/test_price_fetcher.py
git commit -m "feat: add fetch_cumulative_excess_return -- CAR over trading days -1..+3"
```

---

## Task 3: `compute_car_outcome_label` + `check_pending_car_outcomes`

**Files:**
- Create: `backend/app/outcomes/car.py`
- Create: `backend/tests/test_car.py`

**Interfaces:**
- Consumes: `fetch_cumulative_excess_return` (Task 2), `config.CAR_FLAT_THRESHOLD_PCT` (Task 1), `CarOutcome`/`Alert`/`AlertCompany`/`MarketMove` (Task 1 + existing).
- Produces: `compute_car_outcome_label(day0_excess_move_pct: float, car_pct: float) -> str` (returns `"HELD"|"REVERSED"|"FLAT"`). `check_pending_car_outcomes(session, fetch_fn=fetch_cumulative_excess_return) -> int`. Consumed by `app/scheduler.py` (Task 4) and `app/routers/car_review.py` (Task 5).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_car.py`:

```python
from datetime import timedelta

from app.models import Alert, AlertCompany, Article, Company, MarketMove, CarOutcome, utcnow
from app.outcomes.car import check_pending_car_outcomes, compute_car_outcome_label


def test_compute_car_outcome_label_held_when_same_sign():
    assert compute_car_outcome_label(day0_excess_move_pct=-4.2, car_pct=-3.0) == "HELD"
    assert compute_car_outcome_label(day0_excess_move_pct=2.1, car_pct=1.5) == "HELD"


def test_compute_car_outcome_label_reversed_when_opposite_sign():
    assert compute_car_outcome_label(day0_excess_move_pct=-4.2, car_pct=3.0) == "REVERSED"
    assert compute_car_outcome_label(day0_excess_move_pct=2.1, car_pct=-1.5) == "REVERSED"


def test_compute_car_outcome_label_flat_when_near_zero():
    assert compute_car_outcome_label(day0_excess_move_pct=-4.2, car_pct=0.1) == "FLAT"
    assert compute_car_outcome_label(day0_excess_move_pct=2.1, car_pct=-0.2) == "FLAT"


def _company(ticker):
    return Company(ticker=ticker, name=f"Company {ticker}", sector="oil_gas", index_tier="NIFTY50")


def _article(db_session, url):
    article = Article(source="test", url=url, title="t", content="c")
    db_session.add(article)
    db_session.commit()
    return article


def _alert_company(alert_id, company_id):
    return AlertCompany(
        alert_id=alert_id, company_id=company_id, direction="bearish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
    )


def test_check_pending_car_outcomes_creates_a_row_when_fetch_succeeds(db_session):
    company = _company("A.NS")
    db_session.add(company)
    db_session.commit()
    article = _article(db_session, "https://example.com/car1")
    old_created_at = utcnow() - timedelta(days=10)
    alert = Alert(article_id=article.id, category="oil_gas", created_at=old_created_at)
    db_session.add(alert)
    db_session.flush()
    ac = _alert_company(alert.id, company.id)
    db_session.add(ac)
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.8, sector_move_pct=-0.6, excess_move_pct=-4.2,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    created = check_pending_car_outcomes(db_session, fetch_fn=lambda *a, **k: -3.5)

    assert created == 1
    row = db_session.query(CarOutcome).one()
    assert row.company_id == company.id
    assert row.category == "oil_gas"
    assert row.day0_excess_move_pct == -4.2
    assert row.car_pct == -3.5


def test_check_pending_car_outcomes_skips_when_fetch_returns_none(db_session):
    company = _company("A.NS")
    db_session.add(company)
    db_session.commit()
    article = _article(db_session, "https://example.com/car2")
    alert = Alert(article_id=article.id, category="oil_gas", created_at=utcnow() - timedelta(days=10))
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, company.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.8, sector_move_pct=-0.6, excess_move_pct=-4.2,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    created = check_pending_car_outcomes(db_session, fetch_fn=lambda *a, **k: None)

    assert created == 0
    assert db_session.query(CarOutcome).count() == 0


def test_check_pending_car_outcomes_skips_unmeasured_alert_companies(db_session):
    company = _company("A.NS")
    db_session.add(company)
    db_session.commit()
    article = _article(db_session, "https://example.com/car3")
    alert = Alert(article_id=article.id, category="oil_gas", created_at=utcnow() - timedelta(days=10))
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, company.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        measurement_status="no_data", measured_at=utcnow(),
    ))
    db_session.commit()

    created = check_pending_car_outcomes(db_session, fetch_fn=lambda *a, **k: -3.5)

    assert created == 0


def test_check_pending_car_outcomes_skips_alerts_too_recent(db_session):
    company = _company("A.NS")
    db_session.add(company)
    db_session.commit()
    article = _article(db_session, "https://example.com/car4")
    alert = Alert(article_id=article.id, category="oil_gas", created_at=utcnow())
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, company.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.8, sector_move_pct=-0.6, excess_move_pct=-4.2,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    created = check_pending_car_outcomes(db_session, fetch_fn=lambda *a, **k: -3.5)

    assert created == 0


def test_check_pending_car_outcomes_does_not_recreate_existing_row(db_session):
    company = _company("A.NS")
    db_session.add(company)
    db_session.commit()
    article = _article(db_session, "https://example.com/car5")
    alert = Alert(article_id=article.id, category="oil_gas", created_at=utcnow() - timedelta(days=10))
    db_session.add(alert)
    db_session.flush()
    ac = _alert_company(alert.id, company.id)
    db_session.add(ac)
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.8, sector_move_pct=-0.6, excess_move_pct=-4.2,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.flush()
    db_session.add(CarOutcome(
        alert_company_id=ac.id, company_id=company.id, category="oil_gas",
        day0_excess_move_pct=-4.2, car_pct=-3.0,
    ))
    db_session.commit()

    created = check_pending_car_outcomes(db_session, fetch_fn=lambda *a, **k: -9.9)

    assert created == 0
    assert db_session.query(CarOutcome).count() == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_car.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.outcomes.car'`.

- [ ] **Step 3: Implement**

Create `backend/app/outcomes/car.py`:

```python
"""CAR (Cumulative Abnormal Return) review, spec §4.6: back-validates a
flagged reaction by summing (ticker - benchmark) daily returns over
trading days -1..+3 once the market has actually traded that far. "Not
live -- it completes days later" (spec) -- this module's job is entirely
scheduled/batch, never called on a live request path.
"""
from datetime import timedelta

from sqlalchemy.orm import Session

from app import config
from app.models import Alert, AlertCompany, CarOutcome, MarketMove, utcnow
from app.outcomes.price_fetcher import fetch_cumulative_excess_return

# Generous buffer: a -1..+3 trading-day window is well within a week even
# across a long weekend/holiday cluster. An alert younger than this cannot
# possibly have a fully-traded window yet, so it's cheaper to skip it at
# the query level than to call the fetch function and get a None back.
_MIN_ALERT_AGE_DAYS = 7


def compute_car_outcome_label(day0_excess_move_pct: float, car_pct: float) -> str:
    """"Held" vs "reversed" (spec §4.6): a same-sign comparison between the
    original flagged reaction and the actual outcome, with a dead zone
    around zero (config.CAR_FLAT_THRESHOLD_PCT) classified as neither."""
    if abs(car_pct) < config.CAR_FLAT_THRESHOLD_PCT:
        return "FLAT"
    same_sign = (day0_excess_move_pct >= 0) == (car_pct >= 0)
    return "HELD" if same_sign else "REVERSED"


def check_pending_car_outcomes(
    session: Session, fetch_fn=fetch_cumulative_excess_return,
) -> int:
    """For every AlertCompany with a real measured MarketMove
    (measurement_status='ok') whose Alert is at least _MIN_ALERT_AGE_DAYS
    old and has no CarOutcome yet, compute CAR and record it. A None
    fetch result (market hasn't traded that far yet, or data unavailable)
    is skipped -- retried next run, never blocks the rest of the batch
    (same contract as app.outcomes.tracker.check_pending_outcomes).
    Returns the number of rows created.
    """
    cutoff = utcnow() - timedelta(days=_MIN_ALERT_AGE_DAYS)
    already_sampled_ids = session.query(CarOutcome.alert_company_id)

    pending = (
        session.query(AlertCompany, MarketMove)
        .join(Alert, AlertCompany.alert_id == Alert.id)
        .join(
            MarketMove,
            (MarketMove.alert_id == AlertCompany.alert_id) & (MarketMove.company_id == AlertCompany.company_id),
        )
        .filter(Alert.created_at <= cutoff)
        .filter(MarketMove.measurement_status == "ok")
        .filter(~AlertCompany.id.in_(already_sampled_ids))
        .all()
    )

    created = 0
    for alert_company, move in pending:
        car_pct = fetch_fn(alert_company.company.ticker, move.benchmark_ticker, alert_company.alert.created_at)
        if car_pct is None:
            continue
        session.add(CarOutcome(
            alert_company_id=alert_company.id,
            company_id=alert_company.company_id,
            category=alert_company.alert.category,
            day0_excess_move_pct=move.excess_move_pct,
            car_pct=car_pct,
        ))
        session.commit()
        created += 1
    return created
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_car.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full backend suite to confirm no regressions**

Run: `cd backend && python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/outcomes/car.py backend/tests/test_car.py
git commit -m "feat: add compute_car_outcome_label + check_pending_car_outcomes"
```

---

## Task 4: Wire the CAR job into the scheduler

**Files:**
- Modify: `backend/app/scheduler.py`

**Interfaces:**
- Consumes: `check_pending_car_outcomes` (Task 3).

- [ ] **Step 1: Implement**

In `backend/app/scheduler.py`, add the import (alongside the existing `from app.outcomes.tracker import check_pending_outcomes` line):

```python
from app.outcomes.car import check_pending_car_outcomes
```

Add, directly after the existing `_run_horizon` function:

```python
def _run_car_review() -> None:
    """Open a fresh session, run the CAR outcome check, and always close
    the session. Any error is logged, never raised, so one failing run
    does not crash the scheduler thread -- same contract as
    _run_horizon."""
    session = SessionLocal()
    try:
        created = check_pending_car_outcomes(session)
        logger.info("CAR review cycle: %s outcomes recorded", created)
    except Exception:
        logger.exception("CAR review run failed")
    finally:
        session.close()
```

In `start_scheduler()`, add directly after the `for horizon in HORIZONS:` loop's `scheduler.add_job(...)` block:

```python
    scheduler.add_job(
        _run_car_review,
        trigger="interval",
        minutes=60,
        id="car_review",
    )
```

- [ ] **Step 2: Check for an existing scheduler test file**

Run: `cd backend && ls tests/ | grep -i schedul`

If `test_scheduler.py` exists, read it and add a test confirming `car_review` appears among the registered job IDs after `start_scheduler()` (following whichever pattern that file already uses to assert job registration — likely inspecting `scheduler.get_jobs()` or a similar APScheduler introspection call already used there for the existing jobs). If no such test file exists, skip this step (this codebase apparently doesn't unit-test scheduler wiring directly elsewhere either, and the underlying `check_pending_car_outcomes` function is already fully tested in Task 3) — do not invent a new testing pattern for scheduler registration that the rest of the file doesn't already use.

- [ ] **Step 3: Run the full backend suite to confirm no regressions**

Run: `cd backend && python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/app/scheduler.py
git commit -m "feat: register the CAR review job in the scheduler"
```

---

## Task 5: `GET /api/car-review` + `GET /api/car-review/summary`

**Files:**
- Create: `backend/app/routers/car_review.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_car_review_router.py`

**Interfaces:**
- Consumes: `compute_car_outcome_label` (Task 3), `get_current_user` (existing, `app.auth.dependencies` — the REQUIRED, non-optional dependency, since this endpoint needs any-logged-in-user gating, not the `_optional` variant `feed_v2.py`/`stock_deep_dive.py` use).
- Produces: `GET /api/car-review` (list, auth required) and `GET /api/car-review/summary` (aggregate, auth required, threshold-gated).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_car_review_router.py`:

```python
from datetime import timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.models import Alert, AlertCompany, Article, CarOutcome, Company, User, utcnow
from app.routers.articles import get_db
from app.auth.tokens import create_access_token


def _override_db(db_session):
    def _get_db():
        yield db_session
    app.dependency_overrides[get_db] = _get_db


def _auth_headers(db_session):
    user = User(email="reviewer@example.com", hashed_password="x")
    db_session.add(user)
    db_session.commit()
    token = create_access_token(user.id)
    return {"Authorization": f"Bearer {token}"}


def _seed_outcome(db_session, ticker, category, day0_excess, car_pct, url_suffix):
    company = Company(ticker=ticker, name=f"Company {ticker}", sector=category, index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()
    article = Article(source="test", url=f"https://example.com/{url_suffix}", title=f"{ticker} news", content="c")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category=category, created_at=utcnow() - timedelta(days=10))
    db_session.add(alert)
    db_session.flush()
    ac = AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bearish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
    )
    db_session.add(ac)
    db_session.flush()
    db_session.add(CarOutcome(
        alert_company_id=ac.id, company_id=company.id, category=category,
        day0_excess_move_pct=day0_excess, car_pct=car_pct,
    ))
    db_session.commit()
    return alert, company


def test_car_review_requires_auth(db_session):
    _override_db(db_session)
    client = TestClient(app)

    response = client.get("/api/car-review")

    assert response.status_code == 401
    app.dependency_overrides.clear()


def test_car_review_lists_outcomes_with_derived_label(db_session):
    _override_db(db_session)
    headers = _auth_headers(db_session)
    _seed_outcome(db_session, "A.NS", "oil_gas", day0_excess=-4.2, car_pct=-3.0, url_suffix="a")
    client = TestClient(app)

    response = client.get("/api/car-review", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["ticker"] == "A.NS"
    assert body[0]["day0_excess_move_pct"] == -4.2
    assert body[0]["car_pct"] == -3.0
    assert body[0]["outcome_label"] == "HELD"
    app.dependency_overrides.clear()


def test_car_review_summary_requires_auth(db_session):
    _override_db(db_session)
    client = TestClient(app)

    response = client.get("/api/car-review/summary")

    assert response.status_code == 401
    app.dependency_overrides.clear()


def test_car_review_summary_is_none_below_threshold(db_session):
    _override_db(db_session)
    headers = _auth_headers(db_session)
    _seed_outcome(db_session, "A.NS", "oil_gas", day0_excess=-4.2, car_pct=-3.0, url_suffix="a")
    client = TestClient(app)

    response = client.get("/api/car-review/summary", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["sample_count"] == 1
    assert body["hold_rate"] is None
    assert body["mean_car_pct"] is None
    app.dependency_overrides.clear()


def test_car_review_summary_populated_at_threshold(db_session):
    _override_db(db_session)
    headers = _auth_headers(db_session)
    for i in range(5):
        _seed_outcome(db_session, f"A{i}.NS", "oil_gas", day0_excess=-4.2, car_pct=-3.0, url_suffix=f"a{i}")
    client = TestClient(app)

    response = client.get("/api/car-review/summary", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["sample_count"] == 5
    assert body["hold_rate"] == 1.0
    assert body["mean_car_pct"] == -3.0
    assert len(body["by_category"]) == 1
    assert body["by_category"][0]["category"] == "oil_gas"
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_car_review_router.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.routers.car_review'`.

- [ ] **Step 3: Implement**

Create `backend/app/routers/car_review.py`:

```python
"""CAR (Cumulative Abnormal Return) review endpoints (docs/
NEWS_IMPACT_APP_SPEC.md §4.6) -- an internal, any-logged-in-user tool
(this app has no admin/staff tier; adding one is out of scope for a
single internal screen, confirmed at plan time). Shows whether flagged
reactions held or reversed once the market has actually traded far
enough past each alert -- the data this build's whole measurement spine
gets back-validated against.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import config
from app.auth.dependencies import get_current_user
from app.models import Alert, AlertCompany, CarOutcome, User
from app.outcomes.car import compute_car_outcome_label
from app.routers.articles import get_db

router = APIRouter(prefix="/api/car-review", tags=["car-review"])

OUTCOMES_LIMIT = 200


def _serialize(outcome: CarOutcome, alert_company: AlertCompany) -> dict:
    company = alert_company.company
    alert = alert_company.alert
    return {
        "id": outcome.id,
        "ticker": company.ticker,
        "company_name": company.name,
        "category": outcome.category,
        "article_title": alert.article.title,
        "article_url": alert.article.url,
        "alert_created_at": alert.created_at.isoformat(),
        "day0_excess_move_pct": outcome.day0_excess_move_pct,
        "car_pct": outcome.car_pct,
        "outcome_label": compute_car_outcome_label(outcome.day0_excess_move_pct, outcome.car_pct),
    }


@router.get("")
def list_car_review(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(CarOutcome, AlertCompany)
        .join(AlertCompany, CarOutcome.alert_company_id == AlertCompany.id)
        .join(Alert, AlertCompany.alert_id == Alert.id)
        .order_by(Alert.created_at.desc())
        .limit(OUTCOMES_LIMIT)
        .all()
    )
    return [_serialize(outcome, alert_company) for outcome, alert_company in rows]


@router.get("/summary")
def get_car_review_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    outcomes = db.query(CarOutcome).all()
    sample_count = len(outcomes)

    if sample_count < config.CAR_SUMMARY_SAMPLE_THRESHOLD:
        return {"sample_count": sample_count, "hold_rate": None, "mean_car_pct": None, "by_category": []}

    held_count = sum(
        1 for o in outcomes if compute_car_outcome_label(o.day0_excess_move_pct, o.car_pct) == "HELD"
    )
    hold_rate = held_count / sample_count
    mean_car_pct = sum(o.car_pct for o in outcomes) / sample_count

    by_category_outcomes: dict[str, list[CarOutcome]] = {}
    for o in outcomes:
        by_category_outcomes.setdefault(o.category, []).append(o)

    by_category = []
    for category, cat_outcomes in sorted(by_category_outcomes.items()):
        cat_count = len(cat_outcomes)
        if cat_count < config.CAR_SUMMARY_SAMPLE_THRESHOLD:
            by_category.append({"category": category, "sample_count": cat_count, "hold_rate": None, "mean_car_pct": None})
            continue
        cat_held = sum(
            1 for o in cat_outcomes if compute_car_outcome_label(o.day0_excess_move_pct, o.car_pct) == "HELD"
        )
        by_category.append({
            "category": category,
            "sample_count": cat_count,
            "hold_rate": cat_held / cat_count,
            "mean_car_pct": sum(o.car_pct for o in cat_outcomes) / cat_count,
        })

    return {
        "sample_count": sample_count,
        "hold_rate": hold_rate,
        "mean_car_pct": mean_car_pct,
        "by_category": by_category,
    }
```

- [ ] **Step 4: Register the router**

In `backend/app/main.py`, add `car_review` to the router import list (alongside the existing `stock_deep_dive` entry — check the exact current ordering first, this codebase's convention is alphabetical within the import tuple per Phase 7's own registration) and add:

```python
app.include_router(car_review.router)
```

directly after the existing `app.include_router(stock_deep_dive.router)` line (or wherever the import list's alphabetical position places it — read the current file to match exactly). No route-collision risk here: `car_review`'s prefix is `/api/car-review`, distinct from every other router's prefix in the app, so registration order doesn't matter the way it did for `stock_deep_dive`/`feed_v2` in Phase 7 — but keep it grouped with the other feed-v2-era routers for readability.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_car_review_router.py -v`
Expected: all PASS. (If `create_access_token`/`app.auth.tokens` isn't the exact existing helper name, grep the codebase for however other test files already create a valid bearer token for an authenticated `TestClient` request — e.g. `backend/tests/test_holdings*.py` almost certainly already does this for its own `RequireAuth`-equivalent backend routes — and match that exact import/call rather than guessing.)

- [ ] **Step 6: Run the full backend suite to confirm no regressions**

Run: `cd backend && python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/car_review.py backend/app/main.py backend/tests/test_car_review_router.py
git commit -m "feat: add GET /api/car-review and /api/car-review/summary"
```

---

## Task 6: Demo seed script for CAR review

**Files:**
- Create: `backend/seed_car_review_demo.py`

**Context:** CAR data only exists once real trading days have passed — there's no way to produce it live in a fresh dev DB the way `seed_feed_v2_demo.py` produces same-day alert data. This script inserts fully-formed demo rows directly (no LLM calls, no live market fetch), covering all three outcome labels (HELD, REVERSED, FLAT) plus enough total rows (≥`CAR_SUMMARY_SAMPLE_THRESHOLD`) to unlock the aggregate summary for screenshot verification.

- [ ] **Step 1: Implement**

Create `backend/seed_car_review_demo.py`:

```python
"""Deterministic demo data for locally viewing/screenshotting the CAR
review screen (docs/superpowers/plans/2026-07-23-measurement-first-
impact-phase8-car-review.md) -- inserts Alert/Article/Company/
AlertCompany/MarketMove/CarOutcome rows directly (no LLM calls, no live
market data -- CAR data only exists once real trading days have passed,
so there's no way to produce it live in a fresh dev DB). Covers all
three outcome labels (HELD, REVERSED, FLAT) and enough total rows to
unlock the aggregate summary (config.CAR_SUMMARY_SAMPLE_THRESHOLD).

Safe to re-run: clears its own previously-seeded rows (identified by a
fixed marker prefix on Article.url) before re-inserting.

Usage (from the backend/ directory, so `app` is importable):
    .venv/Scripts/python seed_car_review_demo.py
"""
import sys
from datetime import timedelta

from app.config import settings
from app.db import SessionLocal, init_db
from app.models import Alert, AlertCompany, Article, CarOutcome, Company, MarketMove, utcnow

URL_MARKER = "https://demo.car-review.local/"

# (ticker, name, category, benchmark, day0_excess, car_pct, headline)
DEMO_ROWS = [
    ("RELIANCE.NS", "Reliance Industries", "oil_gas", "^CNXENERGY", -4.2, -3.6, "Crude oil supply shock hits refiners"),
    ("TCS.NS", "Tata Consultancy Services", "it", "^CNXIT", 2.8, 3.4, "Large IT deal win announced"),
    ("HDFCBANK.NS", "HDFC Bank", "banking", "^NSEBANK", -3.1, 2.9, "Regulatory concern flagged, later cleared"),
    ("SUNPHARMA.NS", "Sun Pharmaceutical", "pharma", "^CNXPHARMA", 3.5, 0.2, "Drug approval news, muted follow-through"),
    ("TATASTEEL.NS", "Tata Steel", "metals", "^CNXMETAL", -2.6, -2.2, "Tariff announcement hits metal stocks"),
    ("MARUTI.NS", "Maruti Suzuki", "auto", "^CNXAUTO", 4.0, 3.1, "Strong monthly sales numbers"),
]


def main() -> None:
    if not settings.database_url.startswith("sqlite://"):
        print(
            f"ERROR: seed_car_review_demo.py refuses to run against a non-SQLite database.\n"
            f"DATABASE_URL is: {settings.database_url}\n"
            f"This safety guard exists because running this script against production\n"
            f"would inject demo CAR outcomes alongside real ones.\n"
            f"Only run this script against local SQLite dev databases.",
            file=sys.stderr,
        )
        sys.exit(1)

    init_db()
    session = SessionLocal()
    try:
        existing = session.query(Article).filter(Article.url.like(f"{URL_MARKER}%")).all()
        for article in existing:
            for alert in session.query(Alert).filter_by(article_id=article.id).all():
                for ac in session.query(AlertCompany).filter_by(alert_id=alert.id).all():
                    session.query(CarOutcome).filter_by(alert_company_id=ac.id).delete()
                session.query(MarketMove).filter_by(alert_id=alert.id).delete()
                session.query(AlertCompany).filter_by(alert_id=alert.id).delete()
                session.delete(alert)
            session.delete(article)
        session.commit()

        now = utcnow()
        for i, row in enumerate(DEMO_ROWS):
            ticker, name, category, benchmark, day0_excess, car_pct, headline = row

            company = session.query(Company).filter_by(ticker=ticker).one_or_none()
            if company is None:
                company = Company(ticker=ticker, name=name, sector=category, index_tier="NIFTY50", market_cap=50000.0)
                session.add(company)
                session.commit()

            article = Article(
                source="demo", url=f"{URL_MARKER}{i}", title=headline, content=headline,
                published_at=now - timedelta(days=10 + i),
            )
            session.add(article)
            session.commit()

            alert = Alert(
                article_id=article.id, category=category, created_at=now - timedelta(days=10 + i),
                summary_short=headline,
            )
            session.add(alert)
            session.flush()

            alert_company = AlertCompany(
                alert_id=alert.id, company_id=company.id, direction="bullish" if day0_excess >= 0 else "bearish",
                magnitude_low=1.0, magnitude_high=2.0, rationale=headline, basis="direct_mention",
            )
            session.add(alert_company)
            session.flush()

            session.add(MarketMove(
                alert_id=alert.id, company_id=company.id, benchmark_ticker=benchmark,
                raw_move_pct=day0_excess, sector_move_pct=0.0, excess_move_pct=day0_excess,
                volume=100.0, avg_volume_20d=100.0, volume_multiple=1.0,
                measurement_status="ok", measured_at=now - timedelta(days=10 + i),
            ))

            session.add(CarOutcome(
                alert_company_id=alert_company.id, company_id=company.id, category=category,
                day0_excess_move_pct=day0_excess, car_pct=car_pct,
            ))
            session.commit()

        print(f"Seeded {len(DEMO_ROWS)} demo CAR outcomes.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it against the local dev DB**

Run: `cd backend && python seed_car_review_demo.py`
Expected: prints `Seeded 6 demo CAR outcomes.` with no error.

- [ ] **Step 3: Spot-check via the API**

Start a background `uvicorn` (check port availability first, per the established pattern), obtain a bearer token (register/login a test user via the existing auth endpoints), then:
`curl -H "Authorization: Bearer <token>" http://127.0.0.1:8000/api/car-review` — confirm 6 rows with the expected `outcome_label`s (RELIANCE.NS: HELD, TCS.NS: HELD, HDFCBANK.NS: REVERSED, SUNPHARMA.NS: FLAT, TATASTEEL.NS: HELD, MARUTI.NS: HELD).
`curl -H "Authorization: Bearer <token>" http://127.0.0.1:8000/api/car-review/summary` — confirm `sample_count: 6`, `hold_rate` and `mean_car_pct` populated (not null, since 6 ≥ threshold of 5), `by_category` has 6 single-sample-count categories each with `hold_rate: null` (since each category individually only has 1 sample, below its own per-category threshold).
Stop the background server by its specific PID afterward.

- [ ] **Step 4: Commit**

```bash
git add backend/seed_car_review_demo.py
git commit -m "feat: add demo seed script for CAR review screen verification"
```

---

## Task 7: Frontend types + API client

**Files:**
- Create: `frontend/src/lib/carReviewApi.ts`

**Interfaces:**
- Produces: `CarOutcomeLabel` type, `CarReviewRow` interface, `CarReviewCategorySummary` interface, `CarReviewSummary` interface, `getCarReview(token)`, `getCarReviewSummary(token)`.

- [ ] **Step 1: Implement**

Read `frontend/src/lib/feedV2Api.ts` first to copy its exact `authHeaders`/`parseError` helper pattern (do not re-derive a different convention).

Create `frontend/src/lib/carReviewApi.ts`:

```ts
export type CarOutcomeLabel = 'HELD' | 'REVERSED' | 'FLAT';

export interface CarReviewRow {
  id: number;
  ticker: string;
  company_name: string;
  category: string;
  article_title: string;
  article_url: string;
  alert_created_at: string;
  day0_excess_move_pct: number;
  car_pct: number;
  outcome_label: CarOutcomeLabel;
}

export interface CarReviewCategorySummary {
  category: string;
  sample_count: number;
  hold_rate: number | null;
  mean_car_pct: number | null;
}

export interface CarReviewSummary {
  sample_count: number;
  hold_rate: number | null;
  mean_car_pct: number | null;
  by_category: CarReviewCategorySummary[];
}

function authHeaders(token: string | null): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

interface ApiError {
  detail?: string;
}

async function parseError(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as ApiError;
    if (typeof body.detail === 'string') return body.detail;
    return `Request failed (${res.status})`;
  } catch {
    return `Request failed (${res.status})`;
  }
}

export async function getCarReview(token: string | null): Promise<CarReviewRow[]> {
  const res = await fetch('/api/car-review', { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as CarReviewRow[];
}

export async function getCarReviewSummary(token: string | null): Promise<CarReviewSummary> {
  const res = await fetch('/api/car-review/summary', { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as CarReviewSummary;
}
```

- [ ] **Step 2: Verify the frontend builds cleanly**

Run: `cd frontend && npm run build`
Expected: succeeds — `tsc --noEmit` passes.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/carReviewApi.ts
git commit -m "feat: add CarReview API client types and fetch functions"
```

---

## Task 8: `CarReviewPage`

**Files:**
- Create: `frontend/src/pages/CarReviewPage.tsx`
- Create: `frontend/src/pages/CarReviewPage.test.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `getCarReview`/`getCarReviewSummary` (Task 7), `useAuth` (existing).
- Produces: `<CarReviewPage />`, mounted at `/car-review`, wrapped in the existing `RequireAuth`.

**Layout:** aggregate summary tile (sample count, hold rate, mean CAR — only when the backend returns non-null values, i.e. threshold met) at top, then a row per outcome: ticker + company name + category, day0 excess vs CAR side by side, an outcome-label pill (HELD green / REVERSED red / FLAT muted — reuse the existing `bullish`/`bearish`/`muted` color tokens, not new ones, since this is a plain 3-state label, not a direction or intensity signal needing its own hue family), linking out to the original article.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/pages/CarReviewPage.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import CarReviewPage from './CarReviewPage';
import * as carReviewApi from '../lib/carReviewApi';
import type { CarReviewRow, CarReviewSummary } from '../lib/carReviewApi';
import { AuthProvider } from '../lib/auth';

function makeRow(overrides: Partial<CarReviewRow> = {}): CarReviewRow {
  return {
    id: 1,
    ticker: 'RELIANCE.NS',
    company_name: 'Reliance Industries',
    category: 'oil_gas',
    article_title: 'Crude oil supply shock hits refiners',
    article_url: 'https://example.com/article',
    alert_created_at: '2026-07-10T09:00:00Z',
    day0_excess_move_pct: -4.2,
    car_pct: -3.6,
    outcome_label: 'HELD',
    ...overrides,
  };
}

function makeSummary(overrides: Partial<CarReviewSummary> = {}): CarReviewSummary {
  return {
    sample_count: 6,
    hold_rate: 0.83,
    mean_car_pct: -0.4,
    by_category: [{ category: 'oil_gas', sample_count: 6, hold_rate: 0.83, mean_car_pct: -0.4 }],
    ...overrides,
  };
}

function renderPage() {
  return render(
    <AuthProvider>
      <MemoryRouter>
        <CarReviewPage />
      </MemoryRouter>
    </AuthProvider>,
  );
}

describe('CarReviewPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders a row per outcome with its label', async () => {
    vi.spyOn(carReviewApi, 'getCarReview').mockResolvedValue([makeRow()]);
    vi.spyOn(carReviewApi, 'getCarReviewSummary').mockResolvedValue(makeSummary({ sample_count: 1, hold_rate: null, mean_car_pct: null, by_category: [] }));
    renderPage();

    await waitFor(() => expect(screen.getByText('Reliance Industries')).toBeInTheDocument());
    expect(screen.getByText('HELD')).toBeInTheDocument();
    expect(screen.getByText(/4\.2/)).toBeInTheDocument();
    expect(screen.getByText(/3\.6/)).toBeInTheDocument();
  });

  it('renders REVERSED and FLAT labels distinctly', async () => {
    vi.spyOn(carReviewApi, 'getCarReview').mockResolvedValue([
      makeRow({ id: 1, ticker: 'A.NS', outcome_label: 'REVERSED' }),
      makeRow({ id: 2, ticker: 'B.NS', outcome_label: 'FLAT' }),
    ]);
    vi.spyOn(carReviewApi, 'getCarReviewSummary').mockResolvedValue(makeSummary({ sample_count: 2, hold_rate: null, mean_car_pct: null, by_category: [] }));
    renderPage();

    await waitFor(() => expect(screen.getByText('REVERSED')).toBeInTheDocument());
    expect(screen.getByText('FLAT')).toBeInTheDocument();
  });

  it('shows the aggregate summary once the threshold is met', async () => {
    vi.spyOn(carReviewApi, 'getCarReview').mockResolvedValue([makeRow()]);
    vi.spyOn(carReviewApi, 'getCarReviewSummary').mockResolvedValue(makeSummary());
    renderPage();

    await waitFor(() => expect(screen.getByText(/83/)).toBeInTheDocument());
  });

  it('omits the aggregate summary below the threshold', async () => {
    vi.spyOn(carReviewApi, 'getCarReview').mockResolvedValue([makeRow()]);
    vi.spyOn(carReviewApi, 'getCarReviewSummary').mockResolvedValue(
      makeSummary({ sample_count: 1, hold_rate: null, mean_car_pct: null, by_category: [] }),
    );
    renderPage();

    await waitFor(() => expect(screen.getByText('Reliance Industries')).toBeInTheDocument());
    expect(screen.queryByText('Hold rate')).not.toBeInTheDocument();
  });

  it('links each row to its original article', async () => {
    vi.spyOn(carReviewApi, 'getCarReview').mockResolvedValue([makeRow()]);
    vi.spyOn(carReviewApi, 'getCarReviewSummary').mockResolvedValue(makeSummary({ sample_count: 1, hold_rate: null, mean_car_pct: null, by_category: [] }));
    renderPage();

    await waitFor(() => expect(screen.getByText('Reliance Industries')).toBeInTheDocument());
    const link = screen.getByRole('link', { name: /Crude oil supply shock hits refiners/ });
    expect(link).toHaveAttribute('href', 'https://example.com/article');
  });

  it('renders an empty state when there are no outcomes yet', async () => {
    vi.spyOn(carReviewApi, 'getCarReview').mockResolvedValue([]);
    vi.spyOn(carReviewApi, 'getCarReviewSummary').mockResolvedValue(
      makeSummary({ sample_count: 0, hold_rate: null, mean_car_pct: null, by_category: [] }),
    );
    renderPage();

    await waitFor(() => expect(screen.getByText(/no outcomes yet/i)).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/CarReviewPage.test.tsx`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement**

Create `frontend/src/pages/CarReviewPage.tsx`:

```tsx
import { useEffect, useState } from 'react';
import {
  getCarReview, getCarReviewSummary,
  type CarOutcomeLabel, type CarReviewRow, type CarReviewSummary,
} from '../lib/carReviewApi';
import { useAuth } from '../lib/auth';

function labelColorClass(label: CarOutcomeLabel): string {
  if (label === 'HELD') return 'text-bullish';
  if (label === 'REVERSED') return 'text-bearish';
  return 'text-muted';
}

export default function CarReviewPage() {
  const { token } = useAuth();
  const [rows, setRows] = useState<CarReviewRow[] | null>(null);
  const [summary, setSummary] = useState<CarReviewSummary | null>(null);

  useEffect(() => {
    let active = true;
    getCarReview(token)
      .then((data) => {
        if (active) setRows(data);
      })
      .catch(() => {
        if (active) setRows([]);
      });
    getCarReviewSummary(token)
      .then((data) => {
        if (active) setSummary(data);
      })
      .catch(() => {
        if (active) setSummary(null);
      });
    return () => {
      active = false;
    };
  }, [token]);

  if (rows === null) return null;

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-3 px-4 py-8">
      {summary && summary.hold_rate !== null && summary.mean_car_pct !== null && (
        <div className="rounded-lg bg-surface p-5">
          <div className="grid grid-cols-3 gap-4">
            <div>
              <div className="font-sans text-[11px] uppercase tracking-widest text-muted">Sample count</div>
              <div className="font-data text-lg text-ink">{summary.sample_count}</div>
            </div>
            <div>
              <div className="font-sans text-[11px] uppercase tracking-widest text-muted">Hold rate</div>
              <div className="font-data text-lg text-ink">{Math.round(summary.hold_rate * 100)}%</div>
            </div>
            <div>
              <div className="font-sans text-[11px] uppercase tracking-widest text-muted">Mean CAR</div>
              <div className="font-data text-lg text-ink">{summary.mean_car_pct.toFixed(1)}%</div>
            </div>
          </div>
        </div>
      )}

      <div className="rounded-lg bg-surface p-5">
        {rows.length === 0 ? (
          <p className="font-sans text-sm text-muted">No outcomes yet.</p>
        ) : (
          <div className="flex flex-col divide-y divide-hairline">
            {rows.map((row) => (
              <div key={row.id} className="flex flex-col gap-1 py-3">
                <div className="flex items-center gap-2">
                  <span className="font-sans text-sm text-ink">{row.company_name}</span>
                  <span className="font-data text-[11px] text-muted">{row.ticker}</span>
                  <span className="font-sans text-xs uppercase tracking-widest text-muted">{row.category}</span>
                  <span className={`ml-auto font-sans text-xs uppercase tracking-widest ${labelColorClass(row.outcome_label)}`}>
                    {row.outcome_label}
                  </span>
                </div>
                <a
                  href={row.article_url}
                  target="_blank"
                  rel="noreferrer"
                  className="font-sans text-sm text-ink underline"
                >
                  {row.article_title}
                </a>
                <div className="flex gap-6 font-data text-xs text-muted">
                  <span>Day 0: {row.day0_excess_move_pct.toFixed(1)}%</span>
                  <span>CAR (-1..+3d): {row.car_pct.toFixed(1)}%</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
```

- [ ] **Step 4: Wire the route**

Read the current `frontend/src/App.tsx` (Phase 7 left it with `RequireAuth`-wrapped `/holdings`/`/account` routes as the existing pattern). Add the import `import CarReviewPage from './pages/CarReviewPage';` and add, alongside the existing `RequireAuth`-wrapped routes:

```tsx
        <Route
          path="/car-review"
          element={
            <RequireAuth>
              <CarReviewPage />
            </RequireAuth>
          }
        />
```

No nav link anywhere — per this phase's Global Constraints, reachable by URL only.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/CarReviewPage.test.tsx`
Expected: all PASS.

- [ ] **Step 6: Run the full frontend suite to confirm no regressions**

Run: `cd frontend && npm test -- --run`
Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/CarReviewPage.tsx frontend/src/pages/CarReviewPage.test.tsx frontend/src/App.tsx
git commit -m "feat: add CarReviewPage -- CAR outcomes list + aggregate summary, URL-only, RequireAuth-gated"
```

---

## Task 9: Backend full regression + demo spot-check

**Files:**
- No new files — verification task.

- [ ] **Step 1: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 2: Confirm the scheduler starts cleanly with the new job**

Run: `cd backend && python -c "from app.scheduler import start_scheduler; start_scheduler(); print('scheduler started ok')"` (this will hang since the scheduler runs in a background thread and the script has nothing else to do — run it with a short timeout, e.g. via a 5-second background process check, and confirm it prints the success line before being killed, rather than raising at import/registration time). Kill the process afterward.

- [ ] **Step 3: Report any discrepancy found**

If anything doesn't match, fix it in the relevant Task 1-5 file before proceeding, then re-run the full backend suite.

---

## Task 10: Playwright screenshot verification (HARD RULE)

**Files:**
- Create: `frontend/e2e/car-review-screenshots.spec.ts`

**Context:** This phase ships one new screen (`CarReviewPage`), reachable directly by URL (no click-path from anywhere else in the app, unlike every prior phase's screenshot spec which navigates via UI interaction) — the spec can `page.goto('/car-review')` directly after logging in. Given this session's own recent, hard-won experience in Phase 6 (modal `position:fixed` content silently truncated by `fullPage`) and Phase 7 (a race condition producing a blank screenshot, a wrong-page navigation, and a `BottomNav` overlap) — every one of those was found only by a human actually looking at the rendered output, never by "tests passed" — treat this task with the same suspicion: capture, then genuinely inspect each image before calling it done.

- [ ] **Step 1: Write the screenshot spec**

Create `frontend/e2e/car-review-screenshots.spec.ts`:

```ts
import { test } from '@playwright/test';

const THEMES = ['dark', 'light'] as const;

test.describe.configure({ mode: 'serial' });

async function login(page: import('@playwright/test').Page) {
  // Reuse whichever demo/test login flow the rest of this e2e suite (if
  // any) already relies on -- check frontend/e2e/ for an existing
  // register-or-login helper before writing a new one here. If none
  // exists, register a throwaway user via the UI's own /register form
  // (do not call the API directly -- this spec verifies the real login
  // flow works too, consistent with how every other screenshot in this
  // suite exercises real UI interaction, not shortcuts).
  //
  // Verified directly against frontend/src/components/RegisterForm.tsx
  // and frontend/src/lib/i18n.ts's English strings: the email/password
  // <label> elements wrap their <input> (implicit label association, so
  // getByLabel still works), and the submit button's English text is
  // "Create account" (auth.createAccount), NOT "Register" -- match that
  // exact text, not a /register/i guess. RegisterForm's onSuccess navigates
  // to "/" (the legacy feed) on success, per RegisterPage.tsx.
  await page.goto('/register');
  const email = `car-review-${Date.now()}@example.com`;
  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel(/password/i).fill('demo-password-123');
  await page.getByRole('button', { name: 'Create account' }).click();
  await page.waitForURL((url) => !url.pathname.includes('/register'), { timeout: 10_000 });
}

for (const theme of THEMES) {
  test(`car review page (${theme})`, async ({ page }) => {
    await login(page);
    await page.goto('/car-review');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    await page.waitForSelector('text=/./', { timeout: 10_000 }).catch(() => {});
    await page.screenshot({
      path: `.superpowers-screenshots/car-review-${theme}-${test.info().project.name}.png`,
      fullPage: true,
    });
  });
}
```

The `login()` helper above was verified against the actual `RegisterForm.tsx`/`i18n.ts` source at plan-writing time (not a guess) — still check `frontend/e2e/` first for any existing register-or-login helper this spec should reuse instead of duplicating, and re-verify the button text/labels haven't changed since if this task runs long after the plan was written.

- [ ] **Step 2: Seed data and start both servers**

Run the demo seed script (`python seed_car_review_demo.py`), start backend + frontend (check port availability, use alternates + temporary config repointing if needed, reverting before any commit — follow the exact process established in Phases 4-7).

- [ ] **Step 3: Run the screenshot spec**

Run: `cd frontend && npx playwright test car-review-screenshots`
Expected: 4 screenshots (2 themes × 2 viewports) generated successfully.

- [ ] **Step 4: Look at every screenshot — THE ACTUAL VERIFICATION STEP**

Open each of the 4 files with the Read tool and check:
- The aggregate summary tile shows Sample count 6, a real hold-rate percentage, a real mean-CAR percentage (not blank, not "null", not a stale/wrong page).
- All 6 demo rows render: company name, ticker, category, HELD/REVERSED/FLAT label (color-differentiated — HELD green-ish via the `bullish` token, REVERSED red-ish via `bearish`, FLAT muted), the linked article headline, and both the day-0 excess and CAR percentages.
- On mobile: given this session's own Phase 7 finding that a fixed `BottomNav` can overlap content in a `fullPage` screenshot on any sufficiently tall plain page, check specifically whether this page is tall enough to trigger that same artifact — if so, apply the exact same fix already established in `frontend/e2e/feed-v2-screenshots.spec.ts` (hide `nav.fixed` before screenshotting) rather than re-diagnosing it from scratch.
- Both themes legible, no clipped/overlapping text, HELD/REVERSED/FLAT colors clearly distinguishable from each other and from the page background in both themes.
- Confirm this is genuinely the CAR review page and not some other page (an empty/blank capture, or a redirect-to-login page if the login helper silently failed, are both real failure modes to rule out explicitly, given this exact class of bug already bit Phase 7 twice).

Write down every concrete discrepancy found. Fix it. Re-run Step 3 and re-check. Repeat until clean.

- [ ] **Step 5: Stop the background servers**

Kill the specific PIDs — never a broad process-kill.

- [ ] **Step 6: Run both full test suites one more time**

Run: `cd backend && python -m pytest -q` and `cd frontend && npm test -- --run` — confirm zero regressions from any Step 4 fixes.

- [ ] **Step 7: Commit**

Commit the e2e spec, and separately any fixes Step 4's review required, describing exactly what was found and corrected (or "clean on first pass").

---

## Task 11: Full-suite regression check

- [ ] **Step 1: Run the entire backend test suite**

Run: `cd backend && python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 2: Run the entire frontend test suite**

Run: `cd frontend && npm test -- --run`
Expected: all tests PASS.

- [ ] **Step 3: Commit (only if Steps 1-2 required a fix)**

If clean, nothing to commit here.

---

## PHASE 8 STOP — required report

Report:
1. Full-suite pass/fail status, both backend and frontend.
2. All 4 CAR review screenshots' final state — confirm each was actually opened and looked at, list every concrete difference found during Task 10's review and how it was fixed (or "clean on first pass").
3. **Flag for confirmation:** the "any logged-in user, URL-only, no nav link" access model — this was confirmed once at plan time, but flag it again now that the screen actually exists, in case seeing it live changes the answer (e.g. "actually this needs to stay fully private" or "add a link after all").
4. Confirm CAR review never fabricates: re-check that an alert whose window hasn't fully traded yet simply doesn't appear in the list (rather than appearing with a null/zero CAR) — this can be verified against the real (non-demo) data in whatever dev DB has accumulated actual alerts from the live scheduler, if any exist old enough to matter, or by direct code inspection of `check_pending_car_outcomes`'s skip-on-None path if not.
5. **This is the last phase of the original 8-phase task brief.** Once this STOP report is reviewed and accepted, the full `NEWS_IMPACT_APP_SPEC.md` implementation (Phases 1-8) is complete. Summarize, at a high level, what was built across all 8 phases and any known gaps or deliberately-deferred items (e.g., the Advisory/Premium tier, Account Aggregator integration, RIA onboarding — all explicitly out of scope per the original task brief's phase list, milestones 7-9 of the spec) for whoever picks this up next.
