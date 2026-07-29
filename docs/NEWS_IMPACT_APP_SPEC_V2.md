# News-Impact Analysis App — Product, Design & Build Spec

> A card-based, news-first investing app for Indian retail investors. Delivers market news as swipeable
> cards, quantifies each story's impact on stocks, lets users explore effects from a one-line skim down
> to a per-stock deep dive, and surfaces mid/small/micro-cap stocks they'd never find in the headlines.
> A premium (RIA-licensed) tier pulls the user's real holdings via Account Aggregator and adds a
> fundamental impact layer plus personalized, suitability-based advice.

**Audience for this doc:** UI/UX designer and product developer.
**Status:** flow finalized in prototype; this is the reference to build against.
**Not yet decided (fill in before build):** tech stack, exact market-data & news vendors, visual brand.

---

## 0. How to read this doc

- Sections 1-2: the product concept and the core UX model. Designer starts here.
- Sections 3-4: data model and calculations. Developer starts here.
- Section 5: the ripple system (the analytical heart).
- Sections 6-7: discovery and the mobile card UI.
- Sections 8-10: tiers, compliance, build order.
- Section 11: guardrails checklist.

---

## 1. Product principle

**Store five layers of data, surface three fields by default.** Depth is always present but deferred
behind a swipe/tap. Every level is a complete stopping point: a user can stop at any depth and have a
whole thought, never a half-answer. The user reading 100 headlines a day should get value from the skim
alone; the user who cares about one story can drill all the way to a micro-cap's liquidity risk.

Five data layers:
1. The news event
2. Directly affected stocks (impact core)
3. The ripple (spillover to related stocks/sectors, in layers)
4. The timeline (how the effect unfolds over time)
5. Discovery data (peers, supply-chain, patterns)

Three default surface fields (the skim layer, shown on the card front):
- Excess-move number + direction arrow
- One-line "why" (< 12 words)
- Verdict tag (one word)

---

## 2. Core UX model - swipeable news cards

The primary surface is a **vertical feed of news cards**. Each card has a **front** (headline/skim) and
a **back** (layered analysis). The interaction has two axes:

- **Swipe left** on a card front -> flip to its analysis (back). Swipe left again -> advance to the next
  story. **Swipe right / back button** -> return to the headline, then to the previous story.
- **Scroll vertically** -> move through the feed of stories.
- On non-touch devices, tapping the card and arrow controls mirrors the swipe.

### Card front (skim layer)
- Direction arrow + move % (show **excess move**, not raw - see 4.1)
- Verdict tag: `Company-specific` / `Sector-wide` / `Unconfirmed`
- Headline
- One-line plain-language gist
- Category + timestamp
- Affordance: "see who's affected"
- Portfolio dot if any affected stock is in the user's holdings

### Card back (layered analysis)
- Headline (condensed) + source
- The ripple, in layers (see Section 5): each layer labelled Winners/Losers with a direction icon, a
  one-line "why this layer", and the affected stocks
- Each stock row shows: ticker, **cap tier tag**, **liquidity tag**, **impact-intensity bar + score**,
  and an **(i) info button**
- Footer disclaimer line (see Compliance)

### Deeper levels (reachable from the card back)
Tapping a stock row opens the **stock deep-dive**; tapping **(i)** opens a quick "what they do + sector"
popup without leaving the flow. The two are deliberately separate: (i) = glance and stay; row = go deep.

| Level | Name | Answers | Key content |
|---|---|---|---|
| 0 | Card front | "Do I care?" | Excess move, one-line why, verdict, portfolio dot |
| 1 | Card back - summary | "What happened & is it real?" | Gist, raw vs sector move, volume, source |
| 2 | Card back - ripple | "Who else does it touch?" | Layered winners/losers, all cap tiers |
| 3 | Timeline | "Blip or slow burn?" | Effect over today / weeks / months / quarters |
| 4 | Stock deep-dive | "What is this company & how hard hit?" | 6-signal intensity + breakdown, "what they do", cap/sector/PE, liquidity, sector peers |

---

## 3. Data model

### 3.1 Entities

