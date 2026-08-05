# Event Volatility Ranges (Subsystem D) — Design

**Date:** 2026-08-05
**Status:** Approved by user (chat), pending spec review
**Depends on:** stock universe (shipped 2026-08-04), sourced fundamentals (shipped), `market_moves` measurement pipeline (live since spec v2)

## 1. Goal

For each stock, per news category, store the empirically measured range of
its reaction to that kind of news — "CIPLA on pharma-regulation news:
typically −1.8% to +2.4% (median +0.6%, 9 events)". Computed from real
measured price moves only. No LLM output, no estimates, no borrowed
numbers. Where measured history is insufficient, show nothing.

This is the fourth and final subsystem of the 2026-08-03 reliability
effort: universe (A), nature of business + description (B), cap tiers (C),
volatility range per event (D).

## 2. Definitions

- **The measured quantity is day-0 excess move**: `market_moves.
  excess_move_pct` — the stock's same-day move minus its sector benchmark's
  move. Chosen over raw moves (market noise inflates ranges) and over
  multi-day CAR (`car_outcomes` has 126 rows — too sparse). It is also the
  exact number the app already displays per event, so the range and the
  actual are directly comparable on screen.
- **Event type = `Alert.category`** (`oil_gas`, `banking`, `pharma`, ...).
- **A usable measurement** is a `market_moves` row with
  `measurement_status = 'ok'` and non-null `excess_move_pct`.
- **Range** = min / median / max of the usable measurements in a group.
  Percentile bands (p10–p90) need populations these groups will not have
  for months; min/median/max is honest at n=3. Bullish and bearish events
  of one category are pooled deliberately — the range describes response
  spread, and its sign structure (e.g. −4%…−1% for a category that only
  ever hurts this stock) is itself the information. The COMPANY/SECTOR
  thresholds below gate on the count of DISTINCT news events (alert_ids)
  behind a group, not the count of measurement rows — one broad alert that
  resolves several same-sector companies is one day's cross-sectional
  spread, not one independent observation per company.

## 3. Data model

### 3.1 New table `event_volatility_ranges`

One row per (level, subject, category). Full nightly rebuild — an
aggregate with no identity worth preserving, so no upsert machinery.

| column | type | notes |
|---|---|---|
| `id` | int PK | |
| `level` | str, NOT NULL | `COMPANY` \| `SECTOR` |
| `company_id` | int FK companies, nullable | set on COMPANY rows, NULL on SECTOR rows |
| `sector` | str, nullable | set on SECTOR rows (taxonomy sector key), NULL on COMPANY rows |
| `category` | str, NOT NULL | alert category |
| `n_events` | int, NOT NULL | count of distinct news events (alerts) backing this row; min/median/max span all usable measurements from those events |
| `min_excess_move_pct` | float, NOT NULL | |
| `median_excess_move_pct` | float, NOT NULL | |
| `max_excess_move_pct` | float, NOT NULL | |
| `as_of` | date, NOT NULL | rebuild date |
| `source` | str, NOT NULL | always `market_moves` for now; provenance column per house pattern |

Unique constraint on (`level`, `company_id`, `sector`, `category`).
Migration via `_ADDED_COLUMNS` conventions: new table, so
`Base.metadata.create_all` covers it — no `_ADDED_COLUMNS` entries needed.

### 3.2 New column `market_moves.category`

`Alert.category` copied at measurement time. Alerts can be recategorized
after the fact; `calibration_samples.category` already documents this
exact hazard and this is the same fix. Nullable — historical rows predate
it. `_ADDED_COLUMNS` entry: `("market_moves", "category", "VARCHAR")`.

- **Write site:** `app.market.measure.measure_company_move` (or its caller
  that has the Alert in hand) stamps it on row creation.
- **Backfill:** one-time script copies `alerts.category` into existing
  rows via join. Run in dev and prod. Backfilled rows carry today's
  category, which may differ from the category at measurement time for
  any alert recategorized in the past — accepted, unavoidable, and only
  affects the pre-backfill population.
- **Builder reads `market_moves.category` only.** Rows where it is NULL
  (created between deploy and backfill, or backfill missed) are excluded
  rather than joined live to `alerts` — one source of truth per row.

## 4. Builder — `app/market/event_volatility.py`

Pure computation, session in / rows out. No network.

