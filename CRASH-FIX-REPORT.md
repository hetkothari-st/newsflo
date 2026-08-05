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
| **`migrate_precision.py::run_migration`** | AlertCompany (sub-floor / demo / template rows) | **No -- NOT fixed.** Deletes low-confidence and demo-pointing `AlertCompany` rows plus their `ALERT_COMPANY_DEPENDENTS`, but never touches the matching `MarketMove(alert_id, company_id)` row. Same bug class as Fix 2, on a script that already ran in production once. Left unfixed per scope ("report what you find even if you do not change it") -- flagging for a follow-up. |
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

## Verification

- Full backend suite: **1154 passed** (baseline ~1150 + 4 new regression
  tests across the three fixes), 0 failed.
- `python apply_taxonomy_repairs.py --dry-run` against the local worktree
  DB: 106 would-fix / 32 catch-all-skipped / 0 ambiguous, all 6 new
  defense entries apply cleanly, no integrity error raised.
- No `git push`, no production DB access, no LLM API calls made.