```
NewsEvent
  id                string
  headline          string
  source            string
  published_at      datetime        # timestamp matters - reaction speed is a signal
  category          enum(EARNINGS, REGULATORY, MANAGEMENT, M_AND_A, MACRO, COMMODITY,
                         MONETARY_POLICY, TRADE_TARIFF, ORDER_WIN, CREDIT_RATING, LEGAL)
  scope             enum(COMPANY, SECTOR, MARKET)
  summary_short     string          # <= 12 words, the card-front gist
  summary_long      string          # 2 sentences, plain language, no jargon
  verdict           enum(COMPANY_SPECIFIC, SECTOR_WIDE, UNCONFIRMED)   # derived, see 4.3
  breadth_score     int             # 0-100, how widely it rippled, see 4.4
  ripple_template   fk -> RippleTemplate   # which archetype drives the layers, see 5

Impact                              # one per (event, stock) directly affected
  event_id          fk
  ticker            string
  direction         enum(UP, DOWN, NEUTRAL)
  raw_move_pct      float
  sector_move_pct   float
  excess_move_pct   float           # raw - sector (or beta-adjusted, see 4.1) - the real signal
  volume_multiple   float           # day volume / trailing avg
  delivery_pct      float           # % of volume taken to delivery (India edge, see 4.2)
  materiality       float           # news size vs company size, 0-100 (see 4.2)
  vol_normalized    float           # move relative to stock's own ATR/volatility (see 4.2)
  intensity         int             # 0-100 composite, see 4.2 (computed)
  why               string          # plain-language causal link

RippleTemplate                      # reusable per-category map, see Section 5
  id                string
  category          enum(...)        # which news category this template serves
  archetype         enum(COMMODITY, MACRO_POLICY, SUPPLY_CHAIN)
  layers            [RippleLayerDef] # ordered layers with relationship + direction rule

RippleLayerDef
  order             int
  title             string          # e.g. "Winners - domestic steelmakers"
  relationship      enum(PROTECTED, EXPOSED, SELLER, USER, SUPPLIER, CUSTOMER, SUBSTITUTE,
                         RATE_BENEFICIARY, RATE_SENSITIVE, DEFENSIVE_ROTATION, BYPRODUCT, DIRECT)
  direction_rule    string          # how direction is derived from the news (NOT a fixed direction)
  note              string          # one-line "why this layer"

TimelineEffect
  event_id          fk
  horizon           enum(TODAY, DAYS, WEEKS, MONTHS, QUARTERS)
  description       string

Stock                               # directory / master record
  ticker            string pk
  name              string
  sector            string
  market_cap_cr     float
  cap_tier          enum(LARGE, MID, SMALL, MICRO)   # derived from AMFI, see 4.5
  liquidity_tier    enum(LOW, MODERATE, HIGH)        # see 4.6
  pe                float
  business_desc     string          # plain-language "what they do" for the (i) button
  peers             string[]
  supply_chain      { suppliers: string[], customers: string[], substitutes: string[] }

FundamentalEstimate                 # ADVISORY TIER ONLY - analyst/AI-drafted, human-checked
  event_id          fk
  ticker            string
  eps_impact_pct    float
  note              string
  score             int             # 0-100 fundamental impact strength

Portfolio                           # premium tier, refreshed each morning via Account Aggregator
  user_id           fk
  holdings          [{ ticker, qty, avg_cost }]
  fetched_at        datetime

RiskProfile                         # premium/advisory - RIA suitability, gates advice
  user_id           fk
  risk_appetite     enum(...)
  horizon           enum(...)
  ... (suitability fields per SEBI RIA requirements)
```

### 3.2 Storage notes
- Market-derived fields (raw/sector move, volume, delivery %) come straight from the market-data API.
- `cap_tier`, `liquidity_tier`, `intensity`, `verdict`, `breadth_score` are **derived** - compute on
  read or a scheduled job; never store as fixed truth.
- `FundamentalEstimate` is the only layer not fully automatable - the human/AI analyst layer, and the
  core of premium value.

---

## 4. Calculations

### 4.1 Excess (abnormal) return - the backbone
The single most important number. Ship simple, upgrade later:
- **Simple (ship first):** `excess = raw_move_pct - sector_move_pct`
- **Beta-adjusted:** `expected = beta * market_move_pct; excess = raw_move_pct - expected`
- **Multi-factor (later/research):** market + size + value + momentum (event-study method)

