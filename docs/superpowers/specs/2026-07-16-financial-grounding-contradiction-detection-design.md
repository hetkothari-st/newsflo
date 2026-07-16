# Financial Grounding & Contradiction Detection — Design

## Goal

This is sub-project 1 of a 5-item reasoning-quality roadmap (financial grounding
+ contradiction detection → historical retrieval via pgvector → curated company
relationship data → automated flywheel tuning). Ground the AI reasoning
pipeline in real financial data instead of letting Claude potentially state
plausible-sounding but ungrounded price/return numbers, and build the first
real implementation of contradiction detection — currently a hardcoded
`reasoning_consistent=True` in `app/reasoning/confidence.py`, explicitly
flagged as a known gap when that module was built
(`docs/superpowers/specs/2026-07-15-reasoning-engine-upgrade-design.md`).

These two are one feature, not two: contradiction detection requires the same
real price data that grounding requires — you cannot detect "reasoning says
bullish but the stock is down 12% this month" without first having that 12%
number.

## Current state (grounded in the actual code)

`backend/app/analysis/claude_client.py`'s prompt (`ANALYSIS_INSTRUCTIONS`)
explicitly tells the model not to fabricate a precise price/data figure it
isn't confident in (existing rule, unchanged by this work) — but supplies it
with **zero real numbers**. `backend/app/pipeline.py` never reads price data;
it only reads `ticker`/`sector`/`sub_sector` off the resolved `Company`.

Two existing, reusable yfinance call sites already follow this codebase's
established "never raise, degrade to `None`" contract:

- `backend/app/outcomes/price_fetcher.py::fetch_price_change_pct(ticker,
  start_date, horizon_days)` — % change over a window starting at
  `start_date`. Currently used *forward*-looking by the calibration/outcome
  tracker (measuring what happened *after* an alert). This design reuses it
  *backward*-looking (`start_date = now - N days, horizon_days = N`) to get
  "how has this stock moved over the last N days as of right now" — same
  function, different call arguments, no code change needed to that file.
- `backend/app/companies/price_series.py::fetch_price_series(ticker, period)`
  — daily closes over a yfinance period string.

