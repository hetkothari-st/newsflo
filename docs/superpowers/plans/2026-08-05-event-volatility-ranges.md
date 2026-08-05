# Event Volatility Ranges (Subsystem D) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store per-(stock, news-category) empirical reaction ranges built nightly from measured `market_moves`, serve them on card-back rows and the deep-dive sheet, and show nothing where measured history is insufficient.

**Architecture:** One new aggregate table `event_volatility_ranges`, fully rebuilt nightly by a pure builder over `market_moves` rows (status `ok`, non-null `excess_move_pct`, non-null `category`). A fallback ladder serves COMPANY-level rows first, then SECTOR-level pools, then nothing. `market_moves` gains a `category` column stamped at measurement time (reclassification safety, same pattern as `calibration_samples.category`).

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0.35, pytest; React + TypeScript (live tree is `frontend/src/v3/`). No Alembic — migrations via `_ADDED_COLUMNS` in `app/db.py` + `Base.metadata.create_all`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-05-event-volatility-ranges-design.md`.
- Measured data only: ranges derive exclusively from `market_moves` rows with `measurement_status = 'ok'`, non-null `excess_move_pct`, non-null `category`. No LLM output, no estimates, ever.
- Thresholds live in `app/config.py`, never hardcoded: `EVENT_VOL_COMPANY_MIN_EVENTS = 3`, `EVENT_VOL_SECTOR_MIN_EVENTS = 5`.
- Range statistics are exactly min / median / max of `excess_move_pct` — no percentiles, no fitting.
- `sector = 'other'` companies contribute no SECTOR pool rows but still earn COMPANY rows.
- SECTOR pools include measurements from ALL companies in the sector, including those that also earn COMPANY rows.
- Empty builder input must NOT delete existing rows (never clobber good data with nothing).
- Builder reads `market_moves.category` only — never a live join to `alerts.category`.
- Serialized key is `volatility_range`; payload shape `{"level", "n_events", "min_excess_move_pct", "median_excess_move_pct", "max_excess_move_pct", "as_of"}` with `as_of` ISO string.
- The no-alert deep-dive path (Directory) serves `volatility_range: null` — no category, no range.
- SECTOR-level ranges must be visibly labeled in the UI; never dressed as stock-specific.
- Frontend changes go in the live `frontend/src/v3/` tree (plus the shared component dir); `feed-v2/` and `src/pages/` legacy trees are NOT targets.
- Scheduler jobs log and never raise; job bodies must be provably network-free in tests.

## File Structure

- `backend/app/models.py` — `EventVolatilityRange` model + `MarketMove.category` column (modify)
- `backend/app/db.py` — `_ADDED_COLUMNS` entry for `market_moves.category` (modify)
- `backend/app/config.py` — two threshold constants (modify)
- `backend/app/pipeline.py` — stamp `move.category` (modify)
- `backend/app/market/event_volatility.py` — builder + payload (create; the one home for subsystem D logic)
- `backend/app/market/ripple_layers.py` — serve `volatility_range` per row (modify)
- `backend/app/routers/stock_deep_dive.py` — serve `volatility_range` (modify)
- `backend/app/scheduler.py` — nightly rebuild job (modify)
- `backend/backfill_event_volatility.py` — runbook: category backfill + rebuild (create)
- `backend/tests/test_event_volatility.py` — builder/payload tests (create)
- `frontend/src/v3/api.ts`, `frontend/src/v3/Sheets.tsx`, `frontend/src/v3/Shell.tsx`, `frontend/src/v3/v3.css`, `frontend/src/components/VolatilityRange.tsx` — types + rendering (modify/create)

---

### Task 1: Schema + config — `EventVolatilityRange`, `market_moves.category`, thresholds

**Files:**
- Modify: `backend/app/models.py` (MarketMove class ~line 402; new model after `CarOutcome`)
- Modify: `backend/app/db.py` (`_ADDED_COLUMNS` list)
- Modify: `backend/app/config.py` (after the CAR constants ~line 318)
- Test: `backend/tests/test_event_volatility.py` (create)

**Interfaces:**
- Produces: `app.models.EventVolatilityRange` with columns `id, level, company_id, sector, category, n_events, min_excess_move_pct, median_excess_move_pct, max_excess_move_pct, as_of, source`; `MarketMove.category` (String, nullable); `config.EVENT_VOL_COMPANY_MIN_EVENTS = 3`, `config.EVENT_VOL_SECTOR_MIN_EVENTS = 5`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_event_volatility.py
"""Subsystem D: per-(stock, category) reaction ranges from measured moves.

Spec: docs/superpowers/specs/2026-08-05-event-volatility-ranges-design.md.
The tests that matter most are the withholding ones -- below threshold,
wrong level, missing category must all yield nothing rather than a number.
"""
from datetime import date

from app import config
from app.models import EventVolatilityRange, MarketMove

AS_OF = date(2026, 8, 5)


def test_event_volatility_range_table_exists(db_session):
    row = EventVolatilityRange(
        level="COMPANY", company_id=1, sector=None, category="pharma",
        n_events=3, min_excess_move_pct=-1.8, median_excess_move_pct=0.6,
        max_excess_move_pct=2.4, as_of=AS_OF, source="market_moves",
    )
    db_session.add(row)
    db_session.commit()
    got = db_session.query(EventVolatilityRange).one()
    assert got.level == "COMPANY"
    assert got.source == "market_moves"


def test_market_move_carries_its_alert_category(db_session):
    """Copied at measurement time -- alerts get recategorized later, and a
    live join would silently re-shuffle historical ranges (same hazard
    calibration_samples.category already documents)."""
    assert hasattr(MarketMove, "category")


def test_thresholds_live_in_config_not_code():
    assert config.EVENT_VOL_COMPANY_MIN_EVENTS == 3
    assert config.EVENT_VOL_SECTOR_MIN_EVENTS == 5
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_event_volatility.py -q`
Expected: FAIL — `ImportError: cannot import name 'EventVolatilityRange'`