**Always surface `excess`, not `raw`, as the headline number.** A stock up 3% on a day its sector rose
3% had ~zero news impact; showing raw move is the #1 source of false alarms.

### 4.2 Composite intensity score (0-100) - six signals
Blend normalized 0-100 sub-scores. Weights live in **config**; defaults:

```
intensity = 0.28*excess_score      # sector-adjusted abnormal return
          + 0.12*volume_score       # volume vs own average (conviction)
          + 0.15*delivery_score     # % of volume to delivery - real buying vs intraday speculation
          + 0.25*materiality_score  # news size vs company size - floats micro/small caps
          + 0.10*vol_norm_score     # move vs stock's own volatility - normalizes across cap sizes
          + 0.10*fundamental_score  # ADVISORY only; in live-feed tier redistribute its weight
```

Live-feed tier (no fundamental): renormalize the other five to sum to 1.

Signal rationale:
- **delivery_pct** (India-specific edge): high delivery on a move = investors accumulating; low delivery
  = day-trading noise or possible manipulation. Surfaces a warning when < 50% (see UI).
- **materiality**: a Rs 500 Cr order is transformational for a Rs 1,000 Cr micro-cap, trivial for a giant.
  This is the key signal that makes small/micro discovery work.
- **vol_normalized**: a 3% move is huge for a stable large cap, normal for a jumpy small cap.

Bands: `>=75 High`, `50-74 Moderate`, `<50 Low`. Color: High = red/warning, Moderate = amber, Low =
green. This is intensity of *impact*, not good/bad (see Compliance).

**The score must never be a black box.** Every place it appears, a tap reveals the component breakdown:
each sub-score, its weight, plus the fundamental note (advisory) and any risk warnings.

Normalize sub-scores **within a sector or event**, not globally, so a "70" means the same thing across
stories. Validate/retune weights against CAR (4.7) after launch.

### 4.3 Verdict tag (derived)
```
if event is rumor/denied/unconfirmed:                 UNCONFIRMED
elif |excess_move_pct| >= sector-relative threshold:  COMPANY_SPECIFIC
else:                                                 SECTOR_WIDE
```

### 4.4 Breadth
Count of linked stocks (winners + losers + ripple nodes) showing a meaningful excess move, normalized
0-100. One-company earnings beat -> low; sector-wide tariff -> high.

### 4.5 Market-cap tier
Do **not** hardcode. Pin to the current AMFI ranking (top 100 = large, 101-250 = mid, rest = small;
apply a micro cutoff below a chosen market-cap floor). AMFI revises the list every six months - recompute
`cap_tier` from live `market_cap_cr` against the current list.

### 4.6 Liquidity tier
Derive from average traded value / free-float / delivery volumes. Drives the liquidity tag. Critical for
small/micro caps: low liquidity means moves are amplified and exiting is hard - a risk cue, not decoration.

### 4.7 CAR (Cumulative Abnormal Return) - review metric
Sum `excess` over a window (e.g. -1 to +3 trading days). Not live. Use on a **review screen** to show
whether a flagged reaction held or reversed - builds trust and back-validates intensity weights.

---

## 5. The ripple system (analytical heart)

Each news category maps to a **RippleTemplate** - a reusable map of layers. A template defines, per layer:
the relationship type, a **direction rule** (not a fixed direction), a one-line note, and which cap tiers
to populate. Direction is derived from the news because the same company flips sign depending on the
event (a steel user loses on a steel tariff but is unaffected by an oil move; a refiner wins on cheap
crude but loses on dear crude).

### Three archetypes (cover most news)

**A. Commodity-price shape** (e.g. oil, metals) - direction hinges on "do you sell it or use it":
- Layer 1 - Direct sellers/producers (crude -> ONGC, Oil India; opposite sign to a price fall)
- Layer 2a - Refiners / marketers (buy input, sell product -> margin expands on cheaper input)
- Layer 2b - **By-products / derivatives** (crude -> petrochem: paints, tyres, plastics, specialty chem)
- Layer 3 - Heavy users where the commodity is a cost line (airlines, cement, logistics)
- Layer 4 - Macro / second-order (lower oil -> lower inflation -> mild positive for rate-sensitives)

