# Dedicated Charts Page (v3) — Design

## Goal

Replace the in-place SVG tree (`CompanyTree.tsx`) — judged "bad, non-aesthetic"
twice — with a dedicated, full-screen charts page reached by swiping right
off an alert. Four chart types, each a real data-visualization form (treemap,
grouped bars, diverging bar, donut) built entirely from data the pipeline
already produces, not a generic node-link diagram.

## Scope

This is **Phase 1** of the master spec's 10 graph types. The master spec's
`ImpactNode`/`ImpactEdge` data model assumes fields this app doesn't capture:
numeric confidence (0-100), time horizon, a separate evidence list, and any
company↔company/entity relationship (supplier/customer/competitor/commodity/
regulation/macro/ownership). Building the graph types that need those
(Ripple Effect, Supply Chain, Multi-Level Impact Tree, Economic Propagation,
Knowledge Graph) means a new relationship-extraction AI pipeline, which the
spec's own "never fabricate market relationships" / "avoid inventing
supply-chain relationships" rules make a real risk — that's its own project
with its own design pass, not a UI task. Confidence Tree and Timeline Tree
are one step closer (just need two new LLM-schema fields, no fabrication
risk) but are also deferred — out of scope here.

**This phase covers the 4 chart types buildable from today's data:**
Sector, Tier, Impact (winners/losers), Positive/Negative Split.

## Data (no backend model changes)

Every chart consumes the existing `AlertCompany` fields already on the
wire: `direction`, `magnitude_low`/`magnitude_high`, `sector`, `index_tier`,
`ticker`, `name`, `rationale`, `key_points`, `basis`, `confidence`,
`past_mentions`. Per the analysis pipeline (`claude_client.py` rule 5), an
alert has **at most 5 companies** — every chart is small-N by construction,
not a dense visualization.

### New backend endpoint: `GET /api/alerts/{id}`

The charts page is a real route (`/alerts/:id/charts`) and must work on a
direct load/refresh/share, not just via in-app navigation state. Add a
single-alert endpoint reusing the per-alert serialization already in
`list_alerts` (`backend/app/routers/alerts.py`), extracted into a shared
`_serialize_alert(alert, ...)` helper so the two routes don't duplicate that
block. 404 if the id doesn't exist.

## Navigation

- **New route**: `/alerts/:id/charts` (`App.tsx`), rendering `AlertChartsPage`.
- **Mobile entry — swipe right**: on any feed card, open or collapsed
  (`AlertCoverCard.tsx`, `variant="carousel"`, both the collapsed and
  `expanded` branches). A shared `useHorizontalSwipe(onSwipeLeft,
  onSwipeRight)` hook (touchstart/move/end, horizontal delta past a
  threshold AND greater than vertical delta, so it never fights the
  carousel's vertical scroll-snap) fires `onSwipeRight` → navigate to the
  route. The feed card only wires up the right direction. Swiping left /
  the page's own back gesture returns to the feed at the same scroll
  position (`navigate(-1)`).
- **Desktop entry**: `AlertCompanies.tsx` loses its List/Chart toggle
  (charts move off this component entirely) and gains a "Charts" button +
  right-chevron. Click triggers a right-slide transition (CSS transform,
  `motion-safe:transition-transform`) then navigates to the route. Same
  control also binds the right-arrow key when an alert is open/focused.
- The Charts button/swipe is hidden when `alert.companies.length === 0`
  (nothing to chart).

## Removal

- Delete `frontend/src/features/visualize/CompanyTree.tsx` and its test —
  full removal, not a rewrite.
- `AlertCompanies.tsx`: remove `ViewMode`/`viewMode` state and the
  List/Chart toggle entirely. It goes back to always rendering the grouped
  `CompanyChip` list (tabs + group-by select unchanged), plus the new
  Charts button. This also means the plain-text company list stays
  available as the accessible fallback view — the charts page itself
  doesn't need to duplicate a table.

## The charts page (`AlertChartsPage.tsx`)

Layout, top to bottom:
1. Persistent header: back control, category chip, article title
   (truncated), all fixed while the chart body below it changes.
2. Pager strip: 4 labels/dots — Sector · Tier · Impact · Split — indicating
   position; horizontal swipe (`useHorizontalSwipe`, both directions wired
   this time — left advances, right goes back) or tap-a-dot moves between
   them.
3. Full-bleed chart body for the active type.
4. Tapping any company mark in any chart toggles `ReasoningPanel` open
   inline, directly below/beside that mark — reusing `CompanyChip`'s own
   existing tap-to-expand pattern (not a new bottom-sheet component).

### Shared visual rules

- Bullish/bearish always render with the app's existing `text-bullish` /
  `text-bearish` tokens — never a new ad hoc color for direction.
- Dark/light both supported via the existing `theme-light:` Tailwind
  variant pattern already used throughout (`AlertCompanies.tsx`,
  `CompanyChip.tsx`).
- Sector color: replace `colors.ts`'s hash-based `sectorColor()` (arbitrary
  order, never validated) with a **fixed-order categorical palette**
  covering the backend's 10-value `SECTORS` enum
  (`oil_gas, banking, auto, it, pharma, fmcg, metals, telecom, infra,
  other`) plus a defined fallback for any other string a `Company.sector`
  might hold. Validate the palette with the `dataviz` skill's
  `scripts/validate_palette.js` for both light and dark chart surfaces
  before shipping; fix any FAIL before merge.
