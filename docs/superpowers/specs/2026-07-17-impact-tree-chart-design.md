# Impact Tree Chart — Design

## Goal

Rebuild the first chart in `AlertChartsPage` (currently blank below the stat
bar, since the blank-slate wipe in `9541ece`): a "Multi-Level Impact Tree"
showing the news at top, then a sector → company → sub-sector → company
cascade below it, so a user can visually trace how one news item ripples
through direct and indirect holdings.

This supersedes `2026-07-17-affected-companies-charts-redesign-design.md`'s
chart #4 mapping (which restyled `TierRows.tsx` around `impact_level` +
`parent_company_id`, capped at 2 levels since the model has no L3+). That
spec predates the blank-slate wipe and is treated as superseded, not
authoritative. This spec instead groups by **sector fields already on
`Company`** to get 4 real levels, per explicit user direction — see
"Data model gap" below.

## Data model gap (accepted trade-off)

The schema has no literal "sector affected" or "sub-sector affected" node —
`sector`/`sub_sector` are plain fields on `Company`, and `impact_level`
(direct/indirect_l1/indirect_l2) is a causal-distance field on
`AlertCompany`, orthogonal to sector grouping. There is no single field that
produces "sectors → companies → sub-sectors → companies" as a native
hierarchy. This spec derives it by:

- Level 1/2 (direct impact): companies where `impactLevelKey(c) === 'direct'`,
  grouped by `sector`.
- Level 3/4 (indirect ripple): companies where `impactLevelKey(c) !== 'direct'`
  (i.e. `indirect_l1` or `indirect_l2` collapsed together), grouped by
  `sub_sector` (fallback to `sector` if `sub_sector` is null).

This is a real-data derivation, not fabrication — every card traces to an
actual `AlertCompany` row. It does mean Level 3/4 mixes `indirect_l1` and
`indirect_l2` companies together (no separate 5th level for l2), which is an
accepted simplification given the user's 4-level ask.

No "wider market impact" / index level (as shown in the reference image's
Level 4) is included — the app has no per-alert index price-change data, and
inventing one would violate the real-data-only requirement.

## Components

- **New:** `frontend/src/features/visualize/charts/ImpactTree.tsx` — the
  chart itself.
- **New transform:** `groupIndirectBySubSector(companies: AlertCompany[])` in
  `frontend/src/features/visualize/transforms.ts` — filters to
  `impactLevelKey(c) !== 'direct'`, groups by `c.sub_sector ?? c.sector`.
  Mirrors the existing `groupBySector` shape (`{ key, companies }[]`).
- **Reused as-is:** `ChartCardShell` (numbered badge/title/description
  header), `groupBySector` (existing transform), `impactLevelKey` (existing
  helper), `bullish`/`bearish` CSS vars, `font-editorial`/`font-data` tokens,
  hairline border classes — all per existing conventions, no new deps.
- **Wiring:** `AlertChartsPage.tsx` renders `<ImpactTree alert={alert} />` in
  place of the current trailing `<div className="flex-1" />`, inside the
  existing `ChartCardShell`.

No chart library is introduced — hand-rolled Tailwind/CSS layout, consistent
with the rest of the app ("no SVG node-link diagrams" convention already
established for this codebase).

## Data flow

1. `AlertChartsPage` already has `alert.companies: AlertCompany[]` from
   `getAlert()`.
2. Split: `direct = companies.filter(c => impactLevelKey(c) === 'direct')`,
   `indirect = companies.filter(c => impactLevelKey(c) !== 'direct')`.
3. `direct` → `groupBySector(direct)` → sector blocks (Level 1 header +
   Level 2 company cards, per block).
4. `indirect` → `groupIndirectBySubSector(indirect)` → sub-sector blocks
   (Level 3 header + Level 4 company cards, per block).
5. Render top-to-bottom: News node → Level 1/2 sector blocks (repeated per
   sector) → divider → Level 3/4 sub-sector blocks (repeated per sub-sector).

## Visual design

- **News node:** top of tree, bordered card (`border-hairline`), article
  title in `font-editorial`, source + relative time in `font-data
  text-[11px] uppercase tracking-widest text-muted` — same meta-line pattern
  as `InsightCard`.
- **Connectors:** thin vertical hairline + small `▼` glyph between levels.
  No SVG, no computed curves — straight CSS lines/borders only.
- **Level header pills:** `font-data text-[11px] uppercase tracking-widest
  text-muted` label ("LEVEL 1 · DIRECT IMPACT", "LEVEL 3 · INDIRECT IMPACT"),
  sector/sub-sector name + company count, `border border-hairline` card.
- **Company cards:** ticker in bold `font-data`, name in small
  `font-editorial`, direction glyph `▲`/`▼` (no emoji), magnitude % in
  `text-bullish`/`text-bearish` — matches `InsightCard`'s existing visual
  language exactly.
- Each sector/sub-sector block stacks its header pill directly above its own
  company row/grid, so the sector→company (and sub-sector→company)
  relationship reads clearly even with multiple sectors present.
- Fully themed via existing CSS vars — no new colors invented. Dark default +
  `.light` neumorphic variant both supported, per
  `2026-07-13-light-mode-neumorphic-design.md` conventions.
- Always fully expanded, page scrolls vertically — matches reference image,
  no collapse/expand interaction in this version.

## Empty / error handling

- No indirect companies for this alert → Level 3/4 section is omitted
  entirely, replaced by one muted `font-data` note: "No indirect ripple
  effects identified."
- No direct companies (defensive; shouldn't occur in practice) → Level 1/2
  blocks omitted with an equivalent muted note.
- Alert fetch failure is already handled upstream in `AlertChartsPage` — no
  new error handling needed in `ImpactTree` itself.

## Testing

- Vitest unit tests for `groupIndirectBySubSector`: fallback-to-sector when
  `sub_sector` is null, empty-array input, mixed `indirect_l1`/`indirect_l2`
  companies grouping together.
- Manual browser check (per project convention, no automated visual/E2E
  suite exists for charts): one alert with both direct and indirect
  companies, one direct-only alert, both dark and light theme.
