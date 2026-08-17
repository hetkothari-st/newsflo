# DATA GAPS — Phase 0 gate inputs and the historical backfill

Part of [`DATA_GAPS.md`](../DATA_GAPS.md), which is now an index over this
directory. **Section numbers are repo-wide and unchanged** — prose, code
comments and tests that cite "§7" or "DATA_GAPS section 11" still mean the
section of that number, wherever it now lives.

---

## 3. Phase 0 gate inputs that do not exist yet — OPEN

Phase 0 built the publication gate's full §7.4 structure
(`backend/config/gates.yaml` + `backend/app/core/gates.py`), but four of its
inputs have no source in this repo. **None of them is defaulted to a
plausible value.** Each arrives at the gate as `None` ("not known"), and
`config/gates.yaml` states explicitly, per tier, what an unknown means —
fail-closed for `PRIMARY`, permissive for `SECONDARY_RIPPLE`.

| Input | Gate rule | Today | Supplied by |
|---|---|---|---|
| `empirical_status` | PRIMARY requires `AGREE` or `NO_DATA` | the V4 adapter emits the literal truth, `NO_DATA` — there is no empirical calibration table | Phase 5 |
| `adv_20d_inr` (liquidity) | `min_adv_inr` | `min_adv_inr: null`, so the rule is not evaluated at all — **see §12, this is a PRIMARY cutover blocker, not a background gap** | repo owner (liquidity feed) |
| `shock_magnitude_confidence` | `< 0.5` ⇒ macro-only ⇒ company REJECTED | never supplied; unknown does not block | Phase 2 (sensitivity engine) |
| `exposure_stale` | any STALE exposure ⇒ REJECTED | hard-coded `False` **because no exposure ledger exists** — nothing can be stale | Phase 1 |

**Owner:** the V5 phases themselves, not the repo owner. Listed here so the
gate is never read as "fully evaluated" today.

## 4. Historical `alert_companies` → `company_impact` backfill — OPEN

`backend/scripts/backfill_company_impact.py` is **committed and has not been
run** against any database. Two ambiguities are deliberately unresolved:

* legacy rows predate `alerts.content_key`, so they have **no
  `analysis_version`** — the script skips them rather than invent an
  identity;
* the V4 discovery vocabulary values `EXPOSURE_RULE`, `RIPPLE_DISCOVERY`,
  `ESCALATION`, `COMPLETENESS`, `CURATED` have **no V5 twin that is not a
  guess** — those rows get `discovery_source = NULL` and
  `needs_reanalysis = 1`.

**Owner:** repo owner, whenever the historical corpus is wanted in canonical
form. Running it is a deliberate act; nothing schedules it.
