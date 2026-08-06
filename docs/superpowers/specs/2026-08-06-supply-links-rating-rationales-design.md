# Supply Links from Rating Rationales — Design

**Date:** 2026-08-06
**Status:** Approved by user (chat), pending spec review
**Depends on:** stock universe (A), sourced descriptions (B), the exact-match
ladder (`app.companies.matching`), the converging daily-budget job pattern
(`universe_detail_refresh`), Railway volume at `/app/data`.

## 1. Goal

Fill `supply_chain_suppliers_json` / `supply_chain_customers_json` — and the
still-NULL `business_desc` rows — with facts extracted from credit-rating
agencies' public rationale documents, each traceable to a named PDF. Two
consumers:

1. **Pipeline prompts** read company context from the DB instead of relying
   on the LLM's own memory of what a company does.
2. **Ripple derivation** gains a grounding layer: the event company's KNOWN
   counterparties are offered to the company-identification LLM with their
   sourced relationship. The LLM still decides who is affected.

**Hard constraint (user-locked): supply links never auto-attribute impact.**
No code path may create an AlertCompany or ImpactEdge from a stored link.
Links reach the LLM prompt and nothing else. The ETERNAL.NS failure (a
deterministic fan-out labeling a food-delivery stock "directly affected" by
a crude-oil shock) must be structurally impossible, enforced by test §8.T5.

## 2. Why rating rationales

