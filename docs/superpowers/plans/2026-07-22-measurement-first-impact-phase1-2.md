# Measurement-First Impact Architecture — Phase 1+2 (Market Data Foundation + Derived Metrics) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic, LLM-free measurement spine — real price/volume/sector-index data per (alert, company), and pure functions that turn it into `excess_move_pct`, `volume_multiple`, `intensity`, `breadth_score`, `verdict`, and `cap_tier` — exactly as specified in `docs/NEWS_IMPACT_APP_SPEC.md` §3–§4 and the task brief at `C:\Users\ST269\Downloads\CLAUDE_TASK_measurement_first_impact.md` Phases 1–2.

**Architecture:** Measurement is the spine; the LLM cascade is repurposed for explanation only (Phase 3, a separate plan) and never produces a number a user sees. This plan is entirely backend, additive-only (new table, new `app/market/` package, one new pipeline hook), and ships with zero UI change — nothing in this plan is rendered yet. Phases 3 (LLM refinement) and 4–8 (UI, CAR) are separate follow-on plans, executed and visually verified one at a time per the task brief's per-phase STOP gates.

**Tech Stack:** FastAPI + SQLAlchemy (no Alembic — manual `_ADDED_COLUMNS`/`create_all` in `app/db.py`), SQLite (dev) / Postgres (prod), `yfinance` for market data, `pytest` (see `backend/pytest.ini`, `backend/tests/conftest.py`).

## Global Constraints

