# Visualize v2: inline company-list grouping (supersedes the graph-canvas design)

## Why this supersedes the original design

The original `2026-07-10-visualize-graphs-design.md` shipped a separate
full-screen modal with a `reactflow` node-link canvas (Impact Tree / Sector
Tree). In production it failed on every axis:

- **Theme**: hardcoded dark colors, breaking badly against the app's newer
  light/dark theme system (CSS-variable tokens + `.light` class), which did
  not exist when the original design was written.
- **Aesthetic**: squiggly bezier connector lines, plain react-flow default
  chrome (zoom buttons, background dots), poor typographic hierarchy.
- **Use case**: for the common single-company alert, the canvas renders a
  near-empty root → one branch → one leaf tree that fills the whole screen
  with no more information than the already-visible company chip.
- **Interaction model**: a pan/zoom canvas is a poor fit for the mobile-first
  context this app actually runs in.

This v2 design replaces the canvas entirely with a **grouping mode on the
existing company list** inside `AlertCompanies.tsx` — no separate screen, no
node-link rendering library, no canvas.

## Core idea

`AlertCompanies` already renders a grouped-list-with-headers (grouped by
index tier, e.g. "Nifty 50" / "Nifty Next 50" / ...). This design generalizes
that to a **"Group by" selector** offering three groupings of the exact same
`CompanyChip` rows:

- **Tier** (today's default and only mode — unchanged)
- **Impact** — grouped into "Bullish" / "Bearish" sections
- **Sector** — grouped by `company.sector`, alphabetical, "Other" fallback
  for missing/blank sector

Switching groupings re-buckets and re-heads the same rows in place. No modal,
no new screen, no canvas.

## What gets deleted

- `frontend/src/features/visualize/TreeCanvas.tsx` (+ test)
- `frontend/src/features/visualize/TreeView.tsx` (+ test)
- `frontend/src/features/visualize/treeLayout.ts` (+ test)
- `frontend/src/features/visualize/tree.ts`
- `frontend/src/features/visualize/VisualizeModal.tsx` (+ test)
- `frontend/src/features/visualize/ViewPicker.tsx` (+ test)
- The `reactflow` npm dependency (removed from `package.json`)
- The "Visualize →" button and its `visualizeOpen` state in
  `AlertCompanies.tsx`
- The ResizeObserver test polyfill in `frontend/src/test/setup.ts` (added
  solely for react-flow's jsdom compatibility — no longer needed once
  react-flow is gone; the scrollTo polyfill added independently by another
  session stays)

## What gets kept and repurposed

- `frontend/src/features/visualize/colors.ts` (`sectorColor`) — still needed
  for sector group header dots. Unchanged.
- The grouping logic in `transforms.ts` — the bullish/bearish split, the
  sector "Other" fallback, and the alphabetical sector sort are all correct
  and stay, but the functions are rewritten to return plain grouped arrays
  instead of a `TreeNodeData` tree (react-flow shape). New signature:

```ts
export interface CompanyGroup {
  key: string;
  label: string;
  color?: string; // sector dot color; undefined for tier/impact groups
  companies: AlertCompany[];
}

export function groupByImpact(companies: AlertCompany[]): CompanyGroup[];
export function groupBySector(companies: AlertCompany[]): CompanyGroup[];
```

`groupByImpact` excludes companies whose `direction` is neither `'bullish'`
nor `'bearish'` (unchanged no-fabrication behavior). `groupBySector` keeps
the existing "Other" fallback for missing/blank sector and alphabetical sort.
An empty group (zero companies) is never included (unchanged).

- The existing tier-grouping logic already in `AlertCompanies.tsx` becomes
  `groupByTier(companies: AlertCompany[]): CompanyGroup[]`, moved out of the
  component into `frontend/src/features/visualize/transforms.ts` so all
  three groupings live together with one shared `CompanyGroup` shape and one
  shared rendering path in the component.

## Visual design

**"Group by" control**: a small native `<select>` (not a segmented button
row — three extra buttons don't reliably fit next to the existing
"Predicted" / "My Portfolio" tabs on a 360-390px mobile viewport), styled to
match existing form controls, placed where the "Visualize →" button used to
sit (right side of the existing tab row, same row, `justify-between`).
Options: "Tier" (default) / "Impact" / "Sector".

**Group headers**:
- Tier: unchanged — plain uppercase muted label (e.g. "Nifty 50").
- Impact: `"Bullish · 4"` / `"Bearish · 2"`, header text colored with the
  existing `text-bullish`/`text-bearish` tokens (already theme-aware via
  CSS variables — correct in light and dark automatically).
- Sector: sector name + count, with the existing colored-dot convention
  (same visual pattern as `CategorySwatch` and `CompanyChip`'s avatar
  colors) using `sectorColor()`, e.g. `● Energy · 3`.

**Conviction, honestly**: in Impact and Sector modes only (not Tier, which
carries no direction/basis meaning), each `CompanyChip` row is wrapped with
`opacity-100` when `company.basis === 'direct_mention'` and `opacity-70`
when `company.basis === 'sector_inference'` — a real, already-collected
signal (not a fabricated confidence bar). `CompanyChip` itself is not
modified; the opacity is applied by the wrapping `<div>` in
`AlertCompanies.tsx`, keeping the change isolated from the shared,
widely-used `CompanyChip` component and its existing tests.

**Colors**: every color used is either an existing CSS-variable token
(`text-bullish`, `text-bearish`, `text-ink`, `text-muted`) — automatically
correct in both themes — or the existing `sectorColor()` swatch-dot
convention, which (like `CategorySwatch` and `CompanyChip`'s avatar colors)
is intentionally theme-invariant, used only as a small dot, never a full
background wash, so it never needs separate light/dark tuning.

## Testing

- `transforms.test.ts`: rewritten for `groupByImpact`/`groupBySector`
  returning `CompanyGroup[]` (same test cases as before — bullish/bearish
  split, empty-branch omission, direction exclusion, sector grouping,
  alphabetical order, "Other" fallback — updated for the new return shape).
- New `groupByTier` gets its own tests (moved out of `AlertCompanies.test.tsx`
  where tier ordering was previously exercised only indirectly).
- `AlertCompanies.test.tsx`: existing tests stay (they exercise Tier mode,
  which is unchanged); new tests cover switching to Impact/Sector mode,
  correct group headers/counts, and the basis-driven opacity wrapper.
- Delete: `TreeCanvas.test.tsx`, `TreeView.test.tsx`, `treeLayout.test.ts`,
  `VisualizeModal.test.tsx`, `ViewPicker.test.tsx` (all test the removed
  canvas code).
- The `frontend/src/test/setup.ts` ResizeObserver polyfill removal needs no
  test of its own — its only purpose was making the now-deleted react-flow
  tests pass in jsdom.

## Isolation from concurrent work

Other sessions are actively shipping the light/dark theme system and further
`AlertCompanies.tsx`/tier-grouping changes directly on `master` right now.
This work will be done in its own git worktree/branch, merged into master
only after the branch is rebased onto the latest master and verified there,
matching the process used for the original visualize-graphs branch.