CRISIL, ICRA, CARE, India Ratings, Acuité, Infomerics publish public
rationale PDFs for every rated instrument. They routinely name the business
model and key counterparties ("derives ~60% of revenue from Indian
Railways"; "key suppliers include ..."). They are the only free, public,
citable source of named supply-chain relationships for Indian listed
companies. Annual reports anonymize counterparties; exchanges publish none;
commercial datasets (Bloomberg SPLC, FactSet Revere) are licensed.

Coverage honesty: only rated companies have rationales — realistically
1,500–2,500 of the 4,814. Unrated microcaps keep whatever they have today.
Nothing is invented for the gap.

## 3. Discovery — where the PDFs come from

Exchanges require listed companies to disclose rating actions, and both
publish structured feeds:

- **Primary: BSE announcements API** (`AnnGetData`, category "Credit
  Rating") — same `api.bseindia.com` family the universe pipeline already
  fetches with browser headers; no cookie dance.
- **Fallback: NSE corporate-filings credit-rating index** — richer but
  behind NSE's cookie/anti-bot layer.

The plan's FIRST task is a live probe that pins the working combination and
records real payload shapes as fixtures. Announcements yield (company,
agency, date, attachment/rationale URL). Historical depth: BSE announcement
search accepts date ranges — the bootstrap walks backwards far enough to
find at least one rationale per rated company (rating reviews are at least
annual, so 24 months of announcements covers the active rated set).

### Snapshot layout (two-stage, like the universe)

```
data/ratings/index/<YYYY-MM-DD>.json      -- one announcements page per fetch day
data/ratings/docs/<scrip_code>/<sha16>.pdf -- raw rationale documents, immutable
```

Fetch stage is network-only, resumable (a doc already on disk is skipped),
throttled, and time-budgeted. Extraction reads only from disk.

## 4. Extraction — LLM as reader, never author

New module `app/companies/supply_links/` mirroring `descriptions/`:
`snapshot.py` (paths, resume sets), `fetchers.py` (network only),
`extract.py` (pure), `loader.py` (DB only).

- **PDF → text**: `pypdf` (new dependency; pure-python, no system libs —
  Railway image safe). Rationales are 2–8 pages; text extraction failure
  (scanned/image PDF) marks the doc `unextractable`, no OCR (out of scope).
- **LLM call**: forced tool call (existing `build_client` infra), input =
  rationale text (capped ~12k chars, head-weighted — business description
  and counterparty text live in the opening sections), output schema:

```json
{
  "business_summary": "2-3 plain sentences, or null",
  "suppliers":  [{"name": "...", "evidence": "verbatim quote"}],
  "customers":  [{"name": "...", "evidence": "verbatim quote"}]
}
```

- **The anti-hallucination gate**: an entry is kept ONLY if its `evidence`
  appears verbatim in the extracted PDF text (whitespace-normalized
  substring match). No quote, no row. `business_summary` must pass
  `validate_no_advice_language`. The model may return empty lists — most
  rationales name no counterparties, and empty is the correct answer.
- Lists capped at 3 suppliers + 3 customers per document (user asked for
  brief; beyond that rationales are listing the sector, not counterparties).

## 5. Storage

### 5.1 New table `supply_links`

| column | type | notes |
|---|---|---|
| `id` | int PK | |
| `company_id` | FK companies, NOT NULL | the rated company |
| `relation` | str NOT NULL | `SUPPLIER` \| `CUSTOMER` (counterparty's role relative to company) |
| `counterparty_name` | str NOT NULL | as written in the document |
| `counterparty_company_id` | FK companies, nullable | resolved via the EXACT-match ladder only (`matching.matcher`); NULL when no exact match — never fuzzy, that failure mode is documented (488/718 wrong) |
| `evidence` | text NOT NULL | the verbatim quote that survived the gate |
| `source_url` | str NOT NULL | the rationale document URL |
| `source_agency` | str NOT NULL | CRISIL / ICRA / CARE / ... |
| `as_of` | date NOT NULL | the rating action date from the filing |
| `extracted_at` | datetime NOT NULL | |

Unique on (`company_id`, `relation`, `counterparty_name`). Re-extraction of
a newer rationale for the same company REPLACES that company's rows (delete
company's links + reinsert) — a rating review supersedes the old one.
Extraction yielding zero links for a company that previously had links from
an OLDER document keeps the old rows (never clobber good data with nothing);
same-or-newer document with zero links replaces (the relationship claim
aged out).

### 5.2 Derived caches (the columns the user asked to fill)

After each load, per affected company:
- `supply_chain_suppliers_json` / `supply_chain_customers_json` = JSON list
  of `counterparty_name` from `supply_links` (the readable cache for
  prompts; the table is the source of truth).
- `business_desc` = `business_summary` ONLY where `business_desc_source_url`
  IS NULL or already points at a rating rationale — Wikipedia text is never
  overwritten, and nothing is ever blanked. Sets
  `business_desc_source_url` = rationale URL, `business_desc_as_of` = the
  rating date. (Serving gate unchanged: `sourced_description` already
  requires a URL.)

## 6. Prompt grounding (the ripple layer)

`app/analysis/cascade.py`, company-identification stage
(`_identify_companies` / per-sector caller): one new compact block, only
when the alert's direct/event companies have stored links:

```
KNOWN RELATIONSHIPS (sourced from rating documents; historical, not caused
by this news):
- RELIANCE.NS customers: Indian Oil (IOC.NS), BPCL (BPCL.NS) [CRISIL 2026-03]
- RELIANCE.NS suppliers: ...
Include a counterparty ONLY if THIS news plausibly transmits through the
relationship, and say how. A relationship alone is never a reason.
```

- Budget: max 8 link lines, max ~700 chars, event companies only — never
  per-candidate annotation (a per-candidate description block measured
  60.8k chars across 360 candidates and broke both models' TPM ceilings;
  that lesson binds).
- Resolved counterparties (with tickers) that are not already in the
  candidate list are APPENDED to it as ordinary candidates, subject to the
  existing `MAX_CANDIDATES_PER_PROMPT` cap — visible to the LLM, chosen or
  ignored by it like any other candidate.
- The block is additive: zero stored links ⇒ prompt byte-identical to today.

## 7. Jobs & runbooks

- `rating_filings_poll` (daily, scheduler): fetch yesterday's credit-rating
  announcements page into the index; queue = docs on disk not yet extracted.
- `supply_links_refresh` (daily, scheduler, time-budgeted ~30 min): fetch
  queued PDFs + extract + load, resumable, converging — same pattern as
  `universe_detail_refresh`. LLM budget guard: skips when the analysis
  pipeline's rate budget is under pressure (uses the cheap tier).
- `backfill_supply_links.py` runbook: the historical bootstrap — walks the
  announcement archive backwards (24 months), news-active companies first,
  then the rest. Resumable; safe to rerun; prints per-stage counts.

## 8. Testing

- T1 extract: evidence-gate — entry whose quote is absent from the text is
  discarded; whitespace-normalized match accepted; caps enforced.
- T2 loader: replace-on-newer / keep-on-older-empty semantics; Wikipedia
  desc never overwritten; JSON caches match the table.
- T3 matcher wiring: counterparty resolution uses the exact ladder;
  an unmatched name stores NULL company_id (asserted, not assumed).
- T4 prompt: block appears only when links exist; byte-identical prompt
  when none; caps enforced; appended candidates respect the global cap.
- T5 **no-auto-attribution**: event company with stored links + LLM
  returning zero companies ⇒ zero AlertCompany rows, zero ImpactEdges.
  This is the user-locked constraint; the test name says so.
- T6 jobs: registered with intended cadence; no network without a snapshot;
  never raise.

## 9. Non-goals

- No OCR of scanned PDFs.
- No fuzzy counterparty matching, ever.
- No auto-created ripple rows/edges from links (locked).
- No UI surface in this spec — the columns feed prompts; showing links in
  the app is a later, separate decision.
- No paid data sources.