- [ ] **Step 3: Implement**

In `backend/app/models.py`, inside `class MarketMove`, directly under the `benchmark_ticker` column:

```python
    # Alert.category copied at measurement time. Alerts can be
    # recategorized after the fact; a live join would silently re-shuffle
    # which range pool historical moves belong to. Same reclassification-
    # safety pattern calibration_samples.category documents. NULL on rows
    # that predate this column (backfill_event_volatility.py fills them).
    category = Column(String, nullable=True)
```

After `class CarOutcome` (keep its closing lines intact), add:

```python
class EventVolatilityRange(Base):
    """One empirical reaction range per (level, subject, news category) --
    subsystem D (docs/superpowers/specs/2026-08-05-event-volatility-ranges-
    design.md). Built nightly by app.market.event_volatility from measured
    market_moves rows only; fully rebuilt each run (an aggregate has no
    identity worth preserving). No LLM ever writes here.

    level=COMPANY rows set company_id (sector NULL); level=SECTOR rows set
    sector (company_id NULL) and pool every measured company in that
    sector. The unique constraint is belt-and-braces -- the full rebuild
    makes duplicates structurally impossible.
    """
    __tablename__ = "event_volatility_ranges"
    __table_args__ = (
        UniqueConstraint(
            "level", "company_id", "sector", "category",
            name="uq_event_vol_level_subject_category",
        ),
    )

    id = Column(Integer, primary_key=True)
    level = Column(String, nullable=False)  # COMPANY | SECTOR
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True)
    sector = Column(String, nullable=True)
    category = Column(String, nullable=False)
    n_events = Column(Integer, nullable=False)
    min_excess_move_pct = Column(Float, nullable=False)
    median_excess_move_pct = Column(Float, nullable=False)
    max_excess_move_pct = Column(Float, nullable=False)
    as_of = Column(Date, nullable=False)
    source = Column(String, nullable=False, default="market_moves")
```

In `backend/app/db.py`, append to `_ADDED_COLUMNS` (new table needs no entries — `create_all` covers it; only the existing-table column does):

```python
    ("market_moves", "category", "VARCHAR"),
```

In `backend/app/config.py`, after `CAR_SUMMARY_SAMPLE_THRESHOLD`:

```python
# -- Event volatility ranges (subsystem D, spec 2026-08-05) --------------
# Minimum measured events before a range is stored/shown at each level.
# Below both: no row, nothing shown -- omit rather than fabricate.
EVENT_VOL_COMPANY_MIN_EVENTS = 3
EVENT_VOL_SECTOR_MIN_EVENTS = 5
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_event_volatility.py -q`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/app/db.py backend/app/config.py backend/tests/test_event_volatility.py
git commit -m "feat: event_volatility_ranges schema + market_moves.category + thresholds"
```

---

### Task 2: Stamp `category` on new MarketMove rows

**Files:**
- Modify: `backend/app/pipeline.py` (~line 385, the loop calling `measure_company_move`)
- Test: `backend/tests/test_pipeline.py` (append one test)

**Interfaces:**
- Consumes: `MarketMove.category` from Task 1.
- Produces: every `market_moves` row created by the pipeline carries `category = alert.category` at creation.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_pipeline.py`. Reuse the file's existing fake-measure pattern (see ~line 111 for the model): monkeypatch `pipeline_module.measure_company_move` to return an "ok" `MarketMove`, run the same persist path the neighboring tests run, then assert. Follow the closest existing test's setup verbatim (alert/article/company fixtures); only the assertion is new:

```python
def test_market_moves_are_stamped_with_the_alert_category(db_session, monkeypatch):
    """Subsystem D reads market_moves.category, never a live join to
    alerts -- an alert recategorized later must not re-shuffle which range
    pool its historical measurements belong to."""
    # ... same monkeypatch + persist scaffolding as the nearest
    # measure-related test in this file ...
    moves = db_session.query(MarketMove).all()
    assert moves, "persist path should have measured at least one company"
    assert all(m.category == alert.category for m in moves)
```

The scaffolding comment is for the implementer's orientation only — the committed test must contain the real scaffolding copied from the neighboring test, not a comment.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_pipeline.py -k stamped -q`
Expected: FAIL — `category` is None

- [ ] **Step 3: Implement**

In `backend/app/pipeline.py`, in the measurement loop (~line 387):

```python
            move = measure_company_move(session, company_obj)
            move.alert_id = alert.id
            # Copied, not joined: alerts get recategorized later and the
            # volatility-range pools must not re-shuffle when they do
            # (spec 2026-08-05 §3.2).
            move.category = alert.category
            session.add(move)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_pipeline.py -q`
