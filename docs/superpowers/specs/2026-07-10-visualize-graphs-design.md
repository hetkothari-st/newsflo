# Visualize: per-alert impact tree/graph picker

## Purpose

Let a user open any alert and view its company-impact data as an interactive
tree, choosing between a small set of view types. Source spec:
`Claude_Code_Financial_News_Graph_Master_Spec.md` (10 graph/tree types over a
richer `ImpactNode`/`ImpactEdge` data model with numeric confidence scores,
time horizons, and company-to-company relationship edges).

**Scope note:** the current backend data model does not have numeric
confidence (0-100), time horizon, impact level (1-5), or any company-to-company
relationship edges (supplier/customer/competitor/etc). Building the full
10-type spec today would mean fabricating data, which violates the
non-negotiable "never fabricate" rule in the source spec. This design
implements the two view types buildable from real, already-collected data.
Remaining types (Confidence/Basis Tree, Knowledge Graph, and the true
multi-hop types) are deferred to v2, pending either richer backend data or an
explicit decision to model them from proxy fields.

## v1 scope

Two view types, selectable via a picker, rendered for a single alert at a
time:

1. **Impact Tree** — root = article title → branches = Bullish / Bearish →
   leaves = companies (ticker, name, rationale on select). Companies with no
   `direction` are excluded, not shown as fabricated "neutral".
2. **Sector Tree** — root = article title → branches = one per distinct
   sector present among the alert's companies → leaves = companies. Companies
   with no sector are grouped under "Other".

v2 (not built now): Confidence/Basis Tree, Knowledge Graph (node-link,
event-centered), and any spec types that require new backend modeling
(numeric confidence, time horizon, company-relationship edges).

## Data flow

No new fetches. Both views consume the `AlertCompany[]` already present on a
loaded `Alert` (from `getAlerts()` / the WS live feed), transformed client-side
into a tree structure and handed to the renderer.

### Backend change (additive only)

`AlertCompany` does not currently expose `sector` (only the `Company` table
has it). Add `"sector": ac.company.sector` to the two places that already
serialize an `AlertCompany` dict:

- `backend/app/routers/alerts.py` — `list_alerts` company dict
- `backend/app/pipeline.py` — `_alert_broadcast_payload` company dict

This is a pure additive field on an existing dict literal in each place — no
existing logic, query, or field is touched. Frontend `AlertCompany` /
`WsAlertCompany` types in `frontend/src/lib/api.ts` gain `sector: string`.

No other backend files are touched. This avoids collision with other
concurrent sessions working in `backend/app/companies/`, `backend/app/analysis/`.

## Frontend architecture

New module: `frontend/src/features/visualize/`

- `VisualizeModal.tsx` — full-screen overlay. Opened via a new "Visualize"
  button added to the expanded state of `AlertCard.tsx` (existing
  expand/collapse pattern, no new route).
- `ViewPicker.tsx` — segmented control (Impact Tree | Sector Tree).
- `ImpactTree.tsx`, `SectorTree.tsx` — thin components that call the matching
  transform and render the shared `TreeCanvas`.
- `TreeCanvas.tsx` — react-flow wrapper, shared by both view types.
- `transforms.ts` — pure functions `AlertCompany[] -> { nodes, edges }`
  (react-flow shape). One function per view type. Unit-testable with plain
  fixture arrays, no React involved.
- `treeLayout.ts` — pure layout function assigning x/y to a 3-level tree
  (root / branch / leaf).

### Library

Add `reactflow` (npm) as the only new dependency. It provides pan/zoom/
minimap/fit-view out of the box (matches the source spec's UI requirements),
uses a React-native node/edge model that covers both tree layouts now and a
node-link Knowledge Graph later, and is actively maintained. A hand-rolled
SVG tree was considered but rejected — it would mean re-implementing pan/zoom
for no benefit given react-flow already fits both v1 and v2 needs.

## Visual design

Full-screen dark overlay (`bg-page/95` + backdrop blur) consistent with the
existing card aesthetic (`bg-surface`/`border-hairline`/`font-display`
tokens already in `tailwind.config.ts` — the app is already dark-themed, no
new tokens needed):

- Header: article title, `ViewPicker` segmented control, close button.
- Root node: `bg-surface border-hairline`.
- Branch nodes: Impact Tree uses existing `bullish`/`bearish` colors; Sector
  Tree uses a deterministic hash-to-palette function over sector names
  (consistent color per sector, no fabricated meaning).
- Leaf nodes: mini card in the same visual language as `CompanyChip`
  (ticker, name, direction arrow).
- Selecting a leaf opens a side panel that reuses the existing
  `ReasoningPanel` component as-is (rationale + calibration precedent line) —
  no duplication of that logic.
- Pan/zoom via react-flow controls; fit-to-view on open and on view-type
  switch; react-flow's built-in transition animates the re-layout.

## Error handling / edge cases

- Alert with zero companies → empty-state message inside the modal, no crash.
- Company missing `sector` (pre-migration data) → grouped under "Other".
- Company missing `direction` → excluded from Impact Tree only (Sector Tree
  is unaffected since it doesn't depend on direction).

## Testing

- `transforms.test.ts` — pure function tests over fixture `AlertCompany[]`
  arrays: correct grouping, "Other"/exclusion edge cases.
- `VisualizeModal.test.tsx` — opens from `AlertCard`, switches between the two
  views, renders expected node counts for a fixture alert.
- Backend: extend existing `routers/alerts.py` and `pipeline.py` tests to
  assert `sector` is present in the serialized company dict.

## Isolation from concurrent work

Other Claude sessions are active in `worktree-newsflo-core-pipeline` and
`worktree-newsflo-feed-tabs`, and `master` itself has uncommitted changes in
`AlertCard.tsx`, `vite.config.ts`, and `backend/app/companies/loader.py` from
other in-progress work. This feature will be implemented in its own git
worktree/branch to avoid touching those in-flight files, and the two backend
edits are additive one-liners in files (`routers/alerts.py`, `pipeline.py`)
not currently being edited by the other sessions, minimizing merge risk.
