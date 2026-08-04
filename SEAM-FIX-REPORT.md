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

## Concerns (as of the first commit)
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

---

## Follow-up: require an anchor for the sector-wide fan-out (second commit)

The coordinator verified the unanchored-fmcg finding above independently
(measured on the worktree DB: `fmcg` has 408 rows, only 78 (19%) carry a
`sub_sector`, so an anchor cannot form 81% of the time; confirmed
ETERNAL.NS's ₹3.01T is Eternal/Zomato's real size, not a data-quality
bug) and made the call: the plan's own "falls back to the whole sector
when unanchored" design was wrong, not this branch's earlier work. Fixed
per instruction.

### Change
`app/companies/resolution.py::resolve_companies` -- when a sector-wide
(`is_direct=False`) mention has no entry in `anchor_sub_sectors`, the
fan-out for that mention now returns **nothing** instead of falling back
to a blind top-`TOP_N_SECTOR_COMPANIES`-by-market-cap selection over the
whole sector. Rationale recorded in-line at the call site: the fan-out is
an *exposure* tier whose only justification is "the named company's
mechanism reaches structurally similar companies" -- without an anchor
establishing which part of the sector the mechanism reaches, picking the
largest names asserts an exposure nobody established. Also corrected the
`anchor_sub_sectors` docstring, which previously documented the (now
removed) fallback as intended behaviour.

### Tests updated
- `tests/test_resolution.py::test_fanout_without_an_anchor_falls_back_to_the_whole_sector`
  renamed to `test_fanout_without_an_anchor_resolves_to_nothing_not_the_whole_sector`
  and inverted to assert `resolved == []` -- a deliberate behaviour change,
  documented in the test's own docstring as "do NOT restore the fallback
  here" so it isn't mistaken for a regression by a future reader.
- `test_unanchored_fmcg_fanout_excludes_eternal_from_a_realistic_top_3`
  (added in the first commit) replaced with
  `test_unanchored_fmcg_fanout_returns_nothing_regardless_of_eternal_market_cap`,
  which asserts `resolved == []` for an unanchored fmcg mention even
  though ETERNAL.NS is seeded with the largest market cap in the set --
  this is the real case, not a synthetic ranking scenario. A companion
  `test_anchored_fmcg_fanout_still_excludes_eternal_when_anchor_points_elsewhere`
  keeps the anchored path (the one that closes the originally-reported
  bug) covered on its own merits.
- Ten more existing tests in `test_resolution.py` that exercised
  sector-wide fan-out without an anchor (ordering, dedup, indirect-level
  chaining, tradeability/global exclusion, rationale-stripping) were given
  an explicit `sub_sector` + matching `anchor_sub_sectors` so they keep
  testing what they always tested, rather than silently returning `[]`
  post-fix. `test_pipeline.py::test_sector_inference_fan_out_copies_confidence_and_horizon_to_every_row`
  similarly gained a direct-mention "ANCHOR.NS" company so
  `app.pipeline.build_anchor_sub_sectors` has something to anchor on
  end-to-end; row count assertion updated 2 -> 3 (1 direct + 2 fan-out).

### Full backend suite
`python -m pytest`: **1047 passed** (up from 1046 after the first commit;
net +1 -- one fallback test renamed/inverted in place, one I3 test
replaced in place, one companion anchored test added).

`python score_golden.py`: unchanged, `mean precision 1.00  mean recall
1.00  forbidden companies present: 0`.

### Unanchored-fmcg query on the real worktree DB, after this change
Ran the fixed repair passes (rolled back) then called `resolve_companies`
directly against the real DB:

```
Unanchored fmcg fan-out rows: 0
Anchored (personal_care) fmcg fan-out: ['HINDUNILVR.NS', 'MARICO.NS', 'GODREJCP.NS']
```

`ETERNAL.NS` cannot appear in the unanchored case because nothing can --
the fan-out now returns zero rows whenever no anchor exists, closing the
gap flagged after the first commit. The anchored path (a real company like
HUL named directly) still correctly restricts to `personal_care` and
excludes `ETERNAL.NS` (`retail`) on sub-sector merits, independent of
market cap.

### Concerns after this change
1. This makes the sector-wide fan-out tier legitimately absent on most
   alerts for sectors with low `sub_sector` coverage (fmcg: 19%) --
   expected and intended per the coordinator's rationale, but worth the
   product team knowing the exposure tier will now often be empty rather
   than "less targeted." `score_golden.py`'s single golden alert (9020)
   doesn't exercise this path either way, so it can't confirm the change
   didn't regress a *different* alert's expected fan-out; only the new
   unit-level tests cover it.
2. Everything else from the first commit's concerns still applies
   unchanged (ETERNAL.NS's market cap, the monthly loader reverting
   `Company.sector`, the pre-existing untracked review files).
