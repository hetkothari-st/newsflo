# News-Impact Analysis App — Implementation Spec

> A news-first investing app for Indian retail investors. Delivers market news, quantifies its impact on
> stocks, and lets users explore effects from a one-line skim down to a per-stock deep dive. A premium
> (RIA-licensed) tier pulls the user's real holdings via Account Aggregator and adds a fundamental
> impact layer.

This document is the source of truth for an agent implementing the app. Build in the order of the
**Milestones** section. Do not add buy/sell recommendations, ratings, or "attractiveness" scores — see
**Compliance** before writing any user-facing copy.

---

## 1. Product principle

**Store five layers of data, surface three fields by default.** Depth is always present but deferred
behind a tap. Every level is a complete stopping point: a user can stop at any depth and have a whole
thought, never a half-answer.

The five data layers:
1. The news event
2. Directly affected stocks (impact core)
3. The ripple (spillover to related stocks/sectors)
4. The timeline (how the effect unfolds over time)
5. Discovery data (peers, supply-chain, patterns)

The three default surface fields (the skim layer):
- Excess-move number + direction arrow
- One-line "why" (< 12 words)
- Verdict tag (one word)

---

## 2. Progressive-disclosure levels

The UI is a drill-down. Each level answers one question completely and offers a clear door to the next.

| Level | Name | Answers | Key content |
|---|---|---|---|
| 0 | Feed | "Do I care?" | Excess move, one-line why, verdict tag, peak intensity bar, portfolio dot |
| 1 | Summary card | "What happened & is it real?" | 2-sentence summary, raw vs sector move, volume, source+time |
| 2 | Ripple | "Who else does it touch?" | Winners/losers (sorted by intensity), spread by relationship type |
| 3 | Timeline | "Blip or slow burn?" | Effect unfolding: today / weeks / months / quarters |
| 4 | Stock deep-dive | "What is this company & how hard hit?" | Intensity + breakdown, "what they do", market cap/sector/PE, sector peers |

The **portfolio thread** runs through all levels: any stock the user holds is highlighted at every depth.

---

## 3. Data model

### 3.1 Entities

```
NewsEvent
  id                string
  headline          string
  source            string
  published_at      datetime        # timestamp matters — reaction speed is a signal
  category          enum(EARNINGS, REGULATORY, MANAGEMENT, M_AND_A, MACRO, ORDER_WIN,
                         CREDIT_RATING, LEGAL)
  scope             enum(COMPANY, SECTOR, MARKET)   # determines ripple width
  summary_short     string          # <= 12 words, the one-line "why"
  summary_long      string          # 2 sentences, plain language, no jargon
  verdict           enum(COMPANY_SPECIFIC, SECTOR_WIDE, UNCONFIRMED)  # derived, see 4.3
  breadth_score     int             # 0-100, how many linked stocks moved, see 4.4

Impact                              # one per (event, stock) directly affected
  event_id          fk
  ticker            string
  direction         enum(UP, DOWN, NEUTRAL)
  raw_move_pct      float           # stock's own % move on the day
  sector_move_pct   float           # its sector index % move same day
  excess_move_pct   float           # raw - sector (or beta-adjusted, see 4.1) — the real signal
  volume_multiple   float           # day volume / trailing-average volume
  why               string          # plain-language causal link
  intensity         int             # 0-100 composite, see 4.2 (computed, not stored raw)

RippleLink                          # spillover beyond directly-named stocks
  event_id          fk
  relationship      enum(BENEFICIARY, CUSTOMER_INPUT_COST, SUPPLIER, SUBSTITUTE, COMPETITOR,
                         SECTOR_WIDE)
  direction         enum(UP, DOWN, FLAT)
  strength          enum(STRONG, MODERATE, WEAK)
  description       string

TimelineEffect
  event_id          fk
  horizon           enum(TODAY, DAYS, WEEKS, MONTHS, QUARTERS)
  description       string

Stock                               # the directory / master record
  ticker            string pk
  name              string
  sector            string
  market_cap_cr     float
  cap_tier          enum(LARGE, MID, SMALL)   # derived, see 4.5 — recompute, don't hardcode
  pe                float
  business_desc     string          # plain-language "what they do" for the (i) button
  peers             string[]        # same-sector tickers
  supply_chain      { suppliers: string[], customers: string[] }

FundamentalEstimate                 # ADVISORY TIER ONLY — analyst/AI-drafted, human-checked
  event_id          fk
  ticker            string
  eps_impact_pct    float           # estimated change to annual EPS
  note              string          # e.g. "Tariff lets it raise prices ~4-6%; est. +8-11% EPS"
  score             int             # 0-100, normalized fundamental impact strength

Portfolio                           # premium tier, refreshed each morning via AA
  user_id           fk
  holdings          [{ ticker, qty, avg_cost }]
  fetched_at        datetime
```

