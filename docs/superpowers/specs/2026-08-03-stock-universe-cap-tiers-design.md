# Full NSE + BSE Stock Universe with Authentic Cap Tiers — Design

**Date:** 2026-08-03
**Status:** Approved (design), pending implementation plan
**Scope:** Subsystems A (universe/identity) + C (cap tiers), plus the entity-resolution
rebuild that A makes mandatory.

## 1. Problem

`companies` holds 1,016 rows: 509 Indian (`.NS`) and 507 curated global large caps.
The Indian half is exactly NIFTY 500 plus a handful of extras — it covers 100% of
NIFTY 500 but only 67% of NIFTY Total Market 750 and 21% of the NSE main board.
Nothing from BSE-only listings exists at all.

Measured against live exchange masters on 2026-08-03:

| Fact | Value |
|---|---|
| NSE main board (`EQUITY_L.csv`) | 2,409 rows, ISIN on 100% |
| BSE active equity (`ListofScripData`) | 5,091 rows, ISIN on 5,089 |
| Dual-listed (same ISIN, both exchanges) | 2,278 |
| NSE-only | 131 |
| BSE-only | 2,811 |
| Union by ISIN | 5,220, of which 253 are `INF*` mutual-fund/ETF units |
| **Real company universe** | **~4,967** |
| Currently in DB | 509 Indian |

Four defects follow from this:

1. **Coverage.** ~4,458 listed Indian companies have no row, so news about them
   resolves to nothing.
2. **Identity.** `ticker` is the unique key and doubles as the yfinance handle.
   2,278 companies are listed on both exchanges; a ticker-keyed ingest duplicates
   46% of the universe and splits their news history across two rows.
3. **Unsourced classification.** `sector` comes from keyword-matching an industry
   string (`app/companies/loader.py:16`). The module's own comment documents Coal
   India being mis-bucketed into `oil_gas` by this method. `business_desc` and
   `sub_sector` are LLM-generated with no external source.
4. **Starved cap tiers.** `app/market/cap_tier.py` implements AMFI-style rank
   cutoffs correctly, but ranks over the 42 companies that have a non-null
   `market_cap` (of 1,016). Displayed tiers are currently close to meaningless.

## 2. Goals / Non-goals

**Goals**

- Every company listed on NSE or BSE present exactly once, keyed by ISIN.
- Business classification from an official exchange source, not keyword guessing
  or an LLM.
- LARGE/MID/SMALL/MICRO derived from exchange-published market caps, and from
  AMFI's published categorisation where available.
- Every externally-sourced fact carries its source and as-of date; stale facts are
  withheld, not presented as current.
- Entity resolution that does not degrade when the candidate pool grows 10×.

**Non-goals (deferred to their own specs)**

- Subsystem B: replacing LLM-generated `business_desc` / `sub_sector` with sourced
  data. The official 4-level classification this spec stores is the input that
  makes B tractable later.
- Subsystem D: per-company × per-event-type volatility profiles.
- Anything touching the frontend beyond what the API shape forces.

## 3. Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Universe boundary | All ~4,967 active equity ISINs, incl. SME and surveillance groups, each flagged | User requirement is total coverage; flags let resolution rank without excluding |
| Identity | `companies` keyed by ISIN + new `listings` table | 2,278 dual-listed companies; per-listing facts (NSE series vs BSE group) cannot be flattened into one row without lying |
| `companies.id` | Unchanged integer PK | 881 `alert_companies` rows plus watchlists, holdings, market_moves, car_outcomes, calibration_samples all FK to it |
| Taxonomy | Store BSE's official 4 levels verbatim; derive existing 12-value `sector` via explicit mapping | Keeps every downstream consumer working while making the underlying classification auditable |
| Provenance | `source` + `as_of` columns on sourced facts, with staleness thresholds | "Authentic data" is unverifiable without recording origin |
| Globals | Same table, `market` column, no cap tier | AMFI ranking is India-only; a global cap scale would be invented |
| `index_tier` | Unchanged; new rows get `OTHER` | Its ranking role is taken over by market cap, so its collapse into mostly-`OTHER` stops mattering |
| Matcher | Full rebuild in this spec | Substring matching over 5,000 names silently loses matches and produces mismatches |
| Pipeline | Two-stage: snapshot files → deterministic loader | Offline-testable, replayable, resumable; provenance falls out of the snapshot date |

## 4. Architecture

New package `app/companies/universe/`, one job per module, one-way dependencies:

```
fetchers.py   network only   → writes raw snapshots, never touches the DB
snapshot.py   disk layout    → paths, resume state, latest-snapshot lookup
normalize.py  pure functions → raw dicts → canonical records (no I/O, no DB)
loader.py     DB only        → upserts canonical records by ISIN
```

`normalize.py` imports nothing from `app.models` and performs no I/O. It holds the
non-trivial logic — exchange merging, tier mapping, tradeability derivation — and is
testable with plain dicts.

### Data flow

```
NSE EQUITY_L.csv     ─┐
BSE ListofScripData  ─┤→ data/universe/<YYYY-MM-DD>/ → normalize → upsert companies (by ISIN)
BSE ComHeadernew ×N  ─┤                                          → upsert listings
AMFI categorisation  ─┘                                          → upsert company_aliases
```

Stage 1 is resumable: `bse_detail/` holds one file per scrip code and a rerun skips
codes already on disk, so a rate-limit at scrip 3,000 costs the remaining 2,000
rather than the whole run.

Stage 2 never partially applies a company. A scrip whose detail fetch is missing is
ingested with NULL classification fields and NULL `classification_source` — never a
guessed sector.

### Inclusion rule

A snapshot row is ingested as a company only if its ISIN begins with `INE` or `IN9`.
Rows with `INF` ISINs (253 on BSE) are mutual-fund and ETF units, not companies, and
are excluded; so is the single BSE row whose ISIN is the literal string `NA`. This
rule is what reduces the 5,220-ISIN union to the ~4,967 company universe, and it lives
in `normalize.py` as a pure, unit-tested predicate.

### Refresh cadence

| Source | Cadence | Cost |
|---|---|---|
| NSE + BSE masters | Daily | 2 requests |
| BSE per-scrip detail | Monthly, plus on-demand for newly-appeared ISINs | ~5,000 throttled requests, ~30-40 min |
| AMFI categorisation | On publication (half-yearly) | 1 request |

## 5. Schema

### 5.1 `companies` (modified)

`id` remains the integer PK. No existing FK changes.

| Column | Change | Notes |
|---|---|---|
| `isin` | Becomes the natural key | Stays `unique`; add `CHECK (market <> 'INDIA' OR isin IS NOT NULL)` |
| `market` | New, NOT NULL, default `'INDIA'` | `'INDIA'` \| `'GLOBAL'` |
| `ticker` | Meaning narrows | Still unique NOT NULL, now *derived*: NSE listing → `SYMBOL.NS`; BSE-only → `.BO`; global → bare symbol. Purely the market-data handle |
| `official_sector` | New, nullable | BSE `Sector`, verbatim |
| `official_industry` | New, nullable | BSE `IndustryNew`, verbatim |
| `official_igroup` | New, nullable | BSE `IGroup`, verbatim |
| `official_isubgroup` | New, nullable | BSE `ISubGroup`, verbatim |
| `classification_source` | New, nullable | e.g. `'BSE'` |
| `classification_as_of` | New, nullable | Snapshot date |
| `sector` | Type unchanged, NOT NULL | Now derived from `official_sector` via an explicit mapping table, not keyword-guessed |
| `market_cap_source` | New, nullable | `'BSE'` \| `'yfinance'` |
| `market_cap_as_of` | New, nullable | |
| `amfi_tier` | New, nullable | Published `LARGE`/`MID`/`SMALL` |
| `amfi_rank` | New, nullable | |
| `amfi_as_of` | New, nullable | |
| `tradeability` | New, NOT NULL, default `'NORMAL'` | `'NORMAL'` \| `'RESTRICTED'` \| `'SME'` \| `'SUSPENDED'`, derived from the company's best listing. `market = 'GLOBAL'` rows have no listings and take the default |
| `index_tier`, `sub_sector`, `market_cap`, `business_desc`, `supply_chain_*`, `instrument_token` | Untouched | |

### 5.2 `listings` (new)

```
id            PK
company_id    FK → companies.id, NOT NULL
exchange      'NSE' | 'BSE', NOT NULL
symbol        NSE SYMBOL or BSE scrip_id, NOT NULL
scrip_code    BSE numeric code, NULL for NSE
series        NSE EQ/BE/BZ, NULL for BSE
group_code    BSE A/B/T/X/XT/Z/M/MT/MS/P/ZP, NULL for NSE
status        'ACTIVE' | 'SUSPENDED' — BSE reports it directly; NSE presence in
              EQUITY_L.csv implies 'ACTIVE'
is_sme        bool
is_primary    bool — the listing that supplies companies.ticker
face_value    numeric, nullable
listed_on     date, nullable (NSE only)
source        'NSE' | 'BSE'
as_of         date

UNIQUE (exchange, symbol)
UNIQUE (company_id, exchange)
```