Expected: all pass (whole file — the change touches a shared path)

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline.py backend/tests/test_pipeline.py
git commit -m "feat: stamp alert category onto market_moves at measurement time"
```

---

### Task 3: Builder — `app/market/event_volatility.py`

**Files:**
- Create: `backend/app/market/event_volatility.py`
- Test: `backend/tests/test_event_volatility.py` (append)

**Interfaces:**
- Consumes: `EventVolatilityRange`, `MarketMove.category`, `config.EVENT_VOL_*` from Task 1.
- Produces (Tasks 4–6 rely on these exact signatures):
  - `MoveFact` — `dataclass(frozen=True)`: `company_id: int, sector: str | None, category: str, excess_move_pct: float`
  - `collect_move_facts(session) -> list[MoveFact]`
  - `compute_ranges(facts: list[MoveFact]) -> list[dict]` — dicts with keys `level, company_id, sector, category, n_events, min_excess_move_pct, median_excess_move_pct, max_excess_move_pct`
  - `apply_ranges(session, rows: list[dict], as_of: date) -> dict` — returns `{"deleted": int, "inserted": int}`
  - `rebuild(session, as_of: date) -> dict` — collect + compute + apply

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_event_volatility.py`:

```python
from app.market import event_volatility as ev


def _fact(company_id=1, sector="pharma", category="pharma", move=1.0):
    return ev.MoveFact(company_id=company_id, sector=sector,
                       category=category, excess_move_pct=move)


# --- compute_ranges: grouping and thresholds --------------------------------

def test_company_row_needs_three_events():
    facts = [_fact(move=m) for m in (-1.8, 0.6, 2.4)]
    rows = ev.compute_ranges(facts)
    company = [r for r in rows if r["level"] == "COMPANY"]
    assert len(company) == 1
    assert company[0] == {
        "level": "COMPANY", "company_id": 1, "sector": None,
        "category": "pharma", "n_events": 3,
        "min_excess_move_pct": -1.8, "median_excess_move_pct": 0.6,
        "max_excess_move_pct": 2.4,
    }


def test_two_events_earn_no_company_row():
    assert not [r for r in ev.compute_ranges([_fact(), _fact(move=2.0)])
                if r["level"] == "COMPANY"]


def test_sector_pool_needs_five_events_and_includes_company_row_earners():
    """The sector row describes the sector, not 'the leftovers' -- company
    1's three measurements count toward the pharma pool too."""
    facts = [_fact(company_id=1, move=m) for m in (-1.8, 0.6, 2.4)]
    facts += [_fact(company_id=2, move=m) for m in (-4.0, 5.0)]
    rows = ev.compute_ranges(facts)
    sector = [r for r in rows if r["level"] == "SECTOR"]
    assert len(sector) == 1
    assert sector[0]["n_events"] == 5
    assert sector[0]["company_id"] is None
    assert sector[0]["sector"] == "pharma"
    assert sector[0]["min_excess_move_pct"] == -4.0
    assert sector[0]["max_excess_move_pct"] == 5.0
    assert sector[0]["median_excess_move_pct"] == 0.6


def test_four_sector_events_earn_no_sector_row():
    facts = [_fact(company_id=i, move=float(i)) for i in range(1, 5)]
    assert not [r for r in ev.compute_ranges(facts) if r["level"] == "SECTOR"]


def test_other_sector_pools_nothing_but_company_rows_survive():
    """'other' is an absence of classification, not a peer group."""
    facts = [_fact(company_id=1, sector="other", move=m)
             for m in (1.0, 2.0, 3.0, 4.0, 5.0)]
    rows = ev.compute_ranges(facts)
    assert [r["level"] for r in rows] == ["COMPANY"]


def test_none_sector_pools_nothing():
    facts = [_fact(company_id=i, sector=None, move=float(i))
             for i in range(1, 7)]
    assert not [r for r in ev.compute_ranges(facts) if r["level"] == "SECTOR"]


def test_categories_never_mix():
    facts = [_fact(category="pharma", move=m) for m in (1.0, 2.0)]
    facts += [_fact(category="banking", move=m) for m in (3.0, 4.0)]
    assert ev.compute_ranges(facts) == []


def test_signs_are_preserved_not_folded():
    """A category that only ever hurts this stock must show a negative
    range -- the sign structure IS the information."""
    rows = ev.compute_ranges([_fact(move=m) for m in (-4.0, -2.5, -1.0)])
    assert rows[0]["min_excess_move_pct"] == -4.0
    assert rows[0]["max_excess_move_pct"] == -1.0


def test_even_count_median_is_the_midpoint_average():
    facts = [_fact(company_id=i, move=m)
             for i, m in enumerate([1.0, 2.0, 3.0, 10.0], start=1)]
    facts += [_fact(company_id=5, move=4.0)]
    sector = [r for r in ev.compute_ranges(facts) if r["level"] == "SECTOR"][0]
    assert sector["median_excess_move_pct"] == 3.0  # median of 1,2,3,4,10


# --- collect_move_facts: what counts as usable -------------------------------

def _move(db_session, company, category="pharma", excess=1.0, status="ok"):
    move = MarketMove(
        alert_id=1, company_id=company.id, benchmark_ticker="^CNXPHARMA",
        excess_move_pct=excess, category=category, measurement_status=status,
    )
    db_session.add(move)
    db_session.flush()
    return move


def test_collect_facts_excludes_unusable_rows(db_session, make_company):
    company = make_company("CIPLA.NS", sector="pharma")
    _move(db_session, company, excess=1.5)
    _move(db_session, company, status="no_data", excess=None)
    _move(db_session, company, excess=None)          # ok but unmeasured
    _move(db_session, company, category=None)        # pre-backfill row
    facts = ev.collect_move_facts(db_session)
    assert [f.excess_move_pct for f in facts] == [1.5]
    assert facts[0].sector == "pharma"


# --- apply_ranges ------------------------------------------------------------

def test_apply_ranges_full_rebuild_replaces_previous_rows(db_session):
    ev.apply_ranges(db_session, [{
        "level": "COMPANY", "company_id": 1, "sector": None,
        "category": "pharma", "n_events": 3,
        "min_excess_move_pct": -1.0, "median_excess_move_pct": 0.0,
        "max_excess_move_pct": 1.0,
    }], as_of=AS_OF)
    result = ev.apply_ranges(db_session, [{
        "level": "SECTOR", "company_id": None, "sector": "pharma",
        "category": "pharma", "n_events": 6,
        "min_excess_move_pct": -2.0, "median_excess_move_pct": 0.5,
        "max_excess_move_pct": 3.0,
    }], as_of=AS_OF)
    assert result == {"deleted": 1, "inserted": 1}
    rows = db_session.query(EventVolatilityRange).all()
    assert len(rows) == 1 and rows[0].level == "SECTOR"
    assert rows[0].as_of == AS_OF and rows[0].source == "market_moves"


def test_empty_input_never_clobbers_existing_rows(db_session):
    """A dev DB with no measured moves, or a bug upstream, must not blank
    production's ranges."""
    ev.apply_ranges(db_session, [{
        "level": "COMPANY", "company_id": 1, "sector": None,
        "category": "pharma", "n_events": 3,
        "min_excess_move_pct": -1.0, "median_excess_move_pct": 0.0,
        "max_excess_move_pct": 1.0,
    }], as_of=AS_OF)
    result = ev.apply_ranges(db_session, [], as_of=AS_OF)
    assert result == {"deleted": 0, "inserted": 0}
    assert db_session.query(EventVolatilityRange).count() == 1
```

