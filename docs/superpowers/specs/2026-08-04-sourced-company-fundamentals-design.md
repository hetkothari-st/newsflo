# Sourced Company Fundamentals (Subsystem B) — Design

**Date:** 2026-08-04
**Status:** Approved (design), pending implementation plan
**Scope:** Subsystem B from the 2026-08-03 decomposition — "nature of business and a
brief description for every stock", rebuilt on sourced data.
**Depends on:** `2026-08-03-stock-universe-cap-tiers-design.md`, shipped and migrated
to production 2026-08-04.

## 1. Problem

The user's requirement was a trustworthy description of what each company does, with
"no bogus, hallucinated data". Half of that shipped with subsystem A: 4,669 companies
now carry BSE's official 4-level SEBI classification, sourced and provenance-stamped.

The other half did not. Measured in production on 2026-08-04:

| Field | Coverage of 5,314 | Source |
|---|---|---|
| `official_sector` / `official_isubgroup` | 4,669 | BSE, sourced |
| `business_desc` — plain-English "what they do" | **174** | LLM-generated |
| `sub_sector` | 824 | LLM-classified |
| `supply_chain_*_json` | 174 | LLM-generated |

Three defects follow:

1. **The prose is invented.** `business_desc` is written by an LLM with no source
   document. It is displayed on the company panel as fact.
2. **It is actively spreading.** `app/scheduler.py:248` runs
   `_run_business_profile_refresh` every 6 hours over every company with a NULL
   `business_desc`. Before subsystem A that was ~840 companies; it is now ~5,140. Left
   running, the scheduler will generate roughly five thousand fabricated business
   descriptions on a timer.
3. **`sub_sector` is unsourced and under-covered** at 824 of 5,314, while BSE's
   `ISubGroup` expresses the same intent for 4,669.

### 1.1 Why there is no free-text source

Investigated 2026-08-04 before choosing an approach:

- **BSE exposes no description endpoint.** `CompanyProfile` and `AboutCompany` do not
  exist; `CompanyMaster` returns HTML. The `COName` and `COdetails` fields in the
  `ComHeadernew` payload we already fetch are empty strings.
- **Wikidata holds an ISIN for 93 Indian companies** — 2% of the universe. The join
  would be exact where it exists, but it barely exists.
- NSE's company API returns 403 without a browser cookie flow.

There is no authoritative, free, machine-readable source of plain-English business
descriptions at ~5,300-company scale. Any such text would be scraped-and-unverifiable
or model-invented. Both are the thing this project rejects.

### 1.2 What the investigation did find

The `ComHeadernew` payload we **already fetch monthly and already discard** carries
exchange-published fundamentals per company: `EPS`, `CEPS`, `PE`, `PB`, `OPM`, `NPM`,
`ROE`, plus consolidated variants. The pipeline reads four classification fields from
that payload and throws the rest away.

So the answer to "what does this company do" becomes sourced facts rather than prose,
and it costs **no new network requests**.

## 2. Goals / Non-goals

**Goals**

- Replace invented prose with exchange-published fact on the company panel.
- Stop the scheduler fabricating descriptions at scale.
- Raise `sub_sector` from 824 unsourced to ~4,669 sourced.
- Every displayed number traceable to BSE with an as-of date.

**Non-goals**

- Subsystem D (per-event volatility). Separate spec.
- Any free-text business description. Explicitly rejected — see §1.1.
- Deleting existing LLM data. It stops being read; it stays on disk.
- Historical financials. Current values only — see §5.

## 3. Decisions

| Decision | Choice | Rationale |
|---|---|---|
| What "description" means | Sourced facts only, no free text | No trustworthy free-text source exists at this scale (§1.1) |
| Existing LLM fields | Stop reading, leave data in place | Reversible; no destructive migration |
| `sub_sector` | Derive from official `ISubGroup` | 824 → ~4,669, all sourced, same pattern as `sector` |
| Price-derived ratios (PE, PB) | Store and display all, stamped with `as_of` | User decision. See §5.1 for the accepted risk |
| Storage | Flat columns on `companies` | Matches the existing provenance pattern; no join on read; YAGNI on history |
| Fetching | None added | The payload is already fetched monthly and discarded |

## 4. Architecture

No new modules. This extends the pipeline shipped in subsystem A, because the data
already flows through it.