```python
COMPANY_MIN_EVENTS = config.EVENT_VOL_COMPANY_MIN_EVENTS  # 3
SECTOR_MIN_EVENTS = config.EVENT_VOL_SECTOR_MIN_EVENTS    # 5

def compute_ranges(moves: list[MoveFact]) -> list[RangeRow]:
    # group by (company_id, category) -> COMPANY rows where n >= 3
    # group by (sector, category)     -> SECTOR rows where n >= 5
```

- Input facts: `(company_id, sector, category, excess_move_pct)` for every
  usable measurement. Sector comes from the company row AT BUILD TIME —
  a company whose sector was corrected contributes to its current
  sector's pool, not its historical one.
- SECTOR pools include every usable measurement from companies in that
  sector, including companies that also earn their own COMPANY row. The
  sector row describes the sector, not "the leftovers".
- Companies with `sector = 'other'` contribute no SECTOR rows ('other' is
  an absence of classification, not a peer group) but still earn COMPANY
  rows.
- `apply_ranges(session, rows, as_of)`: delete all + bulk insert, one
  transaction. Empty input (e.g. dev DB with no moves) writes nothing and
  leaves the previous rows intact — never clobber good data with nothing.

## 5. Refresh — scheduler job

`_run_event_volatility_refresh` in `app/scheduler.py`: nightly interval
job, no network, reads `market_moves` + `companies`, rebuilds the table.
Logged counts (`company_rows=… sector_rows=… facts=…`), never raises —
same discipline as every other job. Also exposed as
`backfill_event_volatility.py` runbook for the initial prod run (which
also does the `market_moves.category` backfill first).

## 6. Serving — `volatility_range_payload`

`app/market/event_volatility.py`:

```python
def volatility_range_payload(session, company, category) -> dict | None:
    # COMPANY row for (company, category), else SECTOR row for
    # (company.sector, category), else None.
    # -> {"level": "COMPANY"|"SECTOR", "n_events": int,
    #     "min_excess_move_pct": float, "median_excess_move_pct": float,
    #     "max_excess_move_pct": float, "as_of": iso-date}
```

Wired into the two alert-context serializers, keyed `volatility_range`:

- `app.market.ripple_layers.compute_ripple_layers` rows (card back)
- `app.routers.stock_deep_dive` alert path (deep dive opened from a story)

The no-alert deep-dive path (Directory browsing) has no category, hence no
range — a range is meaningless without an event type. Bulk callers
(ripple_layers iterates many rows) load all ranges for the alert's
category in one query, not per row.

## 7. Frontend (live v3 tree)

One line in the card-back row detail and the deep-dive sheet, rendered
only when `volatility_range` is non-null:

> Typical on this news type: −1.8% … +2.4% · median +0.6% · 9 events

SECTOR-level rows are visibly labeled (`sector-level, 12 events`) — a
pooled range must never be dressed as stock-specific. Styling follows the
existing editorial system (mono numerals, `seclab` label treatment). Types
extend `LayerRow` and `StockDeepDive` in `src/v3/api.ts`.

## 8. Honest limits (accepted)

- Today's data supports COMPANY rows for roughly the 181 companies with
  measured events and SECTOR rows for their sectors — not all 4,814.
  Coverage widens automatically as the app measures more events. Nothing
  manual, ever.
- min/max from n=3 is a coarse range. n is always displayed; the reader
  judges.
- Backfilled categories may not match category-at-measurement for
  historically recategorized alerts (§3.2).

## 9. Non-goals

- No multi-day/CAR ranges (data too sparse; revisit when `car_outcomes`
  has population).
- No baseline (non-event) volatility band — explicitly rejected in
  brainstorming in favor of event-type ranges only.
- No prediction, no distribution fitting, no confidence intervals.
- No global-market (`market='GLOBAL'`) coverage: those companies have no
  sector benchmark in the measurement pipeline.

## 10. Testing

- Builder: grouping, both thresholds, pooled-sector composition,
  'other'-sector exclusion, sign preservation, empty-input no-clobber.
- Payload: COMPANY hit, SECTOR fallback, None below thresholds, None for
  missing category.
- Serializers: `volatility_range` key present in card-back row and
  deep-dive alert path; absent (null) in no-alert path.
- Scheduler: job registered nightly; no network in job body.
- Measurement: new moves get `category` stamped.