A dual-listed company is one `companies` row and two `listings` rows, so a company
that is `EQ` on NSE and group `Z` on BSE records both facts truthfully.

`tradeability` derivation, most-permissive listing wins:

| Listing | Result |
|---|---|
| NSE series `EQ`, or BSE group `A`/`B` | `NORMAL` |
| NSE series `BE`/`BZ`, or BSE group `T`/`TS`/`X`/`XT`/`P`/`ZP` | `RESTRICTED` |
| BSE group `M`/`MT`/`MS` | `SME` |
| BSE group `Z`, or exchange-reported suspension | `SUSPENDED` |

### 5.3 `company_aliases` (new)

```
id           PK
company_id   FK → companies.id, NOT NULL
alias        raw string as sourced
alias_type   'LEGAL' | 'SHORT' | 'NSE_SYMBOL' | 'BSE_ID' | 'TRADE_NAME'
normalized   canonical form (see §7)

UNIQUE (normalized, company_id)
INDEX  (normalized)
```

## 6. Sources and provenance

Every source below was called during design. Status reflects what happened, not
what documentation claims.

| Source | Provides | Coverage | Status |
|---|---|---|---|
| `nsearchives.nseindia.com/content/equities/EQUITY_L.csv` | symbol, name, series, ISIN, listing date, face value | 2,409 | Verified; ISIN on 100% |
| `api.bseindia.com/BseIndiaAPI/api/ListofScripData/w` | scrip code, scrip_id, issuer name, ISIN, group, face value, **market cap** | 5,091 | Verified; ISIN 99.96%, cap on 4,808 (94%) |
| `api.bseindia.com/BseIndiaAPI/api/ComHeadernew/w` (per scrip) | official Sector / IndustryNew / IGroup / ISubGroup, group, index | 1 call per scrip | Verified on scrip 500325 |
| `api.bseindia.com/BseIndiaAPI/api/ddlIndustry/w` | closed industry vocabulary | — | Verified |
| `niftyindices.com/IndexConstituent/*.csv` | index membership, `Industry` for members | ~750 | Verified |
| AMFI categorisation list | published tier + rank | Unknown | **Documented URL returns 404 — unresolved** |
| `nseindia.com/api/quote-equity` | NSE's own classification | 2,409 | Returns 403 without a browser cookie flow — **not relied on** |

### 6.1 The AMFI gap

The design does not depend on locating the AMFI file. `amfi_tier` is nullable. When
absent, every company falls back to a tier derived from exchange-published caps using
AMFI's *published cutoff methodology* — rank 1-100 LARGE, 101-250 MID, 251+ SMALL —
which is documented independently of the file itself. The derived tier then subdivides
AMFI's open-ended SMALL band into SMALL (251-500) and MICRO (501+) per §7.

Implementation begins with a timeboxed spike to locate the current file location. If
it cannot be found, the system ships derived-only with `amfi_tier` NULL everywhere.
Nothing else in the design changes.

### 6.2 Coverage gaps and fallbacks

- **131 NSE-only companies** have no BSE classification. Where they are Nifty index
  members, the index CSVs supply `Industry`. Otherwise `sector = 'other'` with
  `classification_source = NULL` — the existing bucket, explicitly marked unsourced
  rather than keyword-guessed into a plausible-looking wrong sector.
- **~283 BSE rows without market cap** get `market_cap = NULL` and no tier.
- **NSE-only market caps** may use yfinance, always labelled
  `market_cap_source = 'yfinance'`, never overwriting an exchange-published value.

### 6.3 Staleness

New config values, enforced at API serialization:

```
UNIVERSE_MAX_AGE_DAYS       = 7      # exchange masters
MARKET_CAP_MAX_AGE_DAYS     = 30
CLASSIFICATION_MAX_AGE_DAYS = 180
AMFI_MAX_AGE_DAYS           = 240    # half-yearly plus grace
```

Past threshold the field is marked stale and the derived cap tier is **withheld**
rather than computed from months-old caps and presented as current. This mirrors
`app/market/measure.py` returning `measurement_status='no_data'` instead of a number.

## 7. Cap tier resolution

```
BSE Mktcap (4,808) ──┐
yfinance fallback  ──┼→ companies.market_cap + source + as_of
                     │
                     └→ rank all market='INDIA' by cap desc → derived tier
                                                               1-100   LARGE
AMFI list (if located) → amfi_tier + amfi_rank                 101-250 MID
                            │                                  251-500 SMALL
                            └── takes precedence when present   501+    MICRO
```