```
bse_detail/<scrip>.json   (already on disk, already refreshed monthly)
        │
        ├─ Sector/IndustryNew/IGroup/ISubGroup → official_* columns      [shipped]
        ├─ ISubGroup                           → sub_sector              [NEW]
        └─ EPS/CEPS/PE/PB/OPM/NPM/ROE + Con*   → 14 ratio columns        [NEW]
```

Touched: `app/companies/universe/normalize.py` (extract ratios),
`app/companies/universe/loader.py` (persist them), and a new
`app/companies/universe/sub_sector_map.py` beside the existing `sector_map.py`.

## 5. Schema

Sixteen nullable columns on `companies`, all registered in `_ADDED_COLUMNS`
(there is no Alembic — see `app/db.py`):

| Column | Source field |
|---|---|
| `eps`, `ceps`, `pe`, `pb`, `opm`, `npm`, `roe` | `EPS`, `CEPS`, `PE`, `PB`, `OPM`, `NPM`, `ROE` |
| `con_eps`, `con_ceps`, `con_pe`, `con_pb`, `con_opm`, `con_npm`, `con_roe` | `ConEPS`, `ConCEPS`, `ConPE`, `ConPB`, `ConOPM`, `ConNPM`, `ConROE` |
| `financials_source` | `'BSE'` |
| `financials_as_of` | snapshot date |

**Never clobber.** A refresh whose payload lacks ratios leaves stored values intact,
exactly as classification does. A missing ratio is `NULL`, never `0` — a displayed
`0.00` ROE reads as a real and alarming number rather than as absent data. Confirmed
against the live payload: Reliance returns `ConPB: None` and `ConROE: None`, so
consolidated coverage is genuinely patchy.

### 5.1 Accepted risk on PE and PB

`EPS`, `CEPS`, `OPM`, `NPM` and `ROE` change at quarterly results. `PE` and `PB` are
price-derived and drift daily, while this payload refreshes monthly.

The chosen design stores and displays all seven with a visible `as_of` date, rather
than computing the price-derived pair live. The accepted consequence, recorded so it
is not rediscovered as a bug: **after a sharp price move a displayed PE can be wrong,
not merely stale.** The `as_of` date is the mitigation. If this proves misleading in
use, the upgrade path is to compute PE and PB on read from stored EPS/book value
against the live price the app already holds — the stored columns remain valid inputs
for that, so nothing here has to be undone.

## 6. sub_sector derivation

`sub_sector_map.py` maps BSE `ISubGroup` values to `(sector, sub_sector)` pairs drawn
from the existing closed vocabulary in `app.companies.sub_sectors`.

Sizes, measured from the 4,684 fetched detail files and the live taxonomy:

- **190** distinct `ISubGroup` values in the real data
- **72** sub-sector values across **17** sectors in the app's closed vocabulary

The mapping is many-to-one and hand-written, like `sector_map.py` before it, at eight
times the size. Unmapped values yield `NULL`, never a guess.

**The pair matters.** The app's sub-sector vocabulary is scoped per sector, so a
derived `sub_sector` must belong to the company's derived `sector`. Where an
`ISubGroup` implies a sector different from the one derived from `official_sector`,
the sector wins and `sub_sector` is left `NULL` — a contradiction is reported, not
resolved by guessing. A test asserts no company holds a `sub_sector` outside its
sector's list.

Coverage: 824 → ~4,669, all sourced.

### 6.1 What happens to the 824 existing LLM values

Not symmetric with `business_desc`, so stated explicitly. Where an official mapping
exists the derived value **overwrites** the LLM one — that is the point of the change.
Where no official mapping exists, the existing LLM value is **left in place**, matching
the "stop reading, leave data" decision and avoiding a destructive write.

That leaves `sub_sector` holding a mix of sourced and legacy values, so it needs a way
to tell them apart. It does not need a new column: `sub_sector` is derived from
`official_isubgroup`, so **`classification_source` is its provenance too**. A company
with `classification_source = 'BSE'` has a sourced `sub_sector`; one with
`classification_source IS NULL` and a non-null `sub_sector` is holding a legacy LLM
value. This is documented on the model so the next reader does not have to infer it.

**This changes live behaviour.** `sub_sector` feeds the ripple-layer sectioning (a
user-locked feature) and the sub-sector anchoring on the unmerged `precision-fix`
branch. More companies receiving a correct sub_sector changes which ones surface. That
is an improvement, but a visible one, and it needs its own tests.

## 7. API surface

Four serializers emit `business_desc` today: `app/market/ripple.py:65`,
`app/market/ripple_layers.py:139`, `app/routers/alerts.py:188`,
`app/routers/stock_deep_dive.py:38`.