If `tests/conftest.py` has no `make_company` fixture, add a local helper in this file instead (a `Company` with `ticker`, `name`, `sector`, `index_tier="OTHER"`, flushed) — check conftest first and follow whatever company-construction pattern the suite already uses.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_event_volatility.py -q`
Expected: FAIL — `ModuleNotFoundError: app.market.event_volatility`

- [ ] **Step 3: Implement**

Create `backend/app/market/event_volatility.py`:

```python
"""Subsystem D: empirical per-(stock, news-category) reaction ranges
(docs/superpowers/specs/2026-08-05-event-volatility-ranges-design.md).

Built from measured market_moves rows only -- status 'ok', non-null
excess_move_pct, non-null category. No LLM output, no estimates. Where the
data is too thin (below the config thresholds) there is simply no row, and
the UI shows nothing: omit rather than fabricate.

The table is an aggregate with no identity worth preserving, so refresh is
a full delete + reinsert -- except that empty input leaves the previous
rows intact (never clobber good data with nothing).
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from statistics import median

from sqlalchemy.orm import Session

from app import config
from app.models import Company, EventVolatilityRange, MarketMove

SOURCE_NAME = "market_moves"


@dataclass(frozen=True)
class MoveFact:
    company_id: int
    sector: str | None
    category: str
    excess_move_pct: float


def collect_move_facts(session: Session) -> list[MoveFact]:
    """Every usable measurement, with the company's sector AT BUILD TIME --
    a company whose sector was corrected contributes to its current
    sector's pool, not its historical one. Rows with NULL category
    (pre-backfill) are excluded, never joined live to alerts: one source
    of truth per row (spec §3.2)."""
    rows = (
        session.query(MarketMove, Company.sector)
        .join(Company, Company.id == MarketMove.company_id)
        .filter(MarketMove.measurement_status == "ok")
        .filter(MarketMove.excess_move_pct.isnot(None))
        .filter(MarketMove.category.isnot(None))
        .all()
    )
    return [
        MoveFact(
            company_id=move.company_id,
            sector=sector,
            category=move.category,
            excess_move_pct=move.excess_move_pct,
        )
        for move, sector in rows
    ]


def _range_stats(moves: list[float]) -> dict:
    return {
        "n_events": len(moves),
        "min_excess_move_pct": min(moves),
        "median_excess_move_pct": median(moves),
        "max_excess_move_pct": max(moves),
    }


def compute_ranges(facts: list[MoveFact]) -> list[dict]:
    """Pure: facts in, range-row dicts out.

    COMPANY rows need EVENT_VOL_COMPANY_MIN_EVENTS; SECTOR pools need
    EVENT_VOL_SECTOR_MIN_EVENTS and include every company's measurements
    (the sector row describes the sector, not "the leftovers"). sector
    'other' or None pools nothing -- an absence of classification is not a
    peer group."""
    by_company: dict[tuple[int, str], list[float]] = defaultdict(list)
    by_sector: dict[tuple[str, str], list[float]] = defaultdict(list)
    for fact in facts:
        by_company[(fact.company_id, fact.category)].append(fact.excess_move_pct)
        if fact.sector and fact.sector != "other":
            by_sector[(fact.sector, fact.category)].append(fact.excess_move_pct)

    rows: list[dict] = []
    for (company_id, category), moves in sorted(by_company.items()):
        if len(moves) < config.EVENT_VOL_COMPANY_MIN_EVENTS:
            continue
        rows.append({
            "level": "COMPANY", "company_id": company_id, "sector": None,
            "category": category, **_range_stats(moves),
        })
    for (sector, category), moves in sorted(by_sector.items()):
        if len(moves) < config.EVENT_VOL_SECTOR_MIN_EVENTS:
            continue
        rows.append({
            "level": "SECTOR", "company_id": None, "sector": sector,
            "category": category, **_range_stats(moves),
        })
    return rows


def apply_ranges(session: Session, rows: list[dict], as_of: date) -> dict:
    """Full rebuild in one transaction. Empty input writes nothing and
    keeps the previous rows -- a dev DB with no measured moves must not
    blank production's ranges through some future shared code path."""
    if not rows:
        return {"deleted": 0, "inserted": 0}
    deleted = session.query(EventVolatilityRange).delete()
    for row in rows:
        session.add(EventVolatilityRange(as_of=as_of, source=SOURCE_NAME, **row))
    session.commit()
    return {"deleted": deleted, "inserted": len(rows)}