- No magnitude percentages are ever printed as raw numbers anywhere on the
  charts page — this already matches `ReasoningPanel`'s existing rule
  ("frequently inaccurate and would overstate precision"). Observed
  `magnitude_low`/`magnitude_high` values span roughly 0-100 with no fixed
  scale (the model self-estimates per-alert, not against a calibrated
  global range), so a fixed global threshold bucket would produce
  degenerate results within one 5-company chart (e.g. every company
  landing in the same bucket, or one outlier swallowing the whole scale).
  Instead, size bars **by relative rank within the alert's own company
  list**: sort by `(magnitude_low + magnitude_high) / 2` descending and map
  rank position to bar length (a new pure function in `transforms.ts`,
  `rankByMagnitude(companies: AlertCompany[]): AlertCompany[]`, sorted
  descending by that midpoint — bar length is then derived purely from
  each company's index in the returned array, e.g. longest for index 0,
  shortest for the last index). This is explicitly an ordinal encoding
  ("stronger than the others in this story"), never a claim about an
  absolute percentage scale.

### 1. Sector — treemap

Data: `groupBySector` (already exists, unchanged grouping logic — only the
color source changes to the fixed palette above).

Layout: one tile per sector present, sized by `companies.length` relative
to the alert's total (simple proportional grid, not a full squarified
treemap algorithm — with ≤5 companies total across ≤5 sectors a light
CSS-grid-based proportional layout is sufficient and avoids a new
dependency). Each tile: sector name header, ticker chips (ticker + ▲/▼)
for its companies.

### 2. Tier — grouped rows

Data: `groupByTier` (already exists, fixed tier order unchanged).

Layout: one row per tier present, in the existing fixed order. Each row:
tier label, a count indicator (filled/empty dots, count vs. the alert's
max-per-tier), a net-sentiment arrow (▲ if bullish > bearish in that tier,
▼ if reversed, a neutral dash if tied), and ticker chips for its companies.

### 3. Impact — diverging bar (winners/losers)

Data: all of the alert's companies, unGrouped, split at a center axis —
bearish extends left, bullish extends right — each side independently
ranked via `rankByMagnitude` (strongest nearest the center axis, weakest
at the outer edge — reads as "how far this story's conviction reaches").

Layout: horizontal bars, bar length derived from rank position (not the
raw float), 2px rounded bar ends, every bar direct-labeled with its ticker
(≤5 total companies always fits without a legend). Tapping a bar expands
that company's `ReasoningPanel` beneath it.

### 4. Split — donut + ranked list

Data: same as Impact, but the story here is composition, not per-company
magnitude: a 2-slice donut (bullish % vs. bearish % **by count**, matching
how the existing `SentimentBar`/`SentimentPill` already compute
proportions — no new counting logic), plus the full company list below the
donut ordered by `rankByMagnitude`, bullish first then bearish.

## Testing

- `rankByMagnitude()` unit tests (descending order, stable tie-break on
  equal midpoints, empty/single-company input).
- Fixed sector-palette assignment unit test (stable id → color, unknown
  sector fallback).
- `useHorizontalSwipe` hook: simulated touch sequences (horizontal past
  threshold → correct direction fires; vertical-dominant → neither fires;
  below threshold → neither fires).
- Each chart component: renders correct tile/row/bar/slice count for a
  given `AlertCompany[]` fixture; tapping a mark expands/collapses its
  `ReasoningPanel` (mirroring `CompanyChip.test.tsx`'s existing pattern).
- `AlertChartsPage`: route param → fetch-by-id on direct load; pager
  navigation between the 4 chart types; back navigation.
- Backend: `GET /api/alerts/{id}` — 200 with correct shape (parity with
  `list_alerts`'s per-alert shape), 404 for a missing id.
- Playwright visual verification (light + dark, mobile width) before
  calling any chart "aesthetic" — this is the exact bar the previous two
  attempts failed.