Each gains a `fundamentals` object:

```json
"fundamentals": {
  "classification": {
    "sector": "Energy",
    "industry": "Oil, Gas & Consumable Fuels",
    "group": "Petroleum Products",
    "sub_group": "Refineries & Marketing"
  },
  "ratios":       { "eps": 28.98, "ceps": 41.67, "pe": 44.95, "pb": 3.36,
                    "opm": 14.24, "npm": 7.99, "roe": 7.48 },
  "consolidated": { "eps": 65.15, "ceps": 108.71, "pe": 19.99, "opm": 0.0, "npm": 0.0 },
  "source": "BSE",
  "as_of": "2026-08-04"
}
```

`business_desc` remains in the response and always serialises `null`. That keeps the
change non-breaking, removes the need for a coordinated frontend deploy, and is
honest: the app no longer claims to know what these companies do in prose.

Ratios that are `NULL` are omitted from the object rather than emitted as `0`.

The three cases, stated explicitly because they are not symmetric:

| Company state | `fundamentals` |
|---|---|
| classification + ratios | full object |
| classification, no ratios | object with `classification` and `as_of`; `ratios` and `consolidated` omitted entirely |
| no classification (~645: the 500 global rows and NSE-only names) | `null` |

An empty `ratios: {}` is never emitted — the key is absent when there is nothing to
put in it, so a client cannot mistake "no data" for "all zeroes".

## 8. Retiring the LLM path

Three things stop. Nothing is deleted.

1. **`_run_business_profile_refresh` is removed from the scheduler**
   (`app/scheduler.py:248-262`). This is the most urgent item in the spec: the job
   selects every company with a NULL `business_desc` and asks an LLM to invent one, on
   a 6-hourly timer. Subsystem A took that population from ~840 to ~5,140.
2. `backfill_business_profiles.py` is retired.
3. `app/companies/business_profile.py` stays on disk, unreferenced, so the work is
   recoverable.

The 174 existing descriptions and 174 supply-chain rows stay in the database, unread.

## 9. Frontend

`InsightCard.tsx` and `RippleSection.tsx` render `business_desc` today. Both switch to
`fundamentals`: the classification path as a breadcrumb, the ratios as a compact row,
with the `as_of` date visible. **The date is not decoration** — under §5.1 it is the
only thing that makes a month-old PE honest, so it is a required element, not a
styling choice.

Where `fundamentals` is `null`, the panel renders nothing rather than an empty shell.

`AlertDetailPanel.test.tsx`, `RippleSection.test.tsx`, `InsightCard.test.tsx` and
`lib/api.ts` all reference `business_desc` and need updating.

## 10. Error handling

Follows the discipline established in subsystem A:

- An absent ratio is `NULL`, never `0`.
- A refresh with no ratio payload never clobbers stored values.
- An unmapped `ISubGroup` yields `NULL`, never a guess.
- A malformed ratio (non-numeric, infinite) is rejected by the same `_parse_float`
  guard that already rejects `inf` for market cap.

## 11. Testing

- Ratio extraction from a committed fixture payload, including the real `ConPB: None`
  and `ConROE: None` case.
- The never-clobber guard: a second load with no ratios leaves stored values intact.
- Every one of the 190 `ISubGroup` mappings resolves to a valid `(sector, sub_sector)`
  pair within the closed vocabulary.
- No company ends with a `sub_sector` outside its sector's list.
- API emits `business_desc: null` and a populated `fundamentals`, with NULL ratios
  omitted rather than zeroed.
- The scheduler no longer registers `_run_business_profile_refresh` — asserted on
  `scheduler.get_jobs()`, not on source text (a prior review found a source-text
  assertion hid a real scheduler defect for twenty tasks).

## 12. Open risks

| Risk | Mitigation |
|---|---|
| A displayed PE can be wrong after a sharp move | Accepted, §5.1. `as_of` visible; upgrade path recorded |
| 190 hand-written mappings may contain errors | Every mapping validated against the closed vocabulary by test; unmapped is NULL, not a guess |
| `sub_sector` changes ripple sectioning | Tests for the user-locked sectioning; flagged for review before merge |
| Collides with `precision-fix`'s sub-sector anchoring | That branch is unmerged and already conflicts with the deployed perf PR; sequencing is a merge-time decision |
| Consolidated ratios are patchy | Expected; NULL is displayed as absent, never as zero |
