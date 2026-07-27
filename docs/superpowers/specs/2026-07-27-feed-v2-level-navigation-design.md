# Feed-v2 Level Navigation + Impact Core Design

## Problem

`docs/NEWS_IMPACT_APP_SPEC.md` §2 requires five progressive-disclosure
levels, each "a complete stopping point" reached via "a clear door to the
next level." The current feed-v2 build violates this in two ways:

1. **Levels are not separated.** `Level1SummaryV2.tsx` renders the
   summary (Level 1), ripple (Level 2), and timeline (Level 3) all
   inline, always-rendered, inside one `AlertDetail` popup opened from
   the feed row. There is no per-level stop, no door, no back button
   between levels — everything scrolls together in one modal. Level 4
   (`/feed-v2/stock/:ticker`) is already a real route and is NOT part of
   this problem.

2. **The "Impact core" data layer doesn't exist.** Spec §1 lists five
   data layers; layer 2 is "Directly affected stocks (impact core)" —
   distinct from layer 1 (the news event) and layer 3 (the ripple).
   `compute_alert_measurement` (`backend/app/market/alert_measurement.py`)
   only ever returns the single "peak" company (the one with the largest
   `|excess_move_pct|`) for an alert. When an alert names multiple
   directly-affected companies (confirmed in production: a bee-farming
   story named both `HINDUNILVR.NS` and `CONCOR.NS`), every company
   except the peak has no dedicated "here's who was named and why" view
   anywhere — `AlertCompany.why` (the LLM-generated, per-company causal
   explanation, already populated by `refine_alert`) is never surfaced in
   feed-v2's API or UI at all, for any company.
   >
   > **Correction (post-implementation whole-branch review):** this
   > section originally claimed non-peak companies were "never shown in
   > ripple... never shown anywhere." That's inaccurate —
   > `compute_ripple_companies` (`backend/app/market/ripple.py`) already
   > includes every non-peak `AlertCompany`, direct or indirect, grouped
   > by relationship type; only `get_sector_peers_for_alert` (a different
   > function, feeding Level 4's sector-peers doorway) is scoped to one
   > company's sector. So a non-peak *directly-named* company was already
   > visible via ripple before this design — just without its own `why`
   > text or a "these are the ones directly named" framing. The Impact
   > core section this design adds is still additive value (the `why`
   > narrative + a data-layer-2-shaped view), but it now intentionally
   > overlaps with ripple for that subset of companies — accepted as two
   > legitimate lenses on the same company (Level 1 = named + why, Level
   > 2 = grouped by relationship), not deduplicated. See `compute_impact_
   > companies`'s docstring in `alert_measurement.py` for the same note.

## Goals

- Levels 1, 2, 3 become real, separately-routed pages, each a complete
  stop with an explicit door to the next (matching Level 4's existing
  pattern).
- Level 1 gains an "Impact core" section: every directly-affected
  company for the alert, each with its own excess move, direction, and
  `why`.
- No change to Level 0 (feed list), Level 4 (stock deep-dive), the
  legacy `/` feed, or any backend measurement/intensity calculation.

## Non-goals

- Redesigning ripple or timeline content (both already spec-compliant
  content-wise, per Phase 5/6 — this only changes where/how they're
  reached, not what they show).
- Portfolio thread, Account Aggregator, advisory tier, CAR review — all
  out of scope, already built in earlier phases or explicitly premium.

## Backend changes

### `compute_impact_companies` (new, `app/market/alert_measurement.py`)

```python
def compute_impact_companies(session: Session, alert: Alert) -> list[dict]:
    """Every AlertCompany for this alert with a real measured excess move
    (measurement_status == "ok") -- the spec's "Impact core" data layer
    (§1, layer 2), distinct from compute_alert_measurement's single
    "peak" company. Returns [] if none are measured (never raises; same
    "omit rather than fabricate" discipline as compute_alert_measurement).
    Each entry: ticker, name, direction, excess_move_pct, why (str | None
    -- refine_alert may not have populated it, e.g. if the LLM call
    failed; omit rather than fabricate, same as every other LLM-text
    field in this codebase).
    """
```

Implementation: query `MarketMove` rows for `alert.id` with
`measurement_status == "ok"`, join back to `AlertCompany`/`Company` for
`direction`/`why`/`ticker`/`name`. Sort by `abs(excess_move_pct)`
descending (largest reaction first — same ordering discipline as
`compute_alert_measurement`'s peak selection and ripple's intensity
sort).

### `GET /api/feed-v2/{alert_id}` (`app/routers/feed_v2.py`)

Add `result["impact_companies"] = compute_impact_companies(db, alert)` to
the existing handler, alongside the existing `ripple`/`timeline` keys.
`GET /api/feed-v2` (the list endpoint) is unchanged — impact core is
Level 1+ detail, not feed-row content.

## Frontend changes

### New routes (`App.tsx`)

```
/feed-v2/alert/:id            Level 1 (summary + impact core)
/feed-v2/alert/:id/ripple     Level 2 (ripple)
/feed-v2/alert/:id/timeline   Level 3 (timeline)
/feed-v2/stock/:ticker        Level 4 (unchanged, already exists)
```

Each is a real page (not a modal), so the browser back button and direct
linking work naturally, consistent with Level 4's existing pattern.

### `FeedRowV2.tsx`

`onOpen` navigates to `/feed-v2/alert/${alert.id}` instead of calling a
callback that opens `AlertDetail`. The intensity-breakdown `(i)` tap
target is unchanged (stays a small popup, not a level — spec §9
describes it as a popup, not a drill-down stop).

### `AlertLevel1Page.tsx` (new, replaces `Level1SummaryV2`'s
composition role)