def rebuild(session: Session, as_of: date) -> dict:
    facts = collect_move_facts(session)
    result = apply_ranges(session, compute_ranges(facts), as_of)
    return {"facts": len(facts), **result}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_event_volatility.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add backend/app/market/event_volatility.py backend/tests/test_event_volatility.py
git commit -m "feat: event volatility range builder -- pure, thresholded, rebuild-safe"
```

---

### Task 4: Serving — payload + bulk lookup

**Files:**
- Modify: `backend/app/market/event_volatility.py` (append)
- Test: `backend/tests/test_event_volatility.py` (append)

**Interfaces:**
- Consumes: Task 3 module.
- Produces (Task 5 relies on these):
  - `range_payload(row: EventVolatilityRange) -> dict` — `{"level", "n_events", "min_excess_move_pct", "median_excess_move_pct", "max_excess_move_pct", "as_of"}`, `as_of` ISO string
  - `volatility_range_payload(session, company, category) -> dict | None`
  - `ranges_for_category(session, category) -> tuple[dict[int, EventVolatilityRange], dict[str, EventVolatilityRange]]` — (by company_id, by sector) for bulk callers

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_event_volatility.py`:

```python
def _stored(db_session, level, category="pharma", company_id=None,
            sector=None, n=3):
    row = EventVolatilityRange(
        level=level, company_id=company_id, sector=sector, category=category,
        n_events=n, min_excess_move_pct=-1.8, median_excess_move_pct=0.6,
        max_excess_move_pct=2.4, as_of=AS_OF, source="market_moves",
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_payload_prefers_the_company_row(db_session, make_company):
    company = make_company("CIPLA.NS", sector="pharma")
    _stored(db_session, "COMPANY", company_id=company.id, n=9)
    _stored(db_session, "SECTOR", sector="pharma", n=40)
    payload = ev.volatility_range_payload(db_session, company, "pharma")
    assert payload == {
        "level": "COMPANY", "n_events": 9,
        "min_excess_move_pct": -1.8, "median_excess_move_pct": 0.6,
        "max_excess_move_pct": 2.4, "as_of": "2026-08-05",
    }


def test_payload_falls_back_to_the_sector_pool(db_session, make_company):
    company = make_company("CIPLA.NS", sector="pharma")
    _stored(db_session, "SECTOR", sector="pharma", n=12)
    payload = ev.volatility_range_payload(db_session, company, "pharma")
    assert payload["level"] == "SECTOR" and payload["n_events"] == 12


def test_payload_is_none_below_every_rung(db_session, make_company):
    company = make_company("CIPLA.NS", sector="pharma")
    assert ev.volatility_range_payload(db_session, company, "pharma") is None


def test_payload_is_none_for_a_different_category(db_session, make_company):
    company = make_company("CIPLA.NS", sector="pharma")
    _stored(db_session, "COMPANY", company_id=company.id, category="banking")
    assert ev.volatility_range_payload(db_session, company, "pharma") is None


def test_payload_is_none_without_a_category(db_session, make_company):
    """Directory browsing has no event context -- a range is meaningless
    without an event type."""
    company = make_company("CIPLA.NS", sector="pharma")
    _stored(db_session, "COMPANY", company_id=company.id)
    assert ev.volatility_range_payload(db_session, company, None) is None


def test_bulk_lookup_returns_both_maps(db_session, make_company):
    company = make_company("CIPLA.NS", sector="pharma")
    _stored(db_session, "COMPANY", company_id=company.id)
    _stored(db_session, "SECTOR", sector="pharma", n=8)
    by_company, by_sector = ev.ranges_for_category(db_session, "pharma")
    assert company.id in by_company
    assert by_sector["pharma"].n_events == 8
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_event_volatility.py -k payload -q`
Expected: FAIL — no attribute `volatility_range_payload`

- [ ] **Step 3: Implement**

Append to `backend/app/market/event_volatility.py`:

```python
def range_payload(row: EventVolatilityRange) -> dict:
    """Serialized shape (spec §6). level travels with the numbers so the UI
    can label a pooled range -- a sector range dressed as stock-specific is
    a lie about sample identity."""
    return {
        "level": row.level,
        "n_events": row.n_events,
        "min_excess_move_pct": row.min_excess_move_pct,
        "median_excess_move_pct": row.median_excess_move_pct,
        "max_excess_move_pct": row.max_excess_move_pct,
        "as_of": row.as_of.isoformat(),
    }


def ranges_for_category(
    session: Session, category: str,
) -> tuple[dict[int, EventVolatilityRange], dict[str, EventVolatilityRange]]:
    """All stored rows for one category, keyed for O(1) per-row lookup --
    the card back iterates many companies and must not query per row."""
    rows = (
        session.query(EventVolatilityRange)
        .filter(EventVolatilityRange.category == category)
        .all()
    )
    by_company = {r.company_id: r for r in rows if r.level == "COMPANY"}
    by_sector = {r.sector: r for r in rows if r.level == "SECTOR"}
    return by_company, by_sector


def lookup_range(
    by_company: dict[int, EventVolatilityRange],
    by_sector: dict[str, EventVolatilityRange],
    company: Company,
) -> dict | None:
    """The fallback ladder against pre-fetched maps: COMPANY row, else the
    company's sector pool, else None."""
    row = by_company.get(company.id)
    if row is None and company.sector:
        row = by_sector.get(company.sector)
    return range_payload(row) if row is not None else None


def volatility_range_payload(
    session: Session, company: Company, category: str | None,
) -> dict | None:
    """Single-company convenience over the same ladder. None without a
    category -- a range is meaningless without an event type."""
    if not category:
        return None
    by_company, by_sector = ranges_for_category(session, category)
    return lookup_range(by_company, by_sector, company)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_event_volatility.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add backend/app/market/event_volatility.py backend/tests/test_event_volatility.py
git commit -m "feat: volatility range payload with company->sector fallback ladder"
```

---

### Task 5: Serialize `volatility_range` on card-back rows and deep dive

**Files:**
- Modify: `backend/app/market/ripple_layers.py` (row dict, ~line 156)
- Modify: `backend/app/routers/stock_deep_dive.py` (`_company_facts` ~line 34; alert path ~line 100)
- Test: `backend/tests/test_ripple_layers.py`, `backend/tests/test_stock_deep_dive_router.py` (append)

**Interfaces:**
- Consumes: `ranges_for_category`, `lookup_range`, `volatility_range_payload` from Task 4.
- Produces: every card-back row dict and both deep-dive paths carry a `volatility_range` key (`dict | None`).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_ripple_layers.py`, following its existing alert/company/layer fixtures:

```python
def test_rows_carry_the_volatility_range_for_this_alerts_category(db_session):
    # Arrange an alert + AlertCompany the way this file's other tests do,
    # then store a matching range:
    from app.models import EventVolatilityRange
    from datetime import date
    db_session.add(EventVolatilityRange(
        level="COMPANY", company_id=company.id, sector=None,
        category=alert.category, n_events=4, min_excess_move_pct=-1.8,
        median_excess_move_pct=0.6, max_excess_move_pct=2.4,
        as_of=date(2026, 8, 5), source="market_moves",
    ))
    db_session.commit()
    layers = compute_ripple_layers(db_session, alert, set())
    row = next(r for layer in layers for r in layer["rows"]
               if r["ticker"] == company.ticker)
    assert row["volatility_range"]["level"] == "COMPANY"
    assert row["volatility_range"]["n_events"] == 4


def test_rows_without_stored_ranges_carry_null_not_a_number(db_session):
    layers = compute_ripple_layers(db_session, alert, set())
    for layer in layers:
        for row in layer["rows"]:
            assert row["volatility_range"] is None
```

Append to `backend/tests/test_stock_deep_dive_router.py`, following its existing client/fixture pattern:

```python
def test_no_alert_deep_dive_has_null_volatility_range(...):
    # Directory path: no alert_id -> no category -> null, key present.
    payload = client.get(f"/api/feed-v2/stock/{ticker}").json()
    assert payload["volatility_range"] is None


def test_alert_deep_dive_serves_the_range_for_that_alerts_category(...):
    # Store an EventVolatilityRange for (company, alert.category) as above,
    # then:
    payload = client.get(f"/api/feed-v2/stock/{ticker}?alert_id={alert.id}").json()
    assert payload["volatility_range"]["level"] == "COMPANY"
```

Also update the row-shape assertions: `tests/test_ripple_layers.py` and any card-back shape test listing exact row keys must add `"volatility_range"`. (`tests/test_ripple.py`'s peer-row shape is untouched — sector peers don't carry it; spec §6 names only these two serializers.)

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_ripple_layers.py tests/test_stock_deep_dive_router.py -q`
Expected: new tests FAIL — KeyError `volatility_range`

- [ ] **Step 3: Implement**

`backend/app/market/ripple_layers.py` — import and bulk-load once, before the row loop:

```python
from app.market.event_volatility import lookup_range, ranges_for_category
```

```python
    # One query for the whole card back, not one per row (spec §6).
    vol_by_company, vol_by_sector = ranges_for_category(session, alert.category)
```

In the row dict, after `"fundamentals"`:

```python
            # Empirical reaction range for this news category (subsystem D).
            # None below the sample thresholds -- omit, never fabricate.
            "volatility_range": lookup_range(vol_by_company, vol_by_sector, company),
```

`backend/app/routers/stock_deep_dive.py` — import:

```python
from app.market.event_volatility import volatility_range_payload
```

In `_company_facts`, alongside the other None-in-directory-context keys:

```python
        # Subsystem D: only meaningful within an event context -- populated
        # on the alert path below, never for Directory browsing.
        "volatility_range": None,
```

In the alert path, after `result["rationale"] = ...`:

```python
    result["volatility_range"] = volatility_range_payload(db, company, alert.category)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_ripple_layers.py tests/test_stock_deep_dive_router.py tests/test_ripple.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add backend/app/market/ripple_layers.py backend/app/routers/stock_deep_dive.py backend/tests/test_ripple_layers.py backend/tests/test_stock_deep_dive_router.py
git commit -m "feat: serve volatility_range on card-back rows and alert deep dive"
```

---

### Task 6: Nightly scheduler job + runbook

**Files:**
- Modify: `backend/app/scheduler.py`
- Create: `backend/backfill_event_volatility.py`
- Test: `backend/tests/test_scheduler_universe.py` (append — it already owns the job-registry assertions)

**Interfaces:**
- Consumes: `rebuild(session, as_of)` from Task 3.
- Produces: APScheduler job id `event_volatility_refresh`, interval 24h; runbook script for the initial prod run.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_scheduler_universe.py`:

```python
def test_event_volatility_refresh_is_registered_nightly(monkeypatch):
    monkeypatch.setattr(scheduler.BackgroundScheduler, "start", lambda self: None)
    try:
        scheduler.start_scheduler()
        jobs = {job.id: job for job in scheduler._scheduler.get_jobs()}
        assert "event_volatility_refresh" in jobs
        assert jobs["event_volatility_refresh"].trigger.interval == timedelta(hours=24)
    finally:
        scheduler._scheduler = None


def test_event_volatility_refresh_never_raises_and_does_no_network(monkeypatch):
    """Rebuild reads the DB only. Any urllib call from this job is a bug."""
    import urllib.request

    def explode(*args, **kwargs):
        raise AssertionError("event volatility refresh must not touch the network")

    monkeypatch.setattr(urllib.request, "urlopen", explode)
    scheduler._run_event_volatility_refresh()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_scheduler_universe.py -q`
Expected: FAIL — no job / no attribute

- [ ] **Step 3: Implement**

`backend/app/scheduler.py` — job body near the other universe jobs:

```python
def _run_event_volatility_refresh() -> None:
    """Nightly: rebuild event_volatility_ranges from measured market_moves
    (subsystem D). DB-only -- no network. Coverage widens by itself as the
    app measures more events; nothing manual, ever. Logged, never raises,
    same discipline as every other job."""
    from app.market.event_volatility import rebuild

    session = SessionLocal()
    try:
        result = rebuild(session, date.today())
        logger.info(
            "Event volatility refresh: facts=%s deleted=%s inserted=%s",
            result["facts"], result["deleted"], result["inserted"],
        )
    except Exception:
        logger.exception("Event volatility refresh failed")
    finally:
        session.close()
```

(If the module imports `SessionLocal` lazily elsewhere, follow that file's existing convention.) Registration in `start_scheduler`, next to the universe jobs:

```python
    scheduler.add_job(
        _run_event_volatility_refresh,
        trigger="interval",
        hours=24,
        # DB-only and cheap, but still not at boot -- a crash loop should
        # not be re-aggregating tables.
        next_run_time=datetime.now(timezone.utc) + timedelta(minutes=30),
        id="event_volatility_refresh",
    )
```

Create `backend/backfill_event_volatility.py`:

```python
"""One-time subsystem-D bootstrap + rerunnable rebuild.

    python backfill_event_volatility.py

1. Copies alerts.category into market_moves.category where NULL (historical
   rows predate the column; a recategorized alert's backfilled value is
   today's category -- accepted, spec §3.2).
2. Rebuilds event_volatility_ranges from all usable measurements.

Idempotent; safe to rerun. The nightly scheduler job does step 2 forever
after; this script exists for the initial run and for step 1.
"""
from datetime import date

from sqlalchemy import text

from app.db import SessionLocal, init_db
from app.market.event_volatility import rebuild