Separately, `backend/app/prices/live_price.py`'s `LIVE_PRICE_CACHE` (Zerodha
Kite real-time ticks) is India-only, requires a matched `instrument_token`
(NIFTY-tier companies only, exact-ticker-match to Zerodha's instrument CSV),
and provides last-traded-price only, no returns. This design does **not**
merge with that system — it uses yfinance uniformly (works for both Indian
and the ~500 global companies already seeded) as a single, simpler data
source. `Company.market_cap` exists as a column but is `None` for every
global company and unconfirmed for Indian ones — out of scope for this
design (not needed for the contradiction-detection use case; a later,
separate pass can backfill it if wanted).

## Design

### 1. Financial snapshot fetcher

New `backend/app/reasoning/financial_context.py`:

```python
def fetch_financial_snapshot(ticker: str) -> dict | None:
    """Fetch {"price": float, "return_1m": float | None, "return_3m": float | None}
    for `ticker`, backward-looking from now. Returns None only if the current
    price itself is unavailable (a snapshot with no price is useless); a
    missing 1m/3m return alone degrades to None for that field, not the
    whole snapshot -- same "partial degrade" contract as the rest of this
    codebase's yfinance call sites.
    """
```

Implementation: current price = last close from
`fetch_price_series(ticker, period="5d")` (existing function, unmodified);
`return_1m`/`return_3m` = two calls to `fetch_price_change_pct(ticker,
start_date=utcnow() - timedelta(days=N), horizon_days=N)` for N=30 and
N=90 (existing function, unmodified, called with different arguments than
its current caller uses).

### 2. Caching — new `financial_snapshots` table, 1-hour TTL

A company can appear in multiple alerts within a short window (e.g. two
separate news stories about the same stock the same afternoon) — without
caching, each would re-hit yfinance. New table:

```
financial_snapshots
  id, ticker (unique), price, return_1m, return_3m, fetched_at
```

`get_or_fetch_financial_snapshot(session, ticker) -> dict | None`: looks up
an existing row for `ticker`; if `fetched_at` is within the last hour,
returns its cached values; otherwise calls `fetch_financial_snapshot` and
upserts the row (insert if absent, update if stale). New table only — no
`_ADDED_COLUMNS` entry needed (that mechanism is for new *columns* on
existing tables; a brand-new table is created automatically by
`Base.metadata.create_all`, same as every other table in this project, since
there's no Alembic here).

### 3. Contradiction detection — deterministic, 5% threshold

New function, `backend/app/reasoning/financial_context.py` (co-located with
the fetcher since they're used together):

```python
def detect_price_contradiction(direction: str, return_1m: float | None) -> str | None:
    """Returns a human-readable contradiction note, or None if no
    contradiction (including when return_1m is unavailable -- absence of
    data is not evidence of a contradiction)."""
```

Threshold: 5 percentage points. `direction == "bullish"` and `return_1m <=
-5.0` → note like `"Price down 8.3% over the past month despite bullish
call."`. `direction == "bearish"` and `return_1m >= 5.0` → the mirrored note.
Anything else (including `return_1m is None`) → `None`. The threshold lives
as a named constant, not a magic number, so it can be retuned later exactly
like the Confidence Engine's weight constants.

### 4. Wiring into the pipeline

`backend/app/pipeline.py::_persist_alert`'s per-company loop already calls
`get_calibration_health(...)` right before `compute_confidence(...)` (from
the prior reasoning-engine-upgrade work). This design adds, at the same
point: `snapshot = get_or_fetch_financial_snapshot(session, company.ticker)`,
then `contradiction_note = detect_price_contradiction(entry["direction"],
snapshot["return_1m"] if snapshot else None)`. The existing
`compute_confidence(...)` call's `reasoning_consistent=True` (hardcoded)
becomes `reasoning_consistent=contradiction_note is None` — the real
signal now feeds the same Confidence Engine slot that was reserved for it
when that module was built.

New `AlertCompany` columns (nullable, same manual `_ADDED_COLUMNS` migration
pattern as every prior column addition in this project): `price_at_analysis`,
`return_1m`, `return_3m`, `contradiction_note`.

### 5. Frontend — new "Facts" block in `ReasoningPanel`

A new section in `frontend/src/components/ReasoningPanel.tsx`, separate from
the existing "Why this call" evidence section (gated on `reasons.length > 0`)
— Facts should render whenever `price_at_analysis` is present, independent
of whether the evidence-discipline fields exist, since a legacy alert
persisted before *this* feature but after the *prior* one could have
evidence but no facts, or vice versa going forward. Shows price, 1-month
return, 3-month return (each individually omitted if `null`). If
`contradiction_note` is present, it renders with distinct visual treatment
(not a routine muted caption — this is a real accuracy signal the user
should notice, styled closer to the existing `text-bearish`/warning
treatment already used elsewhere in this component for penalties).

New `AlertCompany` TypeScript fields (optional, same pattern as every field
added by the prior frontend work): `price_at_analysis?: number | null`,
`return_1m?: number | null`, `return_3m?: number | null`,
`contradiction_note?: string | null`.

## Explicitly out of scope for this design

`Company.market_cap` backfill (not needed for contradiction detection).
Merging with the Kite live-price system (deliberately separate, simpler data
source). Sub-projects 2-5 of the roadmap (pgvector historical retrieval,
curated company relationship data, automated flywheel tuning) — each gets
its own design cycle.

## Testing

`fetch_financial_snapshot` and `detect_price_contradiction` are pure-ish
functions (the fetcher wraps yfinance, mockable the same way
`fetch_price_change_pct`'s existing tests mock it) — straightforward unit
tests with fixed inputs for the contradiction threshold's boundary (exactly
5.0%, just under, just over, in both directions), and for the "no data"
degrade-to-None case. `get_or_fetch_financial_snapshot`'s cache-hit/cache-miss
behavior tested against a real in-memory DB (`db_session` fixture), matching
the pattern already used for `get_calibration_health`. Pipeline-level
integration test confirming a contradiction note actually flows through to
`compute_confidence`'s `reasoning_consistent` argument and gets persisted.