Renders: verdict badge + `summary_long` (existing), raw/sector move +
volume + source/time (existing), then a new **Impact core** list — one
row per `impact_companies` entry: ticker, direction arrow, signed
excess-move %, and `why` text. Ends with a "See ripple →" link to
`/feed-v2/alert/:id/ripple`. A back control returns to `/feed-v2`.

`Level1SummaryV2.tsx` is deleted; its existing summary/raw-move markup
moves into `AlertLevel1Page.tsx` verbatim (no visual change to that
part), the ripple/timeline `<RippleSection>`/`<TimelineEffect>` calls at
its bottom are removed (they move to their own pages below).

### `AlertRipplePage.tsx` (new)

Thin page wrapper: fetches the alert (reuse `getFeedV2Alert`), renders
the existing `RippleSection` component unchanged, adds a "See timeline
→" link to `/feed-v2/alert/:id/timeline` and a back link to
`/feed-v2/alert/:id`.

### `AlertTimelinePage.tsx` (new)

Thin page wrapper: fetches the alert, renders the existing
`TimelineSection` component unchanged, adds a back link to
`/feed-v2/alert/:id/ripple`. No "next" door — Level 3 is the last of
the news-event levels (Level 4 is reached from ripple/peer rows, not
timeline, matching the existing `PeerRow` → deep-dive pattern).

### `feedV2Api.ts`

Add `why: string | null` to a new `ImpactCompany` interface (ticker,
name, direction, excess_move_pct, why) and `impact_companies?:
ImpactCompany[]` to `FeedV2Alert`.

## Data flow

```
FeedRowV2 tap -> /feed-v2/alert/:id (Level 1: summary + impact core)
  -> "See ripple" -> /feed-v2/alert/:id/ripple (Level 2)
    -> "See timeline" -> /feed-v2/alert/:id/timeline (Level 3)
  -> PeerRow tap (from ripple) -> /feed-v2/stock/:ticker (Level 4)
Impact core row tap -> /feed-v2/stock/:ticker?alertId=:id (Level 4,
  reuses PeerRow's existing navigate-on-click pattern)
```

## Testing

- Backend: unit tests for `compute_impact_companies` (multi-company
  alert returns all measured companies, not just peak; unmeasured
  companies excluded; `why` omitted when null; sort order). Router test
  for the new `impact_companies` key on `GET /api/feed-v2/{id}`.
- Frontend: component tests for `AlertLevel1Page`/`AlertRipplePage`/
  `AlertTimelinePage` (render impact core rows, door links present and
  point to the right route, back links correct). Update
  `FeedV2.test.tsx`/`FeedRowV2.test.tsx` for the route-navigation change
  (was: opens modal: now: navigates). Playwright screenshots (HARD RULE:
  390px/1920px, dark/light) for all three new level pages plus the
  updated feed-row tap behavior.