**B. Macro / policy shape** (e.g. RBI rate move):
- Layer 1 - split *within* the direct layer: banks win (lend higher immediately) vs NBFCs lose (funding
  cost rises) - same layer, opposite directions
- Layer 2 - rate-sensitive demand (real estate)
- Layer 3 - big-ticket EMI purchases (autos, discretionary)
- Layer 4 - **defensive rotation** (low-debt staples, regulated utilities) - a *rotation* layer unique to
  macro news: "investors flee toward them", not "the event happened to them"

**C. Supply-chain shape** (e.g. import tariff):
- Layer 1 - Protected domestic makers (win)
- Layer 2 - Exposed users of the protected good (lose)
- Layer 3 - Suppliers upstream (e.g. iron ore for steel)
- Layer 4 - Substitutes sideways (e.g. aluminium for steel)

### Cap-tier spread is mandatory per layer
Every layer must populate at least one mid/small/micro cap where a real one exists. The discovery value
lives in the smaller names - a retail user knows the giants; the smaller pure-plays are the discovery.

### Standard relationship types
`PROTECTED / EXPOSED`, `SELLER / USER`, `SUPPLIER / CUSTOMER`, `SUBSTITUTE`, `BYPRODUCT`,
`RATE_BENEFICIARY / RATE_SENSITIVE`, `DEFENSIVE_ROTATION`, `DIRECT`.

Templates are curated + AI-drafted, human-checked for the hard links. Adding a new news category = adding
a new template, not rewriting the engine.

---

## 6. Discovery (surfacing mid/small/micro caps)

Large caps are found via headlines; smaller caps must be **surfaced by the system**. Three entry paths
(build as tabs):

1. **Materiality-ranked feed** - rank by news-size-vs-company-size, not price move. Floats micro/small
   caps where an event is transformational.
2. **Related to holdings** - start from a large cap the user owns -> surface the smaller suppliers, users,
   substitutes and pure-play peers the same news touches (supply-chain crawl).
3. **Unusual activity** - small/micro caps with abnormal volume/delivery, each flagged by whether the
   delivery data makes the move trustworthy or speculative.

**Default feed sort = intensity (not headline prominence).** Headline-ranked feeds inherit the media's
large-cap bias and kill discovery. Provide a **cap-tier filter** (All / Large / Mid / Small / Micro).

### Liquidity / risk guarding (non-negotiable for small/micro)
Surfacing small/micro caps without risk cues would steer inexperienced investors toward the most
manipulable, illiquid names - bad for them and an RIA liability. Every small/micro surface must carry:
- a **liquidity tag** (Low / Moderate / High)
- a **low-delivery warning** when delivery % < 50 ("much of this move was intraday speculation")
- a **thin-trading note** ("small size amplifies moves both ways; exiting can be hard - higher risk")

Framing stays factual: "most affected by news", never "best to buy".

---

## 7. Mobile UI reference

- **Card front:** `[excess% up/down]  [verdict tag]` -> headline -> one-line gist -> category, time ->
  "see who's affected". Portfolio dot if owned.