- **Never delete existing code.** If any step in this plan would require removing or replacing an existing line, comment it out with a note instead (per explicit user instruction for this whole task) — do not delete. In practice this plan only ever *adds* files/functions/columns, so this should not come up, but it overrides default editing behavior for the whole task.
- Every user-facing number must trace to a `MarketMove` row or a config-weighted pure function of one (spec Definition of Done #1). No LLM call exists anywhere in this plan.
- Missing data → `measurement_status='no_data'`, never a fabricated number, never zero-as-if-measured (spec Ground Rules).
- `excess_move_pct = raw_move_pct - sector_move_pct` (simple tier — spec §4.1). Do not build the beta-adjusted tier; leave a signature-compatible seam.
- `volume_multiple = day_volume / trailing_20d_avg_volume` (spec §4.2).
- Live-feed intensity weights: `0.55*excess + 0.25*volume + 0.20*breadth` (spec §4.2), **in config, not hardcoded**.
- Intensity bands: `>=75 High`, `50-74 Moderate`, `<50 Low` (spec §4.2), **in config**.
- Intensity sub-scores normalize **within sector or event, never globally** (spec §4.2).
- `cap_tier` is recomputed from live market cap ranked against AMFI-style boundaries (top 100 = LARGE, 101–250 = MID, rest = SMALL) — **never hardcoded, never stored as fixed truth** (spec §3.2, §4.5).
- `intensity` is likewise **derived, never persisted as truth** (spec §3.2) — Phase 2 ships pure functions only, not new persisted columns.
- Don't delete the cascade, rulebook, confidence engine, or `ImpactEdge` — this plan doesn't touch them at all.
- Don't weaken or delete existing tests to make something pass.
- New DB table → add the SQLAlchemy model class only; `Base.metadata.create_all` (already called by `init_db()`/test fixtures) creates it automatically. **Do not** add an `_ADDED_COLUMNS` entry for it — that list is only for new *columns* on pre-existing tables.

---

## File Structure

```
backend/app/market/                  NEW package — pure measurement + derived-metric functions
  __init__.py                        empty
  sector_indices.py                  SECTOR_INDEX_MAP, benchmark_ticker_for_sector, is_fallback_benchmark
  measure.py                         measure_company_move() — the only place that calls yfinance for this feature
  intensity.py                       normalize_score(), compute_intensity()
  breadth.py                         compute_breadth_score()
  verdict.py                         compute_verdict()
  cap_tier.py                        compute_cap_tiers(), compute_cap_tier_for_ticker()

backend/app/companies/price_series.py   MODIFY — add fetch_daily_bars() alongside existing fetch_price_series()
backend/app/models.py                   MODIFY — add MarketMove
backend/app/config.py                   MODIFY — add intensity/verdict/AMFI constants below the Settings block
backend/app/pipeline.py                 MODIFY — _persist_alert() gains a MarketMove-recording loop
backend/tests/conftest.py               MODIFY — add autouse stub for the new market-move fetch (network-free tests)
backend/verify_sector_indices.py        NEW — standalone script (same pattern as backend/seed_nifty_indices.py), real yfinance check of every mapped ticker

backend/tests/test_price_series.py      MODIFY — append fetch_daily_bars tests
backend/tests/test_sector_indices.py    NEW
backend/tests/test_measure.py           NEW
backend/tests/test_intensity.py         NEW
backend/tests/test_breadth.py           NEW
backend/tests/test_verdict.py           NEW
backend/tests/test_cap_tier.py          NEW
backend/tests/test_market_move_wiring.py  NEW — pipeline-level: _persist_alert writes MarketMove rows
```

---

## PHASE 1 — Market data foundation (spec §3, §5)

### Task 1: `fetch_daily_bars` — volume-carrying sibling of `fetch_price_series`

**Files:**
- Modify: `backend/app/companies/price_series.py`
- Test: `backend/tests/test_price_series.py`

**Interfaces:**
- Produces: `fetch_daily_bars(ticker: str, period: str) -> list[dict] | None`, each dict `{"date": str, "close": float, "volume": float}`, oldest-first, or `None`. Consumed by `app.market.measure.measure_company_move` (Task 4).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_price_series.py` (same `FakeTicker` pattern already in the file, extended to carry a `Volume` column):

```python
class FakeTickerWithVolume:
    def __init__(self, df):
        self._df = df

    def history(self, period, interval):
        return self._df


def test_fetch_daily_bars_returns_date_close_volume_points(monkeypatch):
    df = pd.DataFrame(
        {"Close": [100.0, 105.0], "Volume": [1000.0, 2000.0]},
        index=pd.to_datetime(["2026-01-01", "2026-01-02"]),
    )
    monkeypatch.setattr(price_series.yf, "Ticker", lambda ticker: FakeTickerWithVolume(df))

    result = price_series.fetch_daily_bars("RELIANCE.NS", period="2mo")

    assert result == [
        {"date": "2026-01-01", "close": 100.0, "volume": 1000.0},
        {"date": "2026-01-02", "close": 105.0, "volume": 2000.0},
    ]


def test_fetch_daily_bars_drops_nan_close_days(monkeypatch):
    df = pd.DataFrame(
        {"Close": [100.0, float("nan")], "Volume": [1000.0, 2000.0]},
        index=pd.to_datetime(["2026-01-01", "2026-01-02"]),
    )
    monkeypatch.setattr(price_series.yf, "Ticker", lambda ticker: FakeTickerWithVolume(df))

    result = price_series.fetch_daily_bars("RELIANCE.NS", period="2mo")

    assert result == [{"date": "2026-01-01", "close": 100.0, "volume": 1000.0}]


def test_fetch_daily_bars_treats_nan_volume_as_zero_not_a_dropped_day(monkeypatch):
    # A close price with no reliable volume that day must still be usable
    # for excess-move math -- only a bad CLOSE should drop the day.
    df = pd.DataFrame(
        {"Close": [100.0, 105.0], "Volume": [1000.0, float("nan")]},
        index=pd.to_datetime(["2026-01-01", "2026-01-02"]),
    )
    monkeypatch.setattr(price_series.yf, "Ticker", lambda ticker: FakeTickerWithVolume(df))

    result = price_series.fetch_daily_bars("RELIANCE.NS", period="2mo")

    assert result == [
        {"date": "2026-01-01", "close": 100.0, "volume": 1000.0},
        {"date": "2026-01-02", "close": 105.0, "volume": 0.0},
    ]


def test_fetch_daily_bars_returns_none_for_empty(monkeypatch):
    df = pd.DataFrame({"Close": [], "Volume": []})
    monkeypatch.setattr(price_series.yf, "Ticker", lambda ticker: FakeTickerWithVolume(df))

    assert price_series.fetch_daily_bars("RELIANCE.NS", period="2mo") is None


def test_fetch_daily_bars_returns_none_on_exception(monkeypatch):
    def boom(ticker):
        raise RuntimeError("network down")

    monkeypatch.setattr(price_series.yf, "Ticker", boom)

    assert price_series.fetch_daily_bars("RELIANCE.NS", period="2mo") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_price_series.py -v`
Expected: the 5 new tests FAIL with `AttributeError: module 'app.companies.price_series' has no attribute 'fetch_daily_bars'`.

- [ ] **Step 3: Implement `fetch_daily_bars`**

Append to `backend/app/companies/price_series.py` (existing `fetch_price_series` stays exactly as-is above it):

```python
def fetch_daily_bars(ticker: str, period: str) -> list[dict] | None:
    """Return daily close+volume bars for ``ticker`` over ``period`` as
    ``[{"date": "YYYY-MM-DD", "close": float, "volume": float}, ...]``,
    oldest first, or ``None`` if data is unavailable or the fetch fails.

    Volume-carrying sibling of ``fetch_price_series`` -- built for
    app.market.measure's excess-move/volume-multiple calculations (see
    docs/NEWS_IMPACT_APP_SPEC.md §3, §5). Same "never raise, degrade to
    None" contract. Only a non-finite CLOSE drops a day (matching
    fetch_price_series); a non-finite/absent volume on an otherwise-good
    day is recorded as 0.0 rather than dropping the close price the
    excess-move math needs.
    """
    try:
        history = yf.Ticker(ticker).history(period=period, interval="1d")
        close = history["Close"]
        if len(close) == 0:
            return None
        volume = history["Volume"] if "Volume" in history else None
        points = []
        for index, close_value in close.items():
            if not math.isfinite(float(close_value)):
                continue
            vol_value = 0.0
            if volume is not None:
                raw_vol = volume.get(index)
                if raw_vol is not None and math.isfinite(float(raw_vol)):
                    vol_value = float(raw_vol)
            points.append({
                "date": index.strftime("%Y-%m-%d"),
                "close": float(close_value),
                "volume": vol_value,
            })
        return points or None
    except Exception:
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_price_series.py -v`
Expected: all tests (old + new) PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/companies/price_series.py backend/tests/test_price_series.py
git commit -m "feat: add fetch_daily_bars (volume-carrying price series) for market measurement"
```

---

### Task 2: Sector-index benchmark mapping

**Files:**
- Create: `backend/app/market/__init__.py`
- Create: `backend/app/market/sector_indices.py`
- Create: `backend/verify_sector_indices.py`
- Test: `backend/tests/test_sector_indices.py`

**Interfaces:**
- Consumes: `app.analysis.schemas.SECTORS` (the 18-value list).
- Produces: `benchmark_ticker_for_sector(sector: str) -> str`, `is_fallback_benchmark(sector: str) -> bool`, `SECTOR_INDEX_MAP: dict[str, str]`, `NIFTY50_TICKER: str`. Consumed by `app.market.measure.measure_company_move` (Task 4).

- [ ] **Step 1: Create the empty package init**

`backend/app/market/__init__.py`:

```python
```

(empty file — just makes `app/market` a package)

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_sector_indices.py`:

```python
from app.analysis.schemas import SECTORS
from app.market import sector_indices


def test_every_sector_has_a_benchmark_mapping():
    for sector in SECTORS:
        assert sector_indices.benchmark_ticker_for_sector(sector)


def test_map_covers_exactly_the_18_sectors():
    assert set(sector_indices.SECTOR_INDEX_MAP.keys()) == set(SECTORS)


def test_banking_maps_to_nifty_bank():
    assert sector_indices.benchmark_ticker_for_sector("banking") == "^NSEBANK"
    assert sector_indices.is_fallback_benchmark("banking") is False


def test_sectors_with_no_clean_index_fall_back_to_nifty_50():
    for sector in ("defense", "textiles", "agriculture", "other"):
        assert sector_indices.benchmark_ticker_for_sector(sector) == sector_indices.NIFTY50_TICKER
        assert sector_indices.is_fallback_benchmark(sector) is True


def test_unrecognized_sector_falls_back_to_nifty_50():
    assert sector_indices.benchmark_ticker_for_sector("not_a_real_sector") == sector_indices.NIFTY50_TICKER
    assert sector_indices.is_fallback_benchmark("not_a_real_sector") is True
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_sector_indices.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.market.sector_indices'`.

- [ ] **Step 4: Implement the mapping**

Create `backend/app/market/sector_indices.py`:

```python
"""Maps each of app.analysis.schemas.SECTORS (18 values) to the NSE sector
index used as its excess-move benchmark (docs/NEWS_IMPACT_APP_SPEC.md §3,
§5). Sectors with no clean NSE sectoral index available on Yahoo Finance
fall back to the Nifty 50 (^NSEI) -- FALLBACK_SECTORS records exactly which
ones, so the UI can say "vs Nifty 50" instead of implying a sector index
that doesn't exist.

Every ticker in this map must be verified against a real yfinance call
before being trusted in production -- see backend/verify_sector_indices.py.
"""

NIFTY50_TICKER = "^NSEI"

SECTOR_INDEX_MAP: dict[str, str] = {
    "banking": "^NSEBANK",
    "it": "^CNXIT",
    "auto": "^CNXAUTO",
    "pharma": "^CNXPHARMA",
    "metals": "^CNXMETAL",
    "fmcg": "^CNXFMCG",
    "infra": "^CNXINFRA",
    "oil_gas": "^CNXENERGY",
    # No dedicated NSE transport/logistics index on Yahoo Finance -- infra
    # (EPC/industrials/utilities) is the closest sectoral proxy available.
    "railways_transport": "^CNXINFRA",
    "construction_realestate": "^CNXREALTY",
    "media_entertainment": "^CNXMEDIA",
    # No clean NSE sectoral index for these on Yahoo Finance -- Nifty 50 is
    # the fallback benchmark. Keep this list in sync with FALLBACK_SECTORS.
    "telecom": NIFTY50_TICKER,
    "defense": NIFTY50_TICKER,
    "agriculture": NIFTY50_TICKER,
    "consumer_durables": NIFTY50_TICKER,
    "chemicals": NIFTY50_TICKER,
    "textiles": NIFTY50_TICKER,
    "other": NIFTY50_TICKER,
}

# Sectors whose SECTOR_INDEX_MAP value is the Nifty 50 fallback rather than a
# real sector index -- must exactly match the sectors mapped to
# NIFTY50_TICKER above.
FALLBACK_SECTORS = frozenset({
    "telecom", "defense", "agriculture", "consumer_durables", "chemicals", "textiles", "other",
})


def benchmark_ticker_for_sector(sector: str) -> str:
    """The sector-index ticker to use as this sector's excess-move
    benchmark, or Nifty 50 if the sector has no clean NSE sectoral index
    (including any sector value not present in SECTOR_INDEX_MAP at all --
    never guess, fall back to the market)."""
    return SECTOR_INDEX_MAP.get(sector, NIFTY50_TICKER)


def is_fallback_benchmark(sector: str) -> bool:
    """True when benchmark_ticker_for_sector(sector) is the Nifty 50
    fallback rather than a real sector index -- lets the UI say "vs Nifty
    50" instead of implying a sector index exists."""
    return sector in FALLBACK_SECTORS or sector not in SECTOR_INDEX_MAP
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_sector_indices.py -v`
Expected: all PASS.

- [ ] **Step 6: Write the real-network verification script**

Create `backend/verify_sector_indices.py` (standalone script, same pattern as `backend/seed_nifty_indices.py` — run manually, not part of the pytest suite since it makes real network calls):

```python
"""Standalone verification: confirm every ticker in
app.market.sector_indices.SECTOR_INDEX_MAP actually returns data from
yfinance. Run manually (real network call, not part of the pytest suite):

    cd backend && python verify_sector_indices.py

Per the Phase 1 task brief: "Verify each ticker actually returns data from
yfinance before committing the map; report any that don't."
"""
import yfinance as yf

from app.market.sector_indices import SECTOR_INDEX_MAP


def main() -> None:
    unique_tickers = sorted(set(SECTOR_INDEX_MAP.values()))
    failures = []
    for ticker in unique_tickers:
        try:
            history = yf.Ticker(ticker).history(period="5d", interval="1d")
            ok = len(history) > 0
        except Exception as exc:  # noqa: BLE001 -- report, don't crash the script
            ok = False
            print(f"{ticker}: EXCEPTION {exc}")
            failures.append(ticker)
            continue
        print(f"{ticker}: {'OK (' + str(len(history)) + ' rows)' if ok else 'NO DATA'}")
        if not ok:
            failures.append(ticker)

    print()
    if failures:
        print(f"FAILED tickers ({len(failures)}): {failures}")
    else:
        print("All sector-index tickers returned data.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Run the verification script and record the result**

Run: `cd backend && python verify_sector_indices.py`

This makes a real network call. Record the output verbatim in the phase report (Task 2's STOP report, below) — how many of the 9 real sector-index tickers returned data vs. failed. If any real (non-Nifty-50) ticker fails, move that sector into `FALLBACK_SECTORS`/`SECTOR_INDEX_MAP` pointing at `NIFTY50_TICKER` and re-run this script and `test_sector_indices.py` before continuing.

- [ ] **Step 8: Commit**

```bash
git add backend/app/market/__init__.py backend/app/market/sector_indices.py backend/verify_sector_indices.py backend/tests/test_sector_indices.py
git commit -m "feat: map SECTORS to NSE sector-index benchmarks with Nifty 50 fallback"
```

---

### Task 3: `MarketMove` model

**Files:**
- Modify: `backend/app/models.py`

**Interfaces:**
- Produces: `MarketMove` SQLAlchemy model — columns `id, alert_id, company_id, raw_move_pct, sector_move_pct, benchmark_ticker, excess_move_pct, volume, avg_volume_20d, volume_multiple, measured_at, measurement_status`. Consumed by `app.market.measure.measure_company_move` (Task 4) and `app.pipeline._persist_alert` (Task 5).

- [ ] **Step 1: Add the model**

Append to `backend/app/models.py`, after the `CalibrationSample` class:

```python
class MarketMove(Base):
    """One row per (event, ticker) -- the measured facts backing every
    user-facing number (docs/NEWS_IMPACT_APP_SPEC.md §3.1, §3.2). ``event``
    here is an Alert row (this codebase's NewsEvent). Arithmetic on
    observed prices only -- no LLM ever writes to this table. A row always
    exists once an alert is persisted (one per resolved company), even when
    measurement failed -- measurement_status='no_data' with null metric
    columns records that honestly rather than omitting the row.
    """
    __tablename__ = "market_moves"
    __table_args__ = (UniqueConstraint("alert_id", "company_id", name="uq_market_move_alert_company"),)

    id = Column(Integer, primary_key=True)
    alert_id = Column(Integer, ForeignKey("alerts.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    raw_move_pct = Column(Float, nullable=True)
    sector_move_pct = Column(Float, nullable=True)
    benchmark_ticker = Column(String, nullable=False)
    excess_move_pct = Column(Float, nullable=True)
    volume = Column(Float, nullable=True)
    avg_volume_20d = Column(Float, nullable=True)
    volume_multiple = Column(Float, nullable=True)
    measured_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    measurement_status = Column(String, nullable=False)  # ok | no_data | stale

    alert = relationship("Alert")
    company = relationship("Company")
```

- [ ] **Step 2: Verify the table is created by the existing test fixture**

Run: `cd backend && python -m pytest tests/test_models.py -v`
Expected: all existing tests still PASS (the `db_session` fixture's `Base.metadata.create_all` now also creates `market_moves`; nothing queries it yet, so no behavior changes).

- [ ] **Step 3: Commit**

```bash
git add backend/app/models.py
git commit -m "feat: add MarketMove model for measured (event, ticker) market facts"
```

---

### Task 4: Measurement service

**Files:**
- Create: `backend/app/market/measure.py`
- Test: `backend/tests/test_measure.py`

**Interfaces:**
- Consumes: `app.companies.price_series.fetch_daily_bars(ticker, period) -> list[dict] | None` (Task 1), `app.market.sector_indices.benchmark_ticker_for_sector(sector) -> str` (Task 2), `app.models.Company`, `app.models.MarketMove`, `app.models.utcnow`.
- Produces: `compute_excess_move_pct(raw_move_pct, sector_move_pct) -> float`, `compute_volume_multiple(day_volume, avg_volume_20d) -> float | None`, `measure_company_move(session, company) -> MarketMove` (unattached — caller sets `alert_id` and `session.add`s it). Consumed by `app.pipeline._persist_alert` (Task 5).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_measure.py`:

```python
import pytest

from app.market import measure
from app.models import Company


class _FakeCompany:
    def __init__(self, ticker, sector, company_id=1):
        self.id = company_id
        self.ticker = ticker
        self.sector = sector


def test_compute_excess_move_pct_positive():
    assert measure.compute_excess_move_pct(raw_move_pct=3.0, sector_move_pct=1.0) == 2.0


def test_compute_excess_move_pct_negative():
    assert measure.compute_excess_move_pct(raw_move_pct=-4.8, sector_move_pct=-0.6) == pytest.approx(-4.2)


def test_compute_volume_multiple_normal():
    assert measure.compute_volume_multiple(day_volume=300.0, avg_volume_20d=100.0) == 3.0


def test_compute_volume_multiple_zero_average_returns_none():
    assert measure.compute_volume_multiple(day_volume=300.0, avg_volume_20d=0.0) is None


def test_compute_volume_multiple_absent_average_returns_none():
    assert measure.compute_volume_multiple(day_volume=300.0, avg_volume_20d=None) is None


def _bars(closes, volumes, dates):
    return [{"date": d, "close": c, "volume": v} for d, c, v in zip(dates, closes, volumes)]


def test_measure_company_move_ok_path(monkeypatch):
    company = _FakeCompany(ticker="RELIANCE.NS", sector="oil_gas")
    dates = [f"2026-01-{i:02d}" for i in range(1, 23)]  # 22 trading days
    company_closes = [100.0] * 21 + [95.2]  # index 20 (prev close) -> index 21 (today): -4.8%
    # bars[-21:-1] (the 20-day trailing window) is indices 1..20 -- index 0
    # is padding excluded from that window, index 21 is "today"'s volume.
    company_volumes = [0.0] + [100.0] * 20 + [300.0]  # 20d avg = 100, today = 300 -> 3x
    benchmark_closes = [1000.0] * 21 + [994.0]  # index 20 -> index 21: -0.6%
    benchmark_volumes = [0.0] * 22

    def fake_fetch_daily_bars(ticker, period):
        if ticker == "RELIANCE.NS":
            return _bars(company_closes, company_volumes, dates)
        return _bars(benchmark_closes, benchmark_volumes, dates)

    monkeypatch.setattr(measure, "fetch_daily_bars", fake_fetch_daily_bars)

    move = measure.measure_company_move(session=None, company=company)

    assert move.measurement_status == "ok"
    assert move.company_id == 1
    assert move.benchmark_ticker == "^CNXENERGY"
    assert move.raw_move_pct == pytest.approx(-4.8, abs=0.01)
    assert move.sector_move_pct == pytest.approx(-0.6, abs=0.01)
    assert move.excess_move_pct == pytest.approx(-4.2, abs=0.02)
    assert move.volume == 300.0
    assert move.avg_volume_20d == pytest.approx(100.0, abs=0.01)
    assert move.volume_multiple == pytest.approx(3.0, abs=0.01)


def test_measure_company_move_no_data_when_company_bars_missing(monkeypatch):
    company = _FakeCompany(ticker="UNKNOWN.NS", sector="other")

    def fake_fetch_daily_bars(ticker, period):
        return None

    monkeypatch.setattr(measure, "fetch_daily_bars", fake_fetch_daily_bars)

    move = measure.measure_company_move(session=None, company=company)

    assert move.measurement_status == "no_data"
    assert move.raw_move_pct is None
    assert move.sector_move_pct is None
    assert move.excess_move_pct is None
    assert move.benchmark_ticker == "^NSEI"  # "other" falls back to Nifty 50


def test_measure_company_move_no_data_when_benchmark_bars_missing(monkeypatch):
    company = _FakeCompany(ticker="RELIANCE.NS", sector="oil_gas")

    def fake_fetch_daily_bars(ticker, period):
        if ticker == "RELIANCE.NS":
            return _bars([100.0, 101.0], [10.0, 10.0], ["2026-01-01", "2026-01-02"])
        return None  # benchmark fetch fails

    monkeypatch.setattr(measure, "fetch_daily_bars", fake_fetch_daily_bars)

    move = measure.measure_company_move(session=None, company=company)

    assert move.measurement_status == "no_data"
    assert move.excess_move_pct is None


def test_measure_company_move_fallback_benchmark_recorded_for_unmapped_sector(monkeypatch):
    company = _FakeCompany(ticker="SOMECO.NS", sector="textiles")

    def fake_fetch_daily_bars(ticker, period):
        return _bars([100.0, 101.0], [10.0, 10.0], ["2026-01-01", "2026-01-02"])

    monkeypatch.setattr(measure, "fetch_daily_bars", fake_fetch_daily_bars)

    move = measure.measure_company_move(session=None, company=company)

    assert move.benchmark_ticker == "^NSEI"
    assert move.measurement_status == "ok"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_measure.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.market.measure'`.

- [ ] **Step 3: Implement the measurement service**

Create `backend/app/market/measure.py`:

```python
"""Deterministic market-measurement service -- the spine of the app
(docs/NEWS_IMPACT_APP_SPEC.md §3-§5). Every function here is arithmetic
over price/volume bars; nothing calls an LLM. Built on
app.companies.price_series.fetch_daily_bars and
app.market.sector_indices.benchmark_ticker_for_sector.
"""
from sqlalchemy.orm import Session

from app.companies.price_series import fetch_daily_bars
from app.market.sector_indices import benchmark_ticker_for_sector
from app.models import Company, MarketMove, utcnow


def compute_excess_move_pct(raw_move_pct: float, sector_move_pct: float) -> float:
    """§4.1 simple tier: excess = raw - sector. The beta-adjusted tier
    (spec §4.1) is a deliberate, unbuilt seam -- this (raw, sector) ->
    excess signature is what a future beta-adjusted variant would still
    need to satisfy, so callers never change."""
    return raw_move_pct - sector_move_pct


def compute_volume_multiple(day_volume: float, avg_volume_20d: float | None) -> float | None:
    """day_volume / trailing_20d_avg_volume, or None if the average is
    zero or absent -- never a fabricated or divide-by-zero number."""
    if not avg_volume_20d:
        return None
    return day_volume / avg_volume_20d


def _daily_return_pct(bars: list[dict]) -> float | None:
    """Latest day's own % close-to-close move from a fetch_daily_bars()
    series, or None if fewer than 2 points exist or the prior close is 0."""
    if len(bars) < 2:
        return None
    prev_close = bars[-2]["close"]
    last_close = bars[-1]["close"]
    if not prev_close:
        return None
    return (last_close - prev_close) / prev_close * 100


def measure_company_move(session: Session, company: Company) -> MarketMove:
    """Fetch real price/volume bars for ``company`` and its sector
    benchmark, compute the measured facts, and return an unattached
    MarketMove row (caller must set alert_id and session.add it). Never
    raises -- any missing upstream data produces measurement_status=
    'no_data' with null metric columns rather than a fabricated number or
    a crashed alert.
    """
    benchmark_ticker = benchmark_ticker_for_sector(company.sector)
    company_bars = fetch_daily_bars(company.ticker, period="2mo")
    benchmark_bars = fetch_daily_bars(benchmark_ticker, period="2mo")

    if not company_bars or not benchmark_bars:
        return MarketMove(
            company_id=company.id, benchmark_ticker=benchmark_ticker,
            measurement_status="no_data", measured_at=utcnow(),
        )

    raw_move_pct = _daily_return_pct(company_bars)
    sector_move_pct = _daily_return_pct(benchmark_bars)
    if raw_move_pct is None or sector_move_pct is None:
        return MarketMove(
            company_id=company.id, benchmark_ticker=benchmark_ticker,
            measurement_status="no_data", measured_at=utcnow(),
        )

    day_volume = company_bars[-1]["volume"]
    trailing = [b["volume"] for b in company_bars[-21:-1]]  # 20 days before today
    avg_volume_20d = (sum(trailing) / len(trailing)) if trailing else None
    volume_multiple = compute_volume_multiple(day_volume, avg_volume_20d)

    return MarketMove(
        company_id=company.id,
        raw_move_pct=raw_move_pct,
        sector_move_pct=sector_move_pct,
        benchmark_ticker=benchmark_ticker,
        excess_move_pct=compute_excess_move_pct(raw_move_pct, sector_move_pct),
        volume=day_volume,
        avg_volume_20d=avg_volume_20d,
        volume_multiple=volume_multiple,
        measured_at=utcnow(),
        measurement_status="ok",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_measure.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/market/measure.py backend/tests/test_measure.py
git commit -m "feat: add measure_company_move — deterministic excess-move/volume-multiple measurement"
```

---

### Task 5: Wire measurement into the pipeline after company resolution

**Files:**
- Modify: `backend/app/pipeline.py`
- Modify: `backend/tests/conftest.py`
- Test: `backend/tests/test_market_move_wiring.py`

**Interfaces:**
- Consumes: `app.market.measure.measure_company_move(session, company) -> MarketMove` (Task 4).
- Produces: one `MarketMove` row per resolved company, attached to the new alert, written inside `_persist_alert`.

- [ ] **Step 1: Add the autouse test stub (network-free tests, matching the existing financial-snapshot pattern)**

In `backend/tests/conftest.py`, append after `_no_real_financial_snapshot_fetch`:

```python
@pytest.fixture(autouse=True)
def _no_real_market_move_fetch(monkeypatch):
    # process_new_articles now calls measure_company_move for every resolved
    # company, which would otherwise make real yfinance network calls in
    # every pipeline test that doesn't care about this feature. Stub it to
    # a no_data MarketMove by default -- tests that DO care about
    # measurement behavior (test_measure.py, test_market_move_wiring.py)
    # override this via their own monkeypatch.setattr, which takes
    # precedence over this autouse default.
    from app.models import MarketMove, utcnow

    def fake_measure(session, company):
        return MarketMove(
            company_id=company.id, benchmark_ticker="^NSEI",
            measurement_status="no_data", measured_at=utcnow(),
        )

    monkeypatch.setattr("app.pipeline.measure_company_move", fake_measure)
```

- [ ] **Step 2: Write the failing pipeline-wiring test**

Create `backend/tests/test_market_move_wiring.py`:

```python
from app.analysis.schemas import AnalysisOutput, CompanyMention
from app.models import Company, MarketMove
from app.pipeline import process_new_articles
import app.pipeline as pipeline_module


def _company():
    return Company(
        ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas",
        index_tier="NIFTY50", market_cap=1.0,
    )


def _article(db_session):
    from app.models import Article
    article = Article(
        source="test", url="https://example.com/a",
        title="Oil prices surge on supply disruption", content="crude oil markets react",
    )
    db_session.add(article)
    db_session.commit()
    return article


def _fake_analysis():
    return AnalysisOutput(
        category="oil_gas",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
            key_points=["Crude eases"], confidence_score=85, time_horizon="Short-Term",
        )],
    )


def test_persist_alert_writes_a_market_move_row_per_company(db_session, monkeypatch):
    company = _company()
    db_session.add(company)
    db_session.commit()
    article = _article(db_session)

    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: _fake_analysis())

    created = process_new_articles(db_session, claude_client=object())

    assert created == 1
    alert = db_session.query(pipeline_module.Alert).one()
    moves = db_session.query(MarketMove).filter_by(alert_id=alert.id).all()
    assert len(moves) == 1
    assert moves[0].company_id == company.id
    # The autouse conftest stub returns no_data -- this test only checks the
    # WIRING (one row per company, alert_id set, no crash), not measurement
    # arithmetic (covered by test_measure.py).
    assert moves[0].measurement_status == "no_data"


def test_persist_alert_does_not_crash_when_measurement_raises_no_data(db_session, monkeypatch):
    # Belt-and-braces: even if measure_company_move's own no_data path is
    # exercised for real (not the conftest stub), _persist_alert must not
    # crash and must still create the Alert + AlertCompany rows.
    from app.models import MarketMove, utcnow

    def fake_measure_real_no_data(session, company):
        return MarketMove(
            company_id=company.id, benchmark_ticker="^CNXENERGY",
            measurement_status="no_data", measured_at=utcnow(),
        )

    monkeypatch.setattr(pipeline_module, "measure_company_move", fake_measure_real_no_data)

    company = _company()
    db_session.add(company)
    db_session.commit()
    article = _article(db_session)
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: _fake_analysis())

    created = process_new_articles(db_session, claude_client=object())

    assert created == 1
    alert = db_session.query(pipeline_module.Alert).one()
    assert db_session.query(pipeline_module.AlertCompany).filter_by(alert_id=alert.id).count() == 1
    moves = db_session.query(MarketMove).filter_by(alert_id=alert.id).all()
    assert len(moves) == 1
    assert moves[0].benchmark_ticker == "^CNXENERGY"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_market_move_wiring.py -v`
Expected: FAIL — `MarketMove` table has no rows (nothing writes to it yet), or `AttributeError: module 'app.pipeline' has no attribute 'measure_company_move'`.

- [ ] **Step 4: Wire `measure_company_move` into `_persist_alert`**

In `backend/app/pipeline.py`, add the import alongside the existing ones (near the top, with the other `app.market`-style imports — insert after the `app.filtering.relevance` import line):

```python
from app.market.measure import measure_company_move
```

Then in `_persist_alert` (`backend/app/pipeline.py`), immediately after the existing `for entry in entries: session.add(_build_alert_company(...))` loop and before the `for gap in (gaps or []):` loop, add:

```python
    for entry in entries:
        company_obj = session.get(Company, entry["company_id"])
        if company_obj is not None:
            move = measure_company_move(session, company_obj)
            move.alert_id = alert.id
            session.add(move)
```

(`Company` is already imported in `pipeline.py`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_market_move_wiring.py -v`
Expected: all PASS.

- [ ] **Step 6: Run the full backend suite to confirm no regressions**

Run: `cd backend && python -m pytest -q`
Expected: all tests PASS (the new autouse fixture keeps every existing pipeline test network-free, matching the `_no_real_financial_snapshot_fetch` precedent).

- [ ] **Step 7: Commit**

```bash
git add backend/app/pipeline.py backend/tests/conftest.py backend/tests/test_market_move_wiring.py
git commit -m "feat: wire measure_company_move into the pipeline after company resolution"
```

---

## PHASE 1 STOP — required report before Phase 2

Before continuing, report:
1. The verbatim output of `python backend/verify_sector_indices.py` (Task 2, Step 7).
2. How many of the 18 `SECTORS` resolved to a real sector index vs. the Nifty 50 fallback (per `SECTOR_INDEX_MAP`/`FALLBACK_SECTORS`: expect 11 real, 7 fallback, pending the verification script confirming all 11 real tickers actually return data).

---

## PHASE 2 — Derived metrics (spec §4.2–§4.5)

All pure functions over already-measured values (no DB session needed except `cap_tier.py`'s convenience wrapper), all in `app/market/`, all unit-tested.

### Task 6: Config — weights, band thresholds, verdict threshold, AMFI rank cutoffs

**Files:**
- Modify: `backend/app/config.py`

- [ ] **Step 1: Add the constants**

Append to `backend/app/config.py`, after the `settings = Settings()` line at the bottom:

```python

# --- Market-impact measurement constants (docs/NEWS_IMPACT_APP_SPEC.md §4) ---
# Not environment-backed: these are product/algorithm constants tuned via
# CAR back-validation (spec §4.6, a later phase), not per-deployment
# secrets -- unlike every Settings field above. Every intensity/verdict/
# cap-tier function in app/market/ reads its weights and thresholds from
# here, never hardcodes them (spec §4.2, §10).

# Live-feed intensity weights (spec §4.2) -- must sum to 1.0. The advisory-
# tier weight profile (adds a fundamental_score term) is out of scope until
# the FundamentalEstimate/RIA-advisory phase.
INTENSITY_WEIGHTS_LIVE = {"excess": 0.55, "volume": 0.25, "breadth": 0.20}

# Intensity band thresholds (spec §4.2): >=75 High, 50-74 Moderate, <50 Low.
INTENSITY_BAND_HIGH = 75
INTENSITY_BAND_MODERATE = 50

# A move (as % excess) at or above this magnitude is "meaningful" for
# breadth counting (spec §4.4) -- a linked stock that barely twitched
# doesn't count as part of the event's spread.
BREADTH_MEANINGFUL_MOVE_PCT = 1.0

# Verdict threshold (spec §4.3): |excess_move_pct| at or above this ->
# COMPANY_SPECIFIC, else SECTOR_WIDE (when not UNCONFIRMED). Starting value;
# retune against CAR outcomes (spec §4.6) once that data exists.
VERDICT_EXCESS_THRESHOLD_PCT = 2.0

# AMFI-style cap-tier rank cutoffs (spec §4.5): rank 1-100 by market cap ->
# LARGE, 101-250 -> MID, rest -> SMALL. Ranks are recomputed from live
# Company.market_cap every call -- never a hardcoded company list.
AMFI_LARGE_CAP_RANK_CUTOFF = 100
AMFI_MID_CAP_RANK_CUTOFF = 250
```

- [ ] **Step 2: Verify the module still imports cleanly**

Run: `cd backend && python -c "from app import config; print(config.INTENSITY_WEIGHTS_LIVE)"`
Expected: prints `{'excess': 0.55, 'volume': 0.25, 'breadth': 0.2}` with no error.

- [ ] **Step 3: Commit**

```bash
git add backend/app/config.py
git commit -m "feat: add intensity/verdict/AMFI config constants (spec §4)"
```

---

### Task 7: Composite intensity score

**Files:**
- Create: `backend/app/market/intensity.py`
- Test: `backend/tests/test_intensity.py`

**Interfaces:**
- Consumes: `app.config.INTENSITY_WEIGHTS_LIVE`, `INTENSITY_BAND_HIGH`, `INTENSITY_BAND_MODERATE`.
- Produces: `normalize_score(value: float, peer_values: list[float]) -> float`, `compute_intensity(*, excess_move_pct, excess_peer_group, volume_multiple, volume_peer_group, breadth_score, weights=None) -> dict` returning `{"score": int, "band": str, "components": [{"label": str, "raw": float, "weight": float, "contribution": float}, ...]}`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_intensity.py`:

```python
import pytest

from app.market import intensity
from app import config


def test_normalize_score_min_max_within_group():
    # value is the max of its peer group -> 100
    assert intensity.normalize_score(5.0, [1.0, 3.0, 5.0]) == pytest.approx(100.0)
    # value is the min -> 0
    assert intensity.normalize_score(1.0, [1.0, 3.0, 5.0]) == pytest.approx(0.0)
    # value is the midpoint -> 50
    assert intensity.normalize_score(3.0, [1.0, 3.0, 5.0]) == pytest.approx(50.0)


def test_normalize_score_uses_absolute_value():
    # A -5% excess move among peers [1, 3, 5] should normalize the same as +5.
    assert intensity.normalize_score(-5.0, [1.0, 3.0, 5.0]) == pytest.approx(100.0)


def test_normalize_score_degenerate_group_returns_100():
    # A single-member (or all-equal) peer group has no "less than" to
    # compare against -- the value IS the max there is.
    assert intensity.normalize_score(2.0, [2.0]) == pytest.approx(100.0)
    assert intensity.normalize_score(2.0, [2.0, 2.0, 2.0]) == pytest.approx(100.0)


def test_compute_intensity_matches_hand_computed_value():
    # excess=-4.8 is the max-magnitude peer -> excess_score=100
    # volume_multiple=3.0 is the max-magnitude peer -> volume_score=100
    # breadth_score=40 (already 0-100, used directly)
    result = intensity.compute_intensity(
        excess_move_pct=-4.8, excess_peer_group=[-4.8, -1.0, 0.5],
        volume_multiple=3.0, volume_peer_group=[3.0, 1.0],
        breadth_score=40,
    )
    expected_score = round(100 * 0.55 + 100 * 0.25 + 40 * 0.20)  # 55 + 25 + 8 = 88
    assert result["score"] == expected_score
    assert result["band"] == "High"
    assert len(result["components"]) == 3
    labels = {c["label"] for c in result["components"]}
    assert labels == {"excess", "volume", "breadth"}


def test_compute_intensity_never_returns_a_bare_number():
    result = intensity.compute_intensity(
        excess_move_pct=1.0, excess_peer_group=[1.0],
        volume_multiple=1.0, volume_peer_group=[1.0],
        breadth_score=10,
    )
    assert isinstance(result, dict)
    assert set(result.keys()) == {"score", "band", "components"}
    for component in result["components"]:
        assert set(component.keys()) == {"label", "raw", "weight", "contribution"}


def test_changing_a_config_weight_changes_the_score():
    kwargs = dict(
        excess_move_pct=-4.8, excess_peer_group=[-4.8, -1.0],
        volume_multiple=3.0, volume_peer_group=[3.0, 1.0],
        breadth_score=40,
    )
    default_result = intensity.compute_intensity(**kwargs)
    custom_result = intensity.compute_intensity(
        **kwargs, weights={"excess": 0.10, "volume": 0.10, "breadth": 0.80},
    )
    assert default_result["score"] != custom_result["score"]


def test_within_sector_normalization_gives_consistent_meaning_across_events():
    # Two "70-equivalent" events with wildly different absolute magnitudes
    # should both land on the same excess_score when normalized against
    # their OWN peer group (spec §4.2: normalize within sector/event, not
    # globally).
    small_move_event = intensity.normalize_score(0.7, [0.0, 0.7, 1.0])
    large_move_event = intensity.normalize_score(70.0, [0.0, 70.0, 100.0])
    assert small_move_event == pytest.approx(large_move_event)


def test_band_thresholds():
    high = intensity.compute_intensity(
        excess_move_pct=10, excess_peer_group=[10], volume_multiple=10,
        volume_peer_group=[10], breadth_score=100,
    )
    assert high["score"] >= config.INTENSITY_BAND_HIGH
    assert high["band"] == "High"

    low = intensity.compute_intensity(
        excess_move_pct=0.01, excess_peer_group=[0.01, 100], volume_multiple=0.01,
        volume_peer_group=[0.01, 100], breadth_score=0,
    )
    assert low["score"] < config.INTENSITY_BAND_MODERATE
    assert low["band"] == "Low"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_intensity.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.market.intensity'`.

- [ ] **Step 3: Implement**

Create `backend/app/market/intensity.py`:

```python
"""Composite intensity score (docs/NEWS_IMPACT_APP_SPEC.md §4.2). Pure
functions only -- intensity is derived on read, never persisted as truth
(spec §3.2). Weights and band thresholds live in app.config, never
hardcoded here (spec §10)."""
from app import config


def normalize_score(value: float, peer_values: list[float]) -> float:
    """Min-max normalize |value| against the |peer_values| population to a
    0-100 score. ``peer_values`` must be the within-sector or within-event
    peer group (spec §4.2: "normalize within sector or event, not
    globally") -- never a global population. A degenerate group (single
    member, or every peer equal) returns 100 -- the value IS the max there
    is, no meaningful "less than" exists to compare it against.
    """
    peers = [abs(v) for v in peer_values]
    value = abs(value)
    lo, hi = min(peers), max(peers)
    if hi == lo:
        return 100.0
    return max(0.0, min(100.0, (value - lo) / (hi - lo) * 100))


def compute_intensity(
    *, excess_move_pct: float, excess_peer_group: list[float],
    volume_multiple: float, volume_peer_group: list[float],
    breadth_score: float, weights: dict[str, float] | None = None,
) -> dict:
    """Live-feed intensity (spec §4.2): 0.55*excess + 0.25*volume +
    0.20*breadth by default (app.config.INTENSITY_WEIGHTS_LIVE), overridable
    via ``weights`` for testing/retuning. Always returns the full component
    breakdown alongside the score -- the UI is required to show it, so this
    function must never return a bare number (spec §4.2, §10).
    """
    weights = weights or config.INTENSITY_WEIGHTS_LIVE
    excess_score = normalize_score(excess_move_pct, excess_peer_group)
    volume_score = normalize_score(volume_multiple, volume_peer_group)
    breadth_component = max(0.0, min(100.0, breadth_score))

    components = [
        {
            "label": "excess", "raw": excess_move_pct, "weight": weights["excess"],
            "contribution": excess_score * weights["excess"],
        },
        {
            "label": "volume", "raw": volume_multiple, "weight": weights["volume"],
            "contribution": volume_score * weights["volume"],
        },
        {
            "label": "breadth", "raw": breadth_score, "weight": weights["breadth"],
            "contribution": breadth_component * weights["breadth"],
        },
    ]
    score = round(sum(c["contribution"] for c in components))
    if score >= config.INTENSITY_BAND_HIGH:
        band = "High"
    elif score >= config.INTENSITY_BAND_MODERATE:
        band = "Moderate"
    else:
        band = "Low"
    return {"score": score, "band": band, "components": components}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_intensity.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/market/intensity.py backend/tests/test_intensity.py
git commit -m "feat: add compute_intensity — config-weighted composite score with component breakdown"
```

---

### Task 8: Breadth score

**Files:**
- Create: `backend/app/market/breadth.py`
- Test: `backend/tests/test_breadth.py`

**Interfaces:**
- Consumes: `app.config.BREADTH_MEANINGFUL_MOVE_PCT`.
- Produces: `compute_breadth_score(excess_moves: list[float], meaningful_threshold_pct: float | None = None) -> int`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_breadth.py`:

```python
from app.market import breadth


def test_all_moved_meaningfully_scores_100():
    assert breadth.compute_breadth_score([5.0, -6.0, 3.0], meaningful_threshold_pct=1.0) == 100


def test_none_moved_meaningfully_scores_0():
    assert breadth.compute_breadth_score([0.1, -0.2, 0.05], meaningful_threshold_pct=1.0) == 0


def test_half_moved_meaningfully_scores_50():
    assert breadth.compute_breadth_score([5.0, 0.1, -6.0, 0.05], meaningful_threshold_pct=1.0) == 50


def test_empty_list_scores_0():
    assert breadth.compute_breadth_score([], meaningful_threshold_pct=1.0) == 0


def test_uses_config_default_threshold_when_not_passed():
    # One-company earnings beat (a single meaningful move) should score
    # LOW breadth, a sector-wide event (many meaningful moves) HIGH --
    # spec §4.4.
    low = breadth.compute_breadth_score([5.0, 0.1, 0.1, 0.1, 0.1])
    high = breadth.compute_breadth_score([5.0, 4.0, 3.0, 6.0, 5.0])
    assert low < high
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_breadth.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

Create `backend/app/market/breadth.py`:

```python
"""Breadth score (docs/NEWS_IMPACT_APP_SPEC.md §4.4): what fraction of an
event's linked stocks (direct + ripple) showed a meaningful excess move,
normalized 0-100. Pure function -- derived on read, never persisted."""
from app import config


def compute_breadth_score(
    excess_moves: list[float], meaningful_threshold_pct: float | None = None,
) -> int:
    """``excess_moves`` is every linked stock's excess_move_pct for one
    event (direct + ripple). A one-company earnings beat scores low
    breadth; a sector-wide event where most linked stocks moved
    meaningfully scores high (spec §4.4)."""
    threshold = (
        meaningful_threshold_pct
        if meaningful_threshold_pct is not None
        else config.BREADTH_MEANINGFUL_MOVE_PCT
    )
    if not excess_moves:
        return 0
    meaningful = sum(1 for m in excess_moves if abs(m) >= threshold)
    return round(meaningful / len(excess_moves) * 100)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_breadth.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/market/breadth.py backend/tests/test_breadth.py
git commit -m "feat: add compute_breadth_score (spec §4.4)"
```

---

### Task 9: Verdict tag

**Files:**
- Create: `backend/app/market/verdict.py`
- Test: `backend/tests/test_verdict.py`

**Interfaces:**
- Consumes: `app.config.VERDICT_EXCESS_THRESHOLD_PCT`.
- Produces: `compute_verdict(*, is_unconfirmed: bool, excess_move_pct: float | None, threshold_pct: float | None = None) -> str` returning one of `"UNCONFIRMED"`, `"COMPANY_SPECIFIC"`, `"SECTOR_WIDE"`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_verdict.py`:

```python
from app.market import verdict


def test_unconfirmed_branch_wins_regardless_of_excess():
    assert verdict.compute_verdict(is_unconfirmed=True, excess_move_pct=10.0) == "UNCONFIRMED"
    assert verdict.compute_verdict(is_unconfirmed=True, excess_move_pct=None) == "UNCONFIRMED"


def test_company_specific_branch():
    assert verdict.compute_verdict(is_unconfirmed=False, excess_move_pct=4.8, threshold_pct=2.0) == "COMPANY_SPECIFIC"
    assert verdict.compute_verdict(is_unconfirmed=False, excess_move_pct=-4.8, threshold_pct=2.0) == "COMPANY_SPECIFIC"


def test_sector_wide_branch():
    assert verdict.compute_verdict(is_unconfirmed=False, excess_move_pct=0.5, threshold_pct=2.0) == "SECTOR_WIDE"


def test_missing_excess_move_treated_as_sector_wide_not_a_crash():
    # No measurement (measurement_status='no_data') must never crash the
    # verdict -- absent excess is treated as not-yet-confirmed-company-
    # specific, i.e. SECTOR_WIDE (the "usually skippable" default).
    assert verdict.compute_verdict(is_unconfirmed=False, excess_move_pct=None, threshold_pct=2.0) == "SECTOR_WIDE"


def test_uses_config_default_threshold_when_not_passed():
    from app import config
    result = verdict.compute_verdict(is_unconfirmed=False, excess_move_pct=config.VERDICT_EXCESS_THRESHOLD_PCT)
    assert result == "COMPANY_SPECIFIC"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_verdict.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

Create `backend/app/market/verdict.py`:

```python
"""Verdict tag (docs/NEWS_IMPACT_APP_SPEC.md §4.3). ``is_unconfirmed`` is a
judgment call (rumor/denial classification) supplied by the LLM refinement
layer (a later phase) -- this function only encodes the derivation logic
once that boolean exists; it never classifies text itself."""
from app import config


def compute_verdict(
    *, is_unconfirmed: bool, excess_move_pct: float | None, threshold_pct: float | None = None,
) -> str:
    if is_unconfirmed:
        return "UNCONFIRMED"
    threshold = threshold_pct if threshold_pct is not None else config.VERDICT_EXCESS_THRESHOLD_PCT
    if excess_move_pct is not None and abs(excess_move_pct) >= threshold:
        return "COMPANY_SPECIFIC"
    return "SECTOR_WIDE"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_verdict.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/market/verdict.py backend/tests/test_verdict.py
git commit -m "feat: add compute_verdict (spec §4.3)"
```

---

### Task 10: Cap tier (AMFI-style, recomputed)

**Files:**
- Create: `backend/app/market/cap_tier.py`
- Test: `backend/tests/test_cap_tier.py`

**Interfaces:**
- Consumes: `app.config.AMFI_LARGE_CAP_RANK_CUTOFF`, `AMFI_MID_CAP_RANK_CUTOFF`, `app.models.Company`.
- Produces: `compute_cap_tiers(companies: list[tuple[str, float]]) -> dict[str, str]` (pure), `compute_cap_tier_for_ticker(session, ticker) -> str | None` (DB convenience wrapper).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_cap_tier.py`:

```python
from app.market import cap_tier
from app.models import Company


def test_top_100_by_market_cap_are_large():
    companies = [(f"T{i}.NS", float(1000 - i)) for i in range(150)]  # descending cap
    tiers = cap_tier.compute_cap_tiers(companies)
    assert tiers["T0.NS"] == "LARGE"
    assert tiers["T99.NS"] == "LARGE"
    assert tiers["T100.NS"] == "MID"


def test_101_to_250_are_mid():
    companies = [(f"T{i}.NS", float(1000 - i)) for i in range(260)]
    tiers = cap_tier.compute_cap_tiers(companies)
    assert tiers["T100.NS"] == "MID"
    assert tiers["T249.NS"] == "MID"
    assert tiers["T250.NS"] == "SMALL"


def test_rest_are_small():
    companies = [(f"T{i}.NS", float(1000 - i)) for i in range(300)]
    tiers = cap_tier.compute_cap_tiers(companies)
    assert tiers["T299.NS"] == "SMALL"


def test_boundary_is_config_driven():
    from app import config
    companies = [(f"T{i}.NS", float(1000 - i)) for i in range(300)]
    tiers = cap_tier.compute_cap_tiers(companies)
    boundary_ticker = f"T{config.AMFI_LARGE_CAP_RANK_CUTOFF - 1}.NS"
    assert tiers[boundary_ticker] == "LARGE"


def test_compute_cap_tier_for_ticker_ranks_from_live_db_state(db_session):
    for i in range(105):
        db_session.add(Company(
            ticker=f"T{i}.NS", name=f"Company {i}", sector="other",
            index_tier="OTHER", market_cap=float(1000 - i),
        ))
    db_session.commit()

    assert cap_tier.compute_cap_tier_for_ticker(db_session, "T0.NS") == "LARGE"
    assert cap_tier.compute_cap_tier_for_ticker(db_session, "T104.NS") == "MID"


def test_compute_cap_tier_for_ticker_none_when_no_market_cap(db_session):
    db_session.add(Company(
        ticker="NOCAP.NS", name="No Cap Co", sector="other", index_tier="OTHER", market_cap=None,
    ))
    db_session.commit()

    assert cap_tier.compute_cap_tier_for_ticker(db_session, "NOCAP.NS") is None


def test_compute_cap_tier_for_ticker_none_when_ticker_not_found(db_session):
    assert cap_tier.compute_cap_tier_for_ticker(db_session, "NOPE.NS") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_cap_tier.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

Create `backend/app/market/cap_tier.py`:

```python
"""Market-cap tier (docs/NEWS_IMPACT_APP_SPEC.md §4.5): AMFI-style rank
boundaries (top 100 = LARGE, 101-250 = MID, rest = SMALL), recomputed from
LIVE market cap every call -- never a hardcoded company list, never stored
as fixed truth (spec §3.2). Note: this is a distinct axis from
Company.index_tier (Nifty-index-membership tier, seeded once from
app.companies.nifty_indices_seed) -- that field is untouched by this
module."""
from sqlalchemy.orm import Session

from app import config
from app.models import Company


def compute_cap_tiers(companies: list[tuple[str, float]]) -> dict[str, str]:
    """``companies`` is [(ticker, market_cap_cr), ...] with non-null market
    caps. Ranks by market cap descending and buckets by AMFI-style rank
    cutoffs from app.config. Returns {ticker: 'LARGE'|'MID'|'SMALL'}."""
    ranked = sorted(companies, key=lambda tc: tc[1], reverse=True)
    tiers: dict[str, str] = {}
    for rank, (ticker, _cap) in enumerate(ranked, start=1):
        if rank <= config.AMFI_LARGE_CAP_RANK_CUTOFF:
            tiers[ticker] = "LARGE"
        elif rank <= config.AMFI_MID_CAP_RANK_CUTOFF:
            tiers[ticker] = "MID"
        else:
            tiers[ticker] = "SMALL"
    return tiers


def compute_cap_tier_for_ticker(session: Session, ticker: str) -> str | None:
    """Convenience wrapper: rank every Company with a non-null market_cap
    in the DB right now and return this ticker's tier, or None if it has
    no market_cap or isn't found. Queries fresh every call -- cap_tier is
    derived, never stored (spec §3.2)."""
    rows = (
        session.query(Company.ticker, Company.market_cap)
        .filter(Company.market_cap.isnot(None))
        .all()
    )
    tiers = compute_cap_tiers([(t, c) for t, c in rows])
    return tiers.get(ticker)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_cap_tier.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/market/cap_tier.py backend/tests/test_cap_tier.py
git commit -m "feat: add compute_cap_tier — AMFI-style rank boundaries, recomputed from live market cap"
```

---

### Task 11: Full-suite regression check

- [ ] **Step 1: Run the entire backend test suite**

Run: `cd backend && python -m pytest -q`
Expected: all tests PASS — every task above is additive-only (new files, new table, one new pipeline hook guarded by an autouse test stub), so nothing pre-existing should regress.

- [ ] **Step 2: Commit (only if Step 1 required any fix)**

If Step 1 was clean, nothing to commit here. If it required a fix, commit it separately with a message describing exactly what regressed and why.

---

## PHASE 2 STOP — required report before Phase 3

Report:
1. Full-suite pass/fail status (Task 11).
2. Confirmation that `intensity`/`cap_tier` are pure functions not wired into the pipeline or any API response yet (by design — Phase 2 is measurement-and-metrics only; wiring into `_serialize_alert`/the frontend happens in later UI phases, per the task brief).
3. Any spec ambiguity hit and how it was resolved (e.g. `VERDICT_EXCESS_THRESHOLD_PCT` and the 7 sectors mapped to the Nifty 50 fallback beyond the task brief's explicit 4 examples — both documented inline in `app/config.py` and `app/market/sector_indices.py`).

This plan ends here. Phase 3 (LLM refinement layer — repointing the cascade at `why`/`summary_short`/`summary_long`/`RippleLink.relationship`/`TimelineEffect`, plus output validation) is a separate plan, written after this one ships and the report above is reviewed.
