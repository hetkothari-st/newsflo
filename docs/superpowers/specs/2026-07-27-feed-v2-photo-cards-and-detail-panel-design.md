# Feed-v2 Photo Cards + Tabbed-Accordion Detail Panel Design

## Problem

Two user-facing complaints against the feed-v2 rebuild shipped earlier this
session (`docs/superpowers/specs/2026-07-27-feed-v2-level-navigation-design.md`):

1. **Levels 1-3 as separate routed pages is the wrong interaction.** The
   prior design read spec §2 ("each level a complete stopping point... a
   clear door to the next") as requiring real navigation. The user's
   explicit correction: everything should be reachable from one popup,
   opened via a click, closed to return to the feed — no page
   redirects. The three routed pages (`AlertLevel1Page`,
   `AlertRipplePage`, `AlertTimelinePage`) and their routes are reverted.

2. **Feed row (Level 0) looks nothing like "a feed."** `FeedRowV2.tsx` is
   a bare text row (excess %, one-liner, verdict tag, ticker, intensity
   bar) — no photo, no real headline. The user wants the legacy feed's
   visual language (article photo, headline) applied to feed-v2's rows,
   without adopting the legacy feed's full-screen swipeable-carousel
   *interaction* (confirmed explicitly: scrollable list, not carousel).

## Goals

- Feed-v2's alert detail becomes a single popup with a tab strip
  (Affected · Ripple · Timeline) below an always-visible summary; tapping
  a tab expands that section in place, tapping the active tab again
  collapses it. Only one section body renders at a time.
- Feed-v2's feed rows become photo cards: article image, category badge,
  time, headline — plus feed-v2's own excess/why/verdict/intensity skim
  fields — in a normal scrollable list.
- Reuse existing components verbatim wherever content is unchanged:
  `AlertCover` (photo + category-tinted fallback), `CategorySwatch`,
  `RippleSection`, `TimelineSection`, the impact-core row markup.
- Zero changes to the legacy `/` feed, Level 4 (`StockDeepDivePage`), or
  any backend measurement/intensity calculation.

## Non-goals

- Swipeable carousel interaction (explicitly declined).
- Redesigning ripple/timeline/impact-core *content* (only their
  container/composition changes, same discipline as the reverted design).
- Any change to `compute_impact_companies`, `compute_ripple_companies`,
  or the CAR/portfolio/advisory features.

## Backend changes

### `article.image_url` on feed-v2 endpoints

`Article.image_url` already exists (populated by `fetch_og_image`, already
used by the legacy feed's `AlertCoverCard`) but `app/routers/feed_v2.py`'s
`_serialize` never includes it. Add it to the `article` dict in
`_serialize` (`app/routers/feed_v2.py`) — this is the only backend change;
it affects both `GET /api/feed-v2` (list) and `GET /api/feed-v2/{id}`
(detail), since both call `_serialize`.

No other backend change. `impact_companies`/`ripple`/`timeline` data
already exists from the prior design and is unchanged.

## Frontend changes

### Revert: delete the three routed pages

Delete `frontend/src/pages/AlertLevel1Page.tsx` (+ `.test.tsx`),
`AlertRipplePage.tsx` (+ `.test.tsx`), `AlertTimelinePage.tsx` (+
`.test.tsx`). Remove their three routes and imports from `App.tsx`.
`FeedRowV2.tsx`'s intensity-breakdown popup and Level 4
(`StockDeepDivePage`, `/feed-v2/stock/:ticker`) are untouched.

### `feedV2Api.ts`

Add `image_url: string | null` to `FeedV2Article`. `ImpactCompany` and
`impact_companies?` on `FeedV2Alert` (added by the prior design) are
unchanged and still needed by the new panel's Affected tab.

### `AlertDetailPanel.tsx` (new)

Replaces the three deleted pages as a single component rendered inside
the existing `AlertDetail` popup shell (`frontend/src/components/
AlertDetail.tsx`, unchanged). Props: `{ alert: FeedV2Alert }`.

Structure, top to bottom:
1. **Summary block** (always visible, not tabbed): verdict badge +
   `summary_long`, raw/sector move + volume tile, source/time —
   identical markup to the old `AlertLevel1Page`'s summary section
   (verbatim reuse, just moved into this component).
2. **Tab strip**: three tabs — "Affected" (count badge from
   `impact_companies.length`), "Ripple" (count from `ripple.length`),
   "Timeline" (count from `timeline.length`). Hairline-bordered row,
   active tab underlined in `--color-accent`. State:
   `activeTab: 'affected' | 'ripple' | 'timeline' | null` (starts
   `null` — nothing expanded by default, matching "should open when I
   click" — collapsed until tapped). Tapping the active tab sets state
   back to `null` (collapse); tapping a different tab switches directly.
3. **Expanded section body** (only rendered when `activeTab` is not
   null): `affected` → the impact-core row list (ticker, signed excess
   %, why — verbatim markup from the old `AlertLevel1Page`); `ripple` →
   `<RippleSection companies={alert.ripple} alertId={alert.id} />`
   unchanged; `timeline` → `<TimelineSection entries={alert.timeline} />`
   unchanged. If the relevant array is empty, render a single quiet line
   ("No affected companies found." / "No ripple detected." / "No
   timeline available.") instead of hiding the tab — keeps the tab strip
   stable (no layout jump as counts vary alert to alert).

Visual treatment matches the project's existing editorial tokens
(`frontend/src/index.css`): hairline borders between summary/tab-strip/
body, `font-data` for counts/tickers, no card shadows, tab underline in
`--color-accent`.

### `FeedRowV2.tsx` (rebuilt)

New layout, top to bottom:
1. **Photo banner** (fixed height, e.g. `h-40`): `<AlertCover
   imageUrl={alert.article.image_url} category={alert.category} />`,
   with `<CategorySwatch category={alert.category} />` and a relative
   timestamp overlaid top-left/top-right (small pill chips over the
   image, same treatment as `AlertCoverCard`'s carousel variant).
2. **Headline**: `alert.article.title`, bold, 2-line clamp.
3. **Skim row** (existing feed-v2 fields, unchanged data, restyled to
   sit under the headline instead of being the whole row): excess % +
   arrow (`formatExcess`), `summary_short`, verdict tag
   (`verdictLabel`), intensity bar + score (existing
   `intensity-tap-target` behavior unchanged — still opens
   `IntensityBreakdownPopup`, still stops propagation), peak ticker,
   owned dot (`in_my_holdings`).

Tapping the card (outside the intensity tap-target) calls `onOpen()` —
`FeedV2.tsx` wires this back to opening `AlertDetailPanel` in a popup
(fetch-on-open, matching the pre-routes `handleOpen` pattern that
existed before the reverted design), not `navigate(...)`.

### `FeedV2.tsx` (reverted to popup)

Restore the `openAlert` state + `handleOpen` fetch pattern (same shape
as the original, pre-this-session `Level1SummaryV2`-opening version),
but render `<AlertDetailPanel alert={openAlert} />` inside `AlertDetail`
instead of `<Level1SummaryV2 alert={openAlert} />`.

## Data flow

```
FeedRowV2 tap -> FeedV2.tsx fetches the alert -> AlertDetail popup opens
  -> AlertDetailPanel: summary always shown; tap "Affected"/"Ripple"/
     "Timeline" tab -> that section expands in place, others collapse
Impact-core row tap (inside "Affected" tab) -> /feed-v2/stock/:ticker
  (Level 4, unchanged)
Ripple peer row tap (inside "Ripple" tab) -> /feed-v2/stock/:ticker
  (Level 4, unchanged)
```

## Testing

- Backend: router test asserting `image_url` present on both list and
  detail `article` payloads (extends `test_feed_v2_router.py`).
- Frontend: `AlertDetailPanel.test.tsx` — summary always renders; each
  tab expands its own section and collapses the others; tapping the
  active tab collapses it; empty-array tabs show the quiet fallback
  line, not a hidden tab. `FeedRowV2.test.tsx` — updated for the new
  photo-card markup (image, headline, category, time) while keeping
  existing assertions for excess/verdict/ticker/score/owned-dot/
  intensity-popup behavior. `FeedV2.test.tsx` reverted to asserting
  popup-open behavior (as it was before the routed-pages design).
  Playwright screenshots (HARD RULE): feed list (photo cards) and the
  detail panel with each of the three tabs expanded, 390px/1920px,
  dark/light.
