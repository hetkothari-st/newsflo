# Crash Fix Report

**Status:** All three fixes implemented, tested, committed.

## Fix 1 — `app/market/alert_measurement.py:109` (production crash)

`compute_alert_measurement` now returns `None` when the peak `MarketMove`'s
`company_id` has no matching `AlertCompany` on the alert -- same degrade
path as "no moves at all" (the existing `not moves: return None` case just
above). No more bare `next()` / `StopIteration`.

## Fix 2 — `reanalyze_cascade.py` orphaning `MarketMove`

Added `session.query(MarketMove).filter_by(alert_id=alert.id).delete(...)`
alongside the existing `AlertCompany` delete. The script never re-measures
(never calls `measure_company_move`), so a reanalyzed alert now correctly
has zero `MarketMove` rows until a separate measurement pass runs -- omit
rather than leave stale/orphaned data.

**Wider audit of every `AlertCompany`/`Alert`-deleting site** (grepped all
`.delete(`/`session.delete(` calls in the repo):

| Site | Deletes | MarketMove handled? |
|---|---|---|
| `app/companies/integrity.py::delete_demo_companies` | Company (+ AlertCompany via company_id) | Yes -- explicitly deletes `MarketMove` by `company_id` |
| `reanalyze_cascade.py::reanalyze_alert` | AlertCompany (by alert) | **Fixed here** |
| `cleanup_orphan_company_refs.py` | orphaned AlertCompany | Yes -- explicitly deletes `orphan_market_moves` too |
| `seed_car_review_demo.py` | Alert + AlertCompany | Yes -- deletes `MarketMove` by `alert_id` first |
| `seed_feed_v2_demo.py` | Alert + AlertCompany | Yes -- deletes `MarketMove` by `alert_id` first |
| `migrate_precision.py::run_migration` | AlertCompany (sub-floor / demo / template rows) | **Fixed (see Fix 4 below).** |
| `backfill_universe.py` (`phantom` company merge) | Company (phantom) | Out of scope -- this reassigns `company_id` columns (including `market_moves.company_id`) to the canonical company before deleting the phantom row; not an Alert/AlertCompany deletion path. |

`app/pipeline.py` (`_persist_alert`) is the sole creator of `MarketMove`
rows per alert, confirmed via `measure_company_move` call site at
`app/pipeline.py:387`.

## Fix 3 — Indian defence companies unfindable

Added to `apply_taxonomy_repairs.py`'s `TAXONOMY_REPAIRS`:

| Ticker | sector | sub_sector |
|---|---|---|
| HAL.NS | defense | defense_platforms |
| BEL.NS | defense | defense_electronics |
| MAZDOCK.NS | defense | shipyard |
| GRSE.NS | defense | shipyard |
| BDL.NS | defense | defense_platforms |
| DATAPATTNS.NS | defense | defense_electronics |

All six sub_sectors are unambiguous fits against
`SUB_SECTOR_TAXONOMY["defense"]` (platforms/electronics/shipyard
definitions) -- no guessing. `--dry-run` against the local worktree DB
confirms all 6 apply cleanly and the post-repair integrity guard
(`_assert_no_new_violations`) passes with no new violations.

Docstring note added: these repairs are reverted by the monthly universe
refresh (`loader.py`'s `_CLASSIFICATION_FIELDS` includes `"sector"`) --
re-running is required until that ownership question is resolved
separately.

## Fix 4 — `migrate_precision.py::run_migration` orphaning `MarketMove` (follow-up, not yet run against production)

Reported in Fix 2's audit as an unfixed landmine: `run_migration` deletes
~270 sub-floor `AlertCompany` rows in production (plus demo-pointing rows)
and their `ALERT_COMPANY_DEPENDENTS`, but never touched the matching
`MarketMove(alert_id, company_id)` row -- same bug class as Fix 2, on a
script scheduled to run against production and not yet run there.

Fixed by computing, for every `(alert_id, company_id)` pair about to lose
its last `AlertCompany` row, whether any OTHER (kept) `AlertCompany` row on
the same alert still points at that same `company_id` -- `AlertCompany`
has no unique constraint on `(alert_id, company_id)`, so a naive
per-deleted-row delete could remove a `MarketMove` a surviving row still
needs. Only pairs with no surviving `AlertCompany` lose their `MarketMove`.
Test added (`test_migrate_precision.py`): two `AlertCompany` rows on the
same alert, one below-floor (deleted) and one above it (kept), each with
its own `MarketMove` -- asserts the deleted row's `MarketMove` is gone and
the kept row's is untouched (the over-broad-delete trap).

Also extended `cleanup_orphan_company_refs.py` with **case 3**: `MarketMove`
rows whose company still exists but whose `(alert_id, company_id)` pair has
no surviving `AlertCompany` -- the exact residue either bug (this one or
Fix 2's) leaves behind. Refactored `main()` into a testable
`run_cleanup(session, dry_run)`, mirroring `migrate_precision.py`'s
`run_migration` shape; 5 new tests in
`tests/test_cleanup_orphan_company_refs.py` (detect+delete, leaves a
healthy row alone, doesn't double-count a case-1 orphan, dry-run writes
nothing, idempotent second run finds zero).

**Local dev DB orphan count: 17** `MarketMove` rows found by case 3 (`--dry-run`)
-- residue from the migration having already been run once against this
worktree's local DB. Cleaned up by running the script for real (local DB
only); a second `--dry-run` pass now reports 0 for all three cases.

## Verification

- Full backend suite: **1161 passed** (Fix 1-3 baseline 1154 + 7 new
  regression tests for Fix 4), 0 failed.
- `python apply_taxonomy_repairs.py --dry-run` against the local worktree
  DB: 106 would-fix / 32 catch-all-skipped / 0 ambiguous, all 6 new
  defense entries apply cleanly, no integrity error raised.
- `python cleanup_orphan_company_refs.py --dry-run` then a real run
  against the local worktree DB: found and removed 17 case-3 orphans;
  re-run confirms 0 remaining across all three cases.
- No `git push`, no production DB access, no LLM API calls made.