- **Card back (per layer):** direction icon + layer title, one-line note, then stock rows.
- **Stock row:** `[TICKER] [CAP TAG] [LIQ TAG] ... [(i)]` then `impact [bar] 82`. Tapping the row ->
  deep-dive; tapping `(i)` -> business/sector popup (stop propagation so the row doesn't also open).
- **Intensity popup / deep-dive:** big score + band, six components each as `label - raw x weight` with a
  mini bar, fundamental note (advisory), low-delivery + thin-trading warnings where they apply, then the
  compliance disclaimer line.
- **Cap tags:** LARGE / MID / SMALL / MICRO, color-coded, legend in header.
- **Sort winners/losers/peers by intensity descending** - the ordering is itself the discovery signal.
- **Gestures:** swipe-left flip (front->back), swipe-left again (next story), swipe-right/back to reverse;
  vertical scroll for the feed. Mirror with taps on non-touch.

Design tokens/behaviour: flat surfaces, hairline borders, 12px card radius, no gradients/shadows, mobile
column cap of two, min font 11px, sentence case throughout.

---

## 8. Tiers

| | Free / Live feed | Premium / Advisory (RIA) |
|---|---|---|
| Card feed + levels 0-4 | Yes | Yes |
| Intensity | 5 signals (excess, volume, delivery, materiality, vol-norm) | + fundamental (6th) |
| Fundamental EPS view | No | Yes |
| Portfolio overlay (AA) | No | Yes |
| Personalized, suitability-filtered advice | No (general/educational only) | Yes (RIA-permitted) |
| Discovery (all 3 paths) + directory | Yes | Yes |
| CAR review screen | Yes | Yes |

Advisory personalized advice requires the RIA onboarding (risk profiling / suitability) in front of it.

---

## 9. Compliance (read before writing any user-facing copy)

**Single biggest business risk. Get a SEBI-focused lawyer to review UI copy pre-launch.**

- App operates under a **SEBI Registered Investment Adviser (RIA)** license (fee-only; no distributor
  commissions). This permits **personalized advice** - but only after **risk profiling / suitability**
  per client, with **documented rationale** for every piece of advice (the ripple + timeline + intensity
  breakdown *is* that rationale - record it).
- **Free tier stays general/educational** - factual news, disclosures, historical data, neutral framing.
  No personalized recommendations broadcast to all users.
- **Intensity is a news-impact metric, NOT a stock rating.** Label everything "how hard the news hit,"
  never "how good to own." Every intensity surface carries: *measures how hard the news hit this stock -
  not whether it's a good investment.*
- **No target prices, no buy/sell/hold labels** in automated output. Personalized advice flows only
  through the RIA advisory workflow with suitability checks.
- **Data protection (DPDP Act):** holdings are sensitive. Holdings access **only via Account Aggregator
  (Sahamati) consent** - never scrape PAN directly. Explicit consent, purpose limitation, encryption at
  rest and in transit, client-data segregation. Refresh each morning before market open.
- **Small/micro-cap risk cues are a compliance feature**, not decoration (see 6).

---

## 10. Build order (milestones)

1. **Data model + Stock directory.** Schema; seed stocks with business descriptions; cap + liquidity
   tiers computed. Directory screen: browse/filter by cap tier + sector (no news).
2. **News ingest + market API.** Ingest -> categorize -> pull prices/volume/delivery -> compute excess,
   volume_multiple, delivery, materiality, vol_normalized, verdict.
3. **Card feed (Level 0) + card front.** Skim layer; excess-move headline, one-liner, verdict, portfolio
   dot placeholder. Intensity-ranked default sort + cap filter.
4. **Composite intensity + breakdown popup.** Five live-feed signals first; heat bars everywhere; tap
   reveals components. Sort by intensity.
5. **Card back - ripple (Level 2) via RippleTemplate.** Build the three archetype templates; layered
   winners/losers; relationship-typed; cap-tier spread per layer.
6. **Timeline (Level 3) + stock deep-dive (Level 4) + (i) button + liquidity/risk cues.**
7. **Swipe interaction model.** Front<->back flip, next/prev story, vertical feed; tap fallbacks.
8. **Discovery: 3 tabs** (materiality, related-to-holdings, unusual activity) with risk guarding.
9. **Account Aggregator integration.** Daily holdings pull; portfolio dot across all levels. (Premium)
10. **RIA onboarding: risk profiling / suitability.** Gate advisory features. (Premium)
11. **Fundamental estimate layer + 6-signal advisory weighting.** (Advisory)
12. **CAR review screen.** Back-validate flags and intensity weights.

---

## 11. Guardrails for the implementing team

- Never emit buy/sell/hold, target prices, or attractiveness ratings in automated output.
- Always surface `excess`, not `raw`, as the headline move.
- Never let the intensity score appear without a reachable component breakdown.
- Recompute (don't hardcode) `cap_tier`, `liquidity_tier`, and `intensity`.
- Normalize intensity sub-scores within sector/event, not globally.
- Keep intensity weights and band thresholds in config.
- Every small/micro-cap surface carries a liquidity tag; low-delivery and thin-trading warnings fire
  where applicable.
- Every layer of every ripple populates at least one mid/small/micro cap where a real one exists.
- Direction is derived per-news from relationship type, never stored as a fixed per-stock attribute.
- All holdings access via Account Aggregator consent; encrypt; never scrape PAN directly.
- All summary/why/gist copy is jargon-free, plain language, sentence case.
- Discovery framing is factual ("most affected by news"), never "best to buy".
