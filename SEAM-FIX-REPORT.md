# Seam-fix report: precision-fix x stock-universe

## Status
All six findings (C1, I1, I2, I3, I4, M1) fixed and tested in the
`precision-verify` worktree. Nothing pushed.

## Commit
See `git log -1` in this worktree after this report is committed
(commit created immediately after this file).

## Backend test summary
`python -m pytest` from `backend/`: **1046 passed** (up from the pre-existing
1038; net +8 new/replaced tests across `test_apply_taxonomy_repairs.py`,
`test_candidates.py`, `test_resolution.py`). No skips, no xfails, no
warnings beyond pre-existing deprecation notices.

`python score_golden.py`: `mean precision 1.00  mean recall 1.00  forbidden
companies present: 0` (alert 9020) -- unchanged, as expected: this harness
scores persisted `alert_companies` rows and cannot see the resolution-level
regression I3 targets. I3 instead added
`tests/test_resolution.py::test_unanchored_fmcg_fanout_excludes_eternal_from_a_realistic_top_3`,
which exercises `resolve_companies` directly.

## Dry-run against the real worktree DB
`python apply_taxonomy_repairs.py --dry-run`:

```
94 would be fixed, 0 reported (ambiguous/unknown, left alone),
32 reported (catch-all sub_sector, left alone).
```

Matches the task's expected split exactly. `ADANIENT.NS` and `TITAN.NS`
(both `*_other`) are now reported as `catchall_skipped` and left in
`sector="other"`. `ETERNAL.NS` is still derived to `sector="fmcg"` --
correctly, since its `sub_sector="retail"` is a real, non-catch-all value
(not part of the C1 bug).

## ETERNAL.NS vs. the unanchored fmcg fan-out -- important finding
Ran the fixed `_apply_explicit_repairs` + `_apply_derived_repairs` against
the real DB in a rolled-back transaction, then queried
`resolve_companies`'s fan-out predicate directly for `sector="fmcg"`:

```
HINDUNILVR.NS  4,946,007,100,000  personal_care
ITC.NS         3,580,922,000,000  staples_food
ETERNAL.NS     3,010,426,900,000  retail          <-- rank #3
```

**ETERNAL.NS is NOT excluded from a truly unanchored fmcg fan-out.** Once
`TITAN.NS`'s incorrect `fmcg_other -> fmcg` sweep is removed (C1) and
`ETERNAL.NS` is legitimately re-sectored to `fmcg` (a genuine derived
repair -- `retail` is not a catch-all), its real market cap (₹3.01T) puts
it ahead of `NESTLEIND.NS` in an unanchored top-3-by-market-cap fan-out.

The only mechanism that keeps it out is **anchoring**
(`anchor_sub_sectors` in `resolve_companies`): when the model names a
specific fmcg company (e.g. HUL, sub_sector `personal_care`), the fan-out
restricts to that sub-sector and `ETERNAL.NS` (`retail`) never qualifies.
This closes the *originally reported* bug (a crude-oil story anchored on
HUL/personal_care reaching ETERNAL.NS) but a genuinely sector-wide,
no-company-named fmcg mention would still surface it. This is not
something C1/I1-I4 as specified fix -- flagging it rather than
silently declaring victory. The I3 regression test therefore uses
constructed (not live) market caps to pin the intended behavior and will
catch drift in `TOP_N_SECTOR_COMPANIES` or the ranking mechanism; it
does not by itself guarantee the live-data outcome above.

## Concerns
1. **ETERNAL.NS's real ₹3.01T market cap** looks anomalously large for
   a food-delivery/quick-commerce company and is what drives the
   unanchored-fan-out finding above -- worth a data-quality look, but out
   of scope here (no market-cap-sourcing files were touched).
2. Per the "not in scope" instruction, `Company.sector` is still reverted
   by the monthly universe refresh (`loader.py`), so the 94 derived
   repairs (and the explicit three) will need re-running on that cadence
   until a human decides the loader's own classification story.
3. `FINAL-REVIEW.diff` and `TASK16-FINISH-REPORT.md` were already present
   as untracked files in this worktree before this session started; left
   untouched and not committed (unrelated to this task).
