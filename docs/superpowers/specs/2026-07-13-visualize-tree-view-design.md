# Visualize: Chart (tree) view alongside the list

## Why

After the v2 redesign shipped as a text-only grouped list, the user asked for the
original tree/graph structures back — but as an additional view, not a
replacement, and rebuilt properly this time (the original `reactflow` canvas
had jsdom test crashes, hardcoded-dark theming that broke against the app's
light/dark system, and squiggly bezier edges).

## Decision: hand-rolled SVG, no library

No new dependency. A plain, static SVG tree — no pan/zoom needed, since alert
company counts are small enough to fit without it. This avoids every failure
mode the previous `reactflow` attempt hit (jsdom/d3-drag crashes, canvas
theme mismatches, bundle weight).

## Data reuse

The tree consumes the exact same `CompanyGroup[]` that `groupByTier` /
`groupByImpact` / `groupBySector` (in `transforms.ts`, unchanged) already
produce for the list view. No new grouping logic — the "Group by" selector
already in `AlertCompanies.tsx` now drives both the list AND the tree.

`GroupMode` (`'tier' | 'impact' | 'sector'`) moves from being declared inline
in `AlertCompanies.tsx` to `transforms.ts`, so the new tree component can
import it without a component-to-component type import.

## Layout: column-per-branch, not row-per-leaf

The original design's failure mode was leaves spreading horizontally under
each branch — width blew up with company count, forcing pan/zoom. This
design instead lays branches out **side by side as columns**, with each
branch's companies **stacked vertically beneath their own column**. Width is
therefore bounded by branch count (small — at most a handful of tiers,
2 impact buckets, or a handful of sectors); only height grows with company
count, and the page already scrolls vertically.

- Root: article title, centered at the top, small `text-muted` label.
- One column per group (branch), each headed by its group label (same
  header content/coloring already used for the list's group headers: sector
  dot, `text-bullish`/`text-bearish` for Impact, plain `text-muted` for
  Tier).
- Under each branch column, its companies stacked vertically as compact leaf
  marks (direction arrow + ticker — not the full `CompanyChip`, to stay
  visually compact in a tree).
- Straight `stroke-hairline` lines connect root → branch and run down each
  branch's column through its leaves (a single trunk line per column, not a
  separate line per leaf) — clean and legible, not the old squiggly bezier
  curves.
- All colors via existing Tailwind color tokens applied directly to SVG
  elements (`fill-`/`stroke-` utilities read from the same `theme.colors` as
  `bg-`/`text-`, so `stroke-bullish`, `fill-surface`, `stroke-hairline` etc.
  all resolve to the same theme-aware CSS variables already used elsewhere —
  automatically correct in light and dark).

## Interaction

Clicking a leaf reveals the existing `ReasoningPanel` component (unmodified,
reused exactly as the list view already does via `CompanyChip`'s built-in
expand) inline below the tree — same rationale-on-demand pattern as before,
just triggered from an SVG leaf instead of a chip.

## Entry point

A "List | Chart" two-option toggle, its own row, placed below the existing
tabs/Group-by row and the `SentimentBar`. Defaults to List. Switching to
Chart renders the same `grouped` array (already computed for the list) via
the new tree component instead of the existing grouped-rows markup — no
change to how `grouped` itself is computed.

## Testing

- New `CompanyTree.tsx` component test: renders root label, one node per
  branch and per company, computes plausible relative positions (branch
  nodes above their own leaves, distinct x per branch column), clicking a
  leaf reveals its `ReasoningPanel` content.
- `AlertCompanies.test.tsx`: new tests for the List/Chart toggle switching
  the rendered content; existing List-mode tests unchanged.
- Visual verification: rendered live via `npm run dev` and inspected with
  Playwright at both a narrow mobile width and in both light/dark theme
  before considering this feature done — the exact verification step this
  feature exists to make up for skipping the first time.

## Isolation

Built in its own worktree, per this project's established pattern for
concurrent-session safety.