def main() -> None:
    init_db()
    session = SessionLocal()
    try:
        stamped = session.execute(text(
            "UPDATE market_moves SET category = ("
            "  SELECT alerts.category FROM alerts"
            "  WHERE alerts.id = market_moves.alert_id"
            ") WHERE category IS NULL AND alert_id IS NOT NULL"
        )).rowcount
        session.commit()
        print(f"backfilled category on {stamped} market_moves rows")

        result = rebuild(session, date.today())
        print(f"rebuild: facts={result['facts']} "
              f"deleted={result['deleted']} inserted={result['inserted']}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_scheduler_universe.py -q`, then locally: `python backfill_event_volatility.py` (dev DB — expect small counts, no error)
Expected: tests pass; script prints counts

- [ ] **Step 5: Commit**

```bash
git add backend/app/scheduler.py backend/backfill_event_volatility.py backend/tests/test_scheduler_universe.py
git commit -m "feat: nightly event-volatility rebuild job + bootstrap runbook"
```

---

### Task 7: Frontend — render the range, labeled by level

**Files:**
- Create: `frontend/src/components/VolatilityRange.tsx`
- Create: `frontend/src/components/VolatilityRange.test.tsx`
- Modify: `frontend/src/v3/api.ts` (LayerRow + StockDeepDive)
- Modify: `frontend/src/v3/Sheets.tsx` (InfoSheetData + both sheet contents), `frontend/src/v3/Shell.tsx` (openInfo)
- Modify: `frontend/src/v3/v3.css`

**Interfaces:**
- Consumes: backend `volatility_range` payload (Task 5 shape).
- Produces: `VolatilityRange` component; `LayerRow.volatility_range`, `StockDeepDive.volatility_range`, `InfoSheetData.volatilityRange` types.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/VolatilityRange.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import VolatilityRange from './VolatilityRange';

const range = {
  level: 'COMPANY' as const,
  n_events: 9,
  min_excess_move_pct: -1.8,
  median_excess_move_pct: 0.6,
  max_excess_move_pct: 2.4,
  as_of: '2026-08-05',
};

describe('VolatilityRange', () => {
  it('renders the measured range with its sample count', () => {
    render(<VolatilityRange range={range} />);
    expect(screen.getByText(/−1\.8%/)).toBeInTheDocument();
    expect(screen.getByText(/\+2\.4%/)).toBeInTheDocument();
    expect(screen.getByText(/9 events/)).toBeInTheDocument();
    expect(screen.queryByText(/sector-level/)).not.toBeInTheDocument();
  });

  it('labels a pooled sector range so it is never read as stock-specific', () => {
    render(<VolatilityRange range={{ ...range, level: 'SECTOR', n_events: 12 }} />);
    expect(screen.getByText(/sector-level/)).toBeInTheDocument();
    expect(screen.getByText(/12 events/)).toBeInTheDocument();
  });

  it('renders nothing without a range', () => {
    const { container } = render(<VolatilityRange range={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/components/VolatilityRange.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: Implement**

`frontend/src/components/VolatilityRange.tsx`:

```tsx
// Empirical reaction range for one news category (subsystem D). The
// backend sends this only when real measured events back it; below the
// sample thresholds the field is null and this renders nothing. A
// SECTOR-level range is pooled across the sector and must say so --
// dressing it as stock-specific would lie about sample identity.
export interface VolatilityRangeData {
  level: 'COMPANY' | 'SECTOR';
  n_events: number;
  min_excess_move_pct: number;
  median_excess_move_pct: number;
  max_excess_move_pct: number;
  as_of: string;
}

const pct = (v: number) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(1)}%`;

export default function VolatilityRange({ range }: { range: VolatilityRangeData | null | undefined }) {
  if (!range) return null;
  return (
    <p className="volrange">
      <span className="vr-label">Typical on this news type</span>
      <span className="vr-nums">
        {pct(range.min_excess_move_pct)} … {pct(range.max_excess_move_pct)}
        {' · '}median {pct(range.median_excess_move_pct)}
      </span>
      <span className="vr-n">
        {range.level === 'SECTOR' ? 'sector-level, ' : ''}
        {range.n_events} events
      </span>
    </p>
  );
}
```

`frontend/src/v3/api.ts` — add to both `LayerRow` and `StockDeepDive`:

```ts
  // Subsystem D: empirical reaction range for this alert's news category.
  // Null below sample thresholds or (deep dive) outside alert context.
  volatility_range: {
    level: 'COMPANY' | 'SECTOR';
    n_events: number;
    min_excess_move_pct: number;
    median_excess_move_pct: number;
    max_excess_move_pct: number;
    as_of: string;
  } | null;
```

`frontend/src/v3/Sheets.tsx`:
- `InfoSheetData` gains `volatilityRange?: VolatilityRangeData | null;` (import the type from the component).
- `InfoSheetContent`: render `<VolatilityRange range={info.volatilityRange} />` directly under the `BusinessDescription` line inside the "What they do" block, and include `info.volatilityRange` in that block's render condition.
- `DeepDiveSheetContent`: render `<VolatilityRange range={data.volatility_range} />` inside the existing `data.excess_move_pct !== null` tiles section, directly under the tiles — actual move above, typical range below, directly comparable. Also render it in the exposure-only branch if the sheet has one; follow the file's structure.

`frontend/src/v3/Shell.tsx` — `openInfo` passes `volatilityRange: row.volatility_range,`.

`frontend/src/v3/v3.css`, after the `.bdesc` block:

```css
/* Subsystem D reaction range: quiet mono line, sample count always
   visible -- the reader judges what n=3 is worth. */
.nf3 .volrange { display: flex; flex-direction: column; gap: 2px; margin: 8px 0 2px; }
.nf3 .volrange .vr-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.07em; color: var(--ink3); }
.nf3 .volrange .vr-nums { font-family: var(--mono); font-size: 13px; color: var(--ink); }
.nf3 .volrange .vr-n { font-size: 10px; color: var(--ink3); font-family: var(--mono); }
```

- [ ] **Step 4: Run to verify pass**

Run: `cd frontend && npx vitest run && npx tsc --noEmit -p tsconfig.json`
Expected: all pass, typecheck clean

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/VolatilityRange.tsx frontend/src/components/VolatilityRange.test.tsx frontend/src/v3/api.ts frontend/src/v3/Sheets.tsx frontend/src/v3/Shell.tsx frontend/src/v3/v3.css
git commit -m "feat: render event volatility range, sector-level pools labeled"
```

---

### Task 8: Full-suite verification

**Files:** none new.

- [ ] **Step 1: Backend suite**

Run: `cd backend && python -m pytest tests/ -q`
Expected: all pass (baseline before this plan: 1,225)

- [ ] **Step 2: Frontend suite + typecheck**

Run: `cd frontend && npx vitest run && npx tsc --noEmit -p tsconfig.json`
Expected: all pass (baseline: 692 + new)

- [ ] **Step 3: Dev end-to-end smoke**

Run: `cd backend && python backfill_event_volatility.py`
Expected: prints backfilled/rebuild counts without error; with dev's 48 moves, likely few or zero rows — that is correct behavior, not failure.

- [ ] **Step 4: Commit any stragglers**

```bash
git status --short   # expect clean
```