All reads go through one function:

```
resolve_cap_tier(company) -> (tier, source, as_of) | None
```

Precedence — AMFI, else derived, else withhold-if-stale — lives in exactly one place
so the API, feed filters, and deck charts cannot drift apart.
`cap_tier.compute_cap_tiers` remains the derived-ranking implementation underneath.

`cap_tier.py`'s existing contract is preserved: the derived tier is recomputed on
read, never stored as fixed truth. `amfi_tier` is not a computation — it is a sourced
fact with an as-of date, which is why it is stored.

### 7.1 AMFI and MICRO interaction

AMFI publishes only three tiers; its SMALL band is open-ended (rank 251 and below).
MICRO is not an AMFI category. Precedence is therefore defined per-tier, not
wholesale:

| AMFI says | Derived rank | Resolved tier | Reported source |
|---|---|---|---|
| `LARGE` | any | `LARGE` | `AMFI <as_of>` |
| `MID` | any | `MID` | `AMFI <as_of>` |
| `SMALL` | 251-500 | `SMALL` | `AMFI <as_of>` |
| `SMALL` | 501+ | `MICRO` | `AMFI <as_of> + NSE index methodology` |
| NULL | any | derived tier | `derived from <market_cap_source> <as_of>` |

AMFI is authoritative for the LARGE/MID/SMALL boundaries. MICRO is only ever a
subdivision of AMFI's SMALL band, and the reported source says so rather than
attributing the MICRO label to AMFI.

### 7.2 Deliberate behaviour changes

1. **MICRO changes definition** — from "below `config.MICRO_CAP_FLOOR` rupees" to
   "rank 501+", matching NSE's published Nifty Microcap 250 methodology (ranks
   501-750). Companies currently tagged MICRO by the floor rule may retag.
2. **Ranking population changes** — the ranking currently runs over 42 companies and
   after this runs over ~4,800. Existing displayed tiers will change. This is the fix,
   not a regression.

## 8. Entity resolution rebuild

New package `app/companies/matching/`, replacing `resolution._find_direct_company`:

```
normalize.py   canonical string form           pure, no DB
aliases.py     builds alias rows at ingest     pure + writes company_aliases
matcher.py     resolve(mention) -> MatchResult indexed queries only
curated.py     reviewed trade-name overrides   static data
```

### 8.1 Normalization

Lowercase, `&` → `and`, strip punctuation, collapse whitespace, then strip legal
suffixes from a closed **end-anchored** list: `ltd`, `limited`, `pvt`, `private`,
`plc`, `inc`, `corp`, `corporation`, `co`, `company`.

`india` and `bharat` are deliberately **not** stripped. They are discriminating
tokens (`Apollo Tyres` vs `Apollo Hospitals`, `Bharat Gears` vs `Bharat Seats`) and
removing them manufactures collisions.

### 8.2 Alias sources

Per company, all from ingest, no LLM: BSE `Issuer_Name` (LEGAL), BSE `Scrip_Name`
(SHORT), NSE `NAME OF COMPANY` (LEGAL), NSE symbol (NSE_SYMBOL), BSE `scrip_id`
(BSE_ID), plus `curated.py` for trade names no registry carries (`Infosys`, `LIC`,
`Maruti`).

### 8.3 Match ladder

Ordered, first hit wins, every rung **exact on the normalized form**. No substring
matching at any rung — that is the mechanism behind today's silent mismatches.

| # | Rung | Notes |
|---|---|---|
| 1 | ticker exact | Current behaviour, preserved |
| 2 | ISIN exact | If the analysis model emits one |
| 3 | alias exact | Indexed lookup on `company_aliases.normalized` |
| 4 | token-set equality | Handles word order and stray tokens |
| 5 | scored fuzzy | Only among candidates sharing a rare token; requires score ≥ threshold **and** a margin over the runner-up |

**Ambiguity resolves to `None`** at every rung, preserving the existing "omit rather
than mismatch" discipline. One narrow exception: when exactly one candidate has
`tradeability = NORMAL` and all others are `SME` or `SUSPENDED`, the NORMAL candidate
wins — the realistic collision once dormant shells enter the table.

### 8.4 Sector fan-out

`resolution._TIER_RANK` is replaced by `market_cap DESC`, filtered to
`market = 'INDIA' AND tradeability = 'NORMAL'`, with `index_tier` as tiebreak and NULL
caps last. Without the filter, the new companies would let dormant shells into the
affected-companies list.