### 3.2 Storage notes

- `excess_move_pct`, `volume_multiple`, `raw/sector move` come straight from the market-data API per event.
- `cap_tier` and `intensity` are **derived** — compute on read or on a scheduled job, never store as a
  fixed truth (prices move; tiers and scores shift).
- `FundamentalEstimate` is the only layer that isn't fully automatable — it's the human/AI-assisted
  analyst layer and the core of the premium value.

---

## 4. Calculations

### 4.1 Excess (abnormal) return — the backbone

The single most important number. Three tiers of sophistication; ship simple, upgrade later:

- **Simple (ship this first):** `excess = raw_move_pct - sector_move_pct`
- **Beta-adjusted (market model):** `expected = beta * market_move_pct; excess = raw_move_pct - expected`
  where `beta` is the stock's trailing sensitivity to the index (e.g. 1-year daily regression).
- **Multi-factor (later / research only):** adjust for market, size, value, momentum (event-study method).

Why it matters: a stock up 3% on a day its sector rose 3% had ~zero news impact. Showing raw move alone
is the #1 source of false alarms. **Always surface `excess`, not `raw`, as the headline number.**

### 4.2 Composite intensity score (0-100)

Drives the visual heat bars. Blend normalized sub-scores. Two weight profiles:

```
# Live-feed tier (fully automatable)
intensity = 0.55*excess_score + 0.25*volume_score + 0.20*breadth_score

# Advisory tier (adds fundamental layer)
intensity = 0.45*excess_score + 0.20*volume_score + 0.15*breadth_score + 0.20*fundamental_score
```

- Each sub-score is 0-100.
- `excess_score` = normalized |excess_move_pct| (normalize **within sector or event**, not globally, so a
  "70" means the same thing across stories).
- `volume_score` = normalized volume_multiple (conviction: big move on thin volume = noise).
- `breadth_score` = the event's breadth (how widely it rippled).
- `fundamental_score` = from FundamentalEstimate (advisory only).
- Keep weights in **config**, not hardcoded. Validate against CAR (4.6) later and retune.

Label bands: `>=75 High`, `50-74 Moderate`, `<50 Low`. Color: High=red-ish, Moderate=amber, Low=green
(intensity of *impact*, not good/bad — see Compliance).

**The score must never be a black box.** Every place it appears, a tap reveals the component breakdown
(each sub-score + its weight + the fundamental note in advisory mode).

### 4.3 Verdict tag (derived)

```
if event unconfirmed/denied/rumor:            UNCONFIRMED
elif |excess_move_pct| >= sector-relative threshold:  COMPANY_SPECIFIC
else:                                          SECTOR_WIDE
```

This collapses a paragraph of sector context into one scannable word. `SECTOR_WIDE` = the stock just
drifted with its group, usually skippable. `COMPANY_SPECIFIC` = worth attention. `UNCONFIRMED` = wait.

### 4.4 Breadth

Count of linked stocks (winners + losers + ripple nodes) that showed a meaningful excess move for the
event, normalized to 0-100. A one-company earnings beat scores low breadth; a sector-wide tariff scores high.

### 4.5 Market-cap tier

Do **not** hardcode. India's AMFI publishes the large/mid/small boundaries (top 100 = large, 101-250 = mid,
rest = small) and revises the list every six months. Pin your definition to the current AMFI ranking and
recompute `cap_tier` from live `market_cap_cr`.

### 4.6 CAR (Cumulative Abnormal Return) — review metric

Sum `excess` over a window (e.g. -1 to +3 trading days). Not live (completes days later). Use it on a
**review screen** to show whether a flagged reaction *held* or reversed — great for user trust and for
back-validating your intensity weights.

---

## 5. Data sources & pipeline

```
[ Market Data API ] --prices, volume, sector indices--> excess, volume_multiple, cap_tier
[ Broker API ]      --user market context / optional linking-->
[ News feed(s) ]    --headlines--> categorize + summarize --> NewsEvent
[ Account Aggregator (Sahamati) ] --consented holdings, daily--> Portfolio  (PREMIUM)
[ Analyst / AI-assisted ] --human-checked--> FundamentalEstimate  (ADVISORY)
```

Pipeline per news event:
1. Ingest headline → classify `category`, `scope`.
2. Generate `summary_short` / `summary_long` (LLM, plain language, jargon-free — validate no advice
   language leaks in).
3. Resolve affected tickers → pull raw/sector move + volume from market API.
4. Compute `excess_move_pct`, `volume_multiple`, `breadth_score`, `verdict`, `intensity`.
5. (Advisory) attach `FundamentalEstimate`.
6. Build `RippleLink`s and `TimelineEffect`s (curated + AI-drafted, human-checked for the hard links).

**Holdings via AA, not PAN scraping.** Use the Account Aggregator (Sahamati) consent framework — the
SEBI/RBI-recognized rail. Refresh each morning before market open. This also gives you a defensible
consent architecture under the DPDP Act (explicit consent, purpose limitation, secure storage).

---

## 6. Tiers

| | Free / Live feed | Premium / Advisory (RIA) |
|---|---|---|
| News feed + levels 0-4 | Yes | Yes |
| Intensity | excess + volume + breadth | + fundamental component |
| Fundamental EPS view | No | Yes |
| Portfolio overlay (AA) | No | Yes |
| Personalized, suitability-filtered advice | No (general/educational only) | Yes (RIA-permitted) |
| Discovery directory | Yes | Yes |

The advisory tier's personalized advice requires the RIA onboarding flow (risk profiling / suitability)
to sit in front of it — see Compliance.

---

## 7. Compliance (read before writing any copy)

**This is the single biggest business risk. Get a SEBI-focused lawyer to review UI copy pre-launch.**

- The app operates under a **SEBI Registered Investment Adviser (RIA)** license (fee-only; no distributor
  commissions). This permits **personalized advice** — but only after **risk profiling / suitability
  assessment** per client, and with **documented rationale** for every piece of advice (your ripple +
  timeline + intensity breakdown *is* that rationale — keep it recorded).
- **Free tier stays general/educational** — factual news, company disclosures, historical data, neutral
  framing. No personalized recommendations broadcast to all users.
- **Intensity is a news-impact metric, not a stock rating.** Label everything as "how hard the news hit,"
  never "how good to own." SEBI is sensitive to anything resembling a rating/attractiveness score. Every
  intensity surface carries the disclaimer: *measures how hard the news hit this stock — not whether it's
  a good investment.*
- **No target prices, no buy/sell/hold labels** anywhere in automated output. Personalized advice, where
  given, flows through the RIA advisory workflow with suitability checks — not as an auto-generated tag.
- **Data protection (DPDP Act):** holdings are sensitive. Explicit consent via AA, purpose limitation,
  encryption at rest and in transit, client data segregation.

---

## 8. Milestones (build order)

1. **Data model + Stock directory.** Schema, seed a handful of stocks with business descriptions, cap
   tiers computed from AMFI boundaries. Directory screen: browse/filter by cap tier + sector (no news).
2. **News event + market API wiring.** Ingest → categorize → pull prices/volume → compute
   `excess_move_pct`, `volume_multiple`, `verdict`.
3. **Feed (Level 0) + Summary (Level 1).** The skim + first tap. Excess move headline, one-liner,
   verdict, raw-vs-sector reveal.
4. **Composite intensity + breakdown popup.** Live-feed weights first. Heat bars everywhere; tap always
   reveals components. Sort winners/losers by intensity.
5. **Ripple (Level 2) + Timeline (Level 3).** Relationship-typed spillover; horizon-based effects.
6. **Stock deep-dive (Level 4) + (i) button.** "What they do", cap/sector/PE, sector peers as discovery
   doorway. (i) = quick sector/business popup without leaving the flow.
7. **Account Aggregator integration.** Daily holdings pull; portfolio dot across all levels. (Premium)
8. **RIA onboarding: risk profiling / suitability.** Gate advisory features behind it. (Premium)
9. **Fundamental estimate layer + advisory intensity weighting.** (Advisory)
10. **CAR review screen.** Back-validate flags and intensity weights.

---

## 9. UI reference (from prototype)

- Feed row: `[excess% ▲/▼]  [one-line why] [•owned]` then `[verdict tag]  [peak-intensity bar]`.
- Stock row (ripple/peers): `[TICKER] [CAP TAG] [•owned] [intensity heat bar + score] [(i)] [›]`.
  - Tapping the row → deep-dive; tapping `(i)` → quick business/sector popup (stop propagation so it
    doesn't open the deep-dive); the two are deliberately separate.
- Intensity popup: big score + band, then each component as `label — raw ×weight` with a mini bar, plus
  the fundamental note (advisory), ending with the compliance disclaimer line.
- Cap tags: LARGE / MID / SMALL, color-coded, with a legend in the header.
- Sort winners/losers and peers by intensity descending — the ordering is itself the discovery signal
  (e.g. small-caps often top the list; same news swings them hardest).

---

## 10. Guardrails for the implementing agent

- Never emit buy/sell/hold, target prices, or attractiveness ratings in automated output.
- Always surface `excess`, not `raw`, as the headline move.
- Never let the intensity score appear without a reachable component breakdown.
- Recompute (don't hardcode) `cap_tier` and `intensity`.
- Normalize intensity sub-scores within sector/event, not globally.
- Keep intensity weights and band thresholds in config.
- All holdings access via Account Aggregator consent; encrypt; never scrape PAN directly.
- Keep all summary/why copy jargon-free and plain-language.