### 8.5 Evaluation

Two corpora:

- **Regression corpus** — the 881 existing `alert_companies` rows are real
  article→company links. Extracted as expected outcomes.
- **Adversarial set** — hand-written collisions: `Bharat Seats` / `Bharat Gears` /
  `Bharat Bijlee`, `Apollo Tyres` / `Apollo Hospitals`, `SBI` / `SBI Cards` /
  `SBI Life`, `HDFC Bank` / `HDFC AMC`.

**Gate:** no net loss of matches against the regression corpus, and zero mismatches
on the adversarial set. Misses are acceptable; wrong companies are not.

### 8.6 Performance

The current path loads every company row into Python per mention
(`resolution.py:86`). The new path is a single indexed lookup. At ~5,000 companies and
~15,000 aliases this is the difference between the ingest making resolution roughly
10× slower and it not mattering.

## 9. Migration

Each step is independently reversible. Steps 1-3 are safe to ship before 4-6 exist.

1. **Schema migration** — add columns and tables, all nullable. No data change.
2. **Backfill existing 509** — match to snapshot by symbol; populate ISIN, listings,
   official classification. Fix `HPCL.NS` → `HINDPETRO.NS` and `OILINDIA.NS` →
   `OIL.NS` here (ticker rewrite only; `id` unchanged, so FKs and alert history
   survive). `JBCHEPHARM.NS`, which is absent from the NSE master entirely, is flagged
   `SUSPENDED` pending manual review rather than deleted — it has alert history.
3. **Mark globals** — 507 rows get `market = 'GLOBAL'`. The `CHECK` constraint is
   added only after this.
4. **Full ingest** — the ~4,458 new companies.
5. **Alias build and matcher swap** — behind a config flag, so the previous matcher
   can be restored without a deploy.
6. **Cap tier switchover** — last, once caps are populated.

### 9.1 Backward compatibility

`ticker` stays unique NOT NULL in `.NS`/`.BO` form, so `yf.Ticker(ticker)`,
`app/companies/price_series.py`, `app/companies/market_caps.py`,
`app/outcomes/price_fetcher.py`, and all frontend references continue to work
untouched.

**Open verification item:** Yahoo Finance's symbol format for obscure BSE-only scrips
is inconsistent (`RELIANCE.BO` versus numeric `539448.BO`). The plan includes a
verification step. BSE-only companies with no resolvable Yahoo handle keep their BSE
market cap and simply have no price series.

## 10. Error handling

Follows the degradation discipline already established in `app/market/measure.py`,
`app/companies/business_profile.py`, and `app/companies/market_caps.py`.

- A per-scrip fetch failure leaves that file absent from the snapshot; the company is
  ingested with NULL classification. The batch is never blocked.
- A source shape change (missing expected key) fails stage 1 **loudly**, with the
  offending payload, before anything reaches the DB.
- Rate limiting triggers exponential backoff then a clean stop; the resume file lets
  the next run continue.
- A partial snapshot loads what exists. Every absent fact is NULL with NULL
  provenance — never a default value.

## 11. Testing

- **Pure units, no network:** `normalize.py`, `matcher.py`, sector mapping,
  tradeability derivation, cap tier resolution.
- **Loader:** against small committed fixture snapshots (~20 companies including one
  dual-listed, one SME, one suspended, one NSE-only, one missing-cap).
- **Migration:** runs against a copy of the current DB shape and asserts all 881
  `alert_companies` FKs still resolve.
- **Matcher:** the regression corpus and adversarial set from §8.5, as a gating test.

No test contacts NSE, BSE, or AMFI. That is the purpose of the two-stage split.

## 12. Open risks

| Risk | Mitigation |
|---|---|
| AMFI file location unknown | Timeboxed spike; derived-only fallback already designed in |
| BSE endpoints are undocumented and may change or rate-limit | Two-stage split fails loudly at stage 1; resumable fetch; daily masters are only 2 requests |
| Yahoo symbol format for BSE-only scrips | Verification step in the plan; degrades to no price series |
| ~5,000 per-scrip detail calls | Monthly cadence, throttled, resumable, on-demand for new ISINs only |
| Displayed cap tiers will change for existing companies | Intended; called out in §7.1 so it is not mistaken for a regression |

## 13. Follow-on specs

- **Subsystem B** — replace LLM-generated `business_desc` and `sub_sector` with data
  derived from the official classification stored here, plus a sourced business
  description.
- **Subsystem D** — per-company × per-event-type volatility profiles, building on
  `market_moves`, `car_outcomes`, and `calibration_samples`.
