# Visualize (Impact/Sector Tree) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Visualize" button to the expanded `AlertCard` that opens a full-screen modal where the user picks between an Impact Tree (Bullish/Bearish split) and a Sector Tree, both rendered as interactive pan/zoom node graphs of that alert's real company data.

**Architecture:** Frontend-only feature module at `frontend/src/features/visualize/` built on `reactflow` for the node/edge canvas. Pure functions turn `AlertCompany[]` into a generic `TreeNodeData` tree (`transforms.ts`), then a pure layout function turns that into react-flow `{nodes, edges}` (`treeLayout.ts`). One backend change: add the already-existing `sector` column to the two places that serialize `AlertCompany` (REST + WebSocket), since the Sector Tree needs it and it isn't currently exposed.

**Tech Stack:** React 18 + TypeScript + Vite + Tailwind (existing). New dependency: `reactflow` (^11.11.4). Backend: FastAPI + SQLAlchemy (existing, additive change only).

## Global Constraints

- Never fabricate data: only fields the backend actually returns may drive a view. Companies missing a required field for a given view (e.g. no recognized `direction` for the Impact Tree) are excluded from that view, never shown as a fabricated "neutral"/default.
- Distinguish direct vs. inferred impact where the data already encodes it (`basis: direct_mention | sector_inference`) — do not blur this distinction in new UI copy.
- Dark theme, existing Tailwind tokens only (`bg-page`, `bg-surface`, `border-hairline`, `text-ink`, `text-muted`, `text-bullish`, `text-bearish`, `font-display`) — no new color tokens except the sector palette defined in this plan.
- Pan and zoom must work on every graph/tree view (source spec UI requirement) — satisfied by react-flow's built-in `Controls` + `fitView`.
- This work happens in the isolated worktree at `C:\Users\ST269\Desktop\newsflo\.claude\worktrees\visualize-graphs` (branch `worktree-visualize-graphs`), created to avoid colliding with other concurrent sessions' uncommitted changes on `master` and their own worktrees (`worktree-newsflo-core-pipeline`, `worktree-newsflo-feed-tabs`). All file paths below are relative to that worktree root unless stated otherwise.
- `sector` is added as an **optional** field (`sector?: string`) on the frontend `AlertCompany`/`WsAlertCompany` types, not required — this avoids having to edit every existing test fixture literal across the frontend test suite (7 files currently construct `AlertCompany` objects), keeping this feature's diff isolated from files other sessions may be mid-editing.

---

### Task 1: Backend — expose `sector` on the REST alerts response

**Files:**
- Modify: `backend/app/routers/alerts.py:34` (inside the `companies` list comprehension, after the `index_tier` key)
- Test: `backend/tests/test_api.py` (new test, appended after `test_list_alerts_flags_in_my_holdings_for_authenticated_holder`)

**Interfaces:**
- Produces: `GET /api/alerts` response `companies[].sector: str` — consumed by the frontend `AlertCompany` type in Task 3.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_api.py`, after `test_list_alerts_flags_in_my_holdings_for_authenticated_holder`:

```python
def test_list_alerts_includes_company_sector(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    article = Article(
        source="test", url="https://example.com/sector", title="Sector test headline",
        status="ANALYZED", category="oil_energy",
    )
    db_session.add(article)
    db_session.commit()

    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()

    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin",
        basis="direct_mention", confidence="llm_estimate",
    ))
    db_session.commit()

    response = client.get("/api/alerts")

    assert response.status_code == 200
    assert response.json()[0]["companies"][0]["sector"] == "oil_gas"

    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"C:\Users\ST269\Desktop\newsflo\backend\.venv\Scripts\python.exe" -m pytest tests/test_api.py::test_list_alerts_includes_company_sector -v` (from the worktree's `backend/` directory)
Expected: FAIL with `KeyError: 'sector'`

- [ ] **Step 3: Implement**

In `backend/app/routers/alerts.py`, in the `companies` list comprehension inside `list_alerts`, add the `sector` key right after `index_tier`:

```python
        "companies": [{
            "company_id": ac.company_id, "ticker": ac.company.ticker, "name": ac.company.name,
            "index_tier": ac.company.index_tier, "sector": ac.company.sector,
            "direction": ac.direction,
            "magnitude_low": ac.magnitude_low, "magnitude_high": ac.magnitude_high,
            "rationale": ac.rationale, "basis": ac.basis, "confidence": ac.confidence,
            "market": infer_market(ac.company.ticker),
            "in_my_holdings": ac.company_id in held_company_ids,
        } for ac in alert.companies],
```

- [ ] **Step 4: Run test to verify it passes**

Run: `"C:\Users\ST269\Desktop\newsflo\backend\.venv\Scripts\python.exe" -m pytest tests/test_api.py -v` (from `backend/`)
Expected: all tests in the file PASS, including `test_list_alerts_includes_company_sector`

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/alerts.py backend/tests/test_api.py
git commit -m "feat: expose company sector on GET /api/alerts"
```

---

### Task 2: Backend — expose `sector` on the WebSocket broadcast payload

**Files:**
- Modify: `backend/app/pipeline.py:39` (inside `_alert_broadcast_payload`, after the `index_tier` key)
- Test: `backend/tests/test_pipeline.py` (new test, appended at end of file)

**Interfaces:**
- Produces: WS-pushed alert `companies[].sector: str` — consumed by the frontend `WsAlertCompany` type (derived from `AlertCompany` in Task 3, so no separate frontend change needed).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_pipeline.py`:

```python
def test_alert_broadcast_payload_includes_sector(db_session):
    company = Company(ticker="RELIANCE.NS", name="Reliance Industries", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0)
    db_session.add(company)
    db_session.commit()

    article = Article(source="test", url="https://example.com/broadcast-sector", title="Sector broadcast test")
    db_session.add(article)
    db_session.commit()

    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()

    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin",
        basis="direct_mention", confidence="llm_estimate",
    ))
    db_session.commit()
    db_session.refresh(alert)

    payload = pipeline_module._alert_broadcast_payload(alert)

    assert payload["companies"][0]["sector"] == "oil_gas"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `"C:\Users\ST269\Desktop\newsflo\backend\.venv\Scripts\python.exe" -m pytest tests/test_pipeline.py::test_alert_broadcast_payload_includes_sector -v` (from `backend/`)
Expected: FAIL with `KeyError: 'sector'`

- [ ] **Step 3: Implement**

In `backend/app/pipeline.py`, inside `_alert_broadcast_payload`, add `sector` after `index_tier`:

```python
        "companies": [{
            "company_id": ac.company_id,
            "ticker": ac.company.ticker,
            "name": ac.company.name,
            "index_tier": ac.company.index_tier,
            "sector": ac.company.sector,
            "direction": ac.direction,
            "magnitude_low": ac.magnitude_low,
            "magnitude_high": ac.magnitude_high,
            "rationale": ac.rationale,
            "basis": ac.basis,
            "confidence": ac.confidence,
            "market": infer_market(ac.company.ticker),
        } for ac in alert.companies],
```

- [ ] **Step 4: Run test to verify it passes**

Run: `"C:\Users\ST269\Desktop\newsflo\backend\.venv\Scripts\python.exe" -m pytest tests/test_pipeline.py -v` (from `backend/`)
Expected: all tests in the file PASS

- [ ] **Step 5: Run the full backend suite**

Run: `"C:\Users\ST269\Desktop\newsflo\backend\.venv\Scripts\python.exe" -m pytest -q` (from `backend/`)
Expected: `144 passed` (143 existing + 1 new; Task 1 already added its own)

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipeline.py backend/tests/test_pipeline.py
git commit -m "feat: expose company sector on the live alert WebSocket broadcast"
```

---

### Task 3: Frontend — add `sector` to the `AlertCompany` type

**Files:**
- Modify: `frontend/src/lib/api.ts:10-23` (the `AlertCompany` interface)

**Interfaces:**
- Produces: `AlertCompany.sector?: string` and (via the existing `Omit`) `WsAlertCompany.sector?: string` — consumed by `buildSectorTree` in Task 8.

- [ ] **Step 1: Add the field**

In `frontend/src/lib/api.ts`, add `sector` to the `AlertCompany` interface, right after `index_tier`:

```ts
export interface AlertCompany {
  company_id: number;
  ticker: string;
  name: string;
  index_tier: string; // NIFTY50 | NIFTY100 | NIFTY500 | GLOBAL_LARGE_CAP | OTHER
  sector?: string;
  direction: string; // bullish | bearish
  magnitude_low: number;
  magnitude_high: number;
  rationale: string;
  basis: string; // direct_mention | sector_inference
  confidence: string; // llm_estimate | calibrated
  market: 'IN' | 'GLOBAL';
  in_my_holdings: boolean;
}
```

- [ ] **Step 2: Verify the frontend still typechecks and all existing tests still pass**

Run (from `frontend/`): `npx tsc --noEmit`
Expected: no errors

Run: `npm test`
Expected: `20 passed (20)` test files, `84 passed` tests — unchanged from baseline (the field is optional, so no existing fixture breaks)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat: add optional sector field to the AlertCompany type"
```

---

### Task 4: Frontend — add the `reactflow` dependency

**Files:**
- Modify: `frontend/package.json`, `frontend/package-lock.json` (via npm, not hand-edited)

**Interfaces:**
- Produces: the `reactflow` package (default export `ReactFlow`, plus `Background`, `Controls`, `Handle`, `Position`, and types `Node`, `Edge`, `NodeProps`) — consumed by `TreeCanvas.tsx` in Task 9.

- [ ] **Step 1: Install**

Run (from `frontend/`): `npm install reactflow@^11.11.4`
Expected: `package.json` gains a `"reactflow": "^11.11.4"` dependency entry; `package-lock.json` updates.

- [ ] **Step 2: Verify the app still builds and tests still pass**

Run: `npx tsc --noEmit`
Expected: no errors

Run: `npm test`
Expected: `84 passed` (unchanged — nothing imports `reactflow` yet)

- [ ] **Step 3: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "chore: add reactflow dependency for the visualize feature"
```

---

### Task 5: Frontend — deterministic sector color helper

**Files:**
- Create: `frontend/src/features/visualize/colors.ts`
- Test: `frontend/src/features/visualize/colors.test.ts`

**Interfaces:**
- Produces: `sectorColor(sector: string): string` (hex color) — consumed by `transforms.ts` in Task 8.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/visualize/colors.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { sectorColor } from './colors';

describe('sectorColor', () => {
  it('returns the same color for the same sector every time', () => {
    expect(sectorColor('Technology')).toBe(sectorColor('Technology'));
  });

  it('returns a hex color string', () => {
    expect(sectorColor('Energy')).toMatch(/^#[0-9A-Fa-f]{6}$/);
  });

  it('can return different colors for different sectors', () => {
    const colors = new Set(['Technology', 'Energy', 'Financials', 'Healthcare', 'Industrials'].map(sectorColor));
    expect(colors.size).toBeGreaterThan(1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npx vitest run src/features/visualize/colors.test.ts`
Expected: FAIL — `colors.ts` does not exist

- [ ] **Step 3: Implement**

Create `frontend/src/features/visualize/colors.ts`:

```ts
// Same deterministic hash-to-palette approach as CompanyChip's avatarColor,
// duplicated here (not imported) so this feature's diff stays isolated from
// components other sessions may be mid-editing.
const SECTOR_PALETTE = [
  '#F5A623', // amber
  '#4A90D9', // blue
  '#2DD4BF', // teal
  '#E85D4C', // red-orange
  '#9B7EDE', // violet
  '#5FB878', // green
  '#D4708C', // rose
  '#6C8CD5', // indigo
];

export function sectorColor(sector: string): string {
  let hash = 0;
  for (let i = 0; i < sector.length; i++) hash = (hash * 31 + sector.charCodeAt(i)) >>> 0;
  return SECTOR_PALETTE[hash % SECTOR_PALETTE.length];
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/features/visualize/colors.test.ts`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/visualize/colors.ts frontend/src/features/visualize/colors.test.ts
git commit -m "feat: add deterministic sector color helper for the visualize feature"
```

---

### Task 6: Frontend — generic tree data types

**Files:**
- Create: `frontend/src/features/visualize/tree.ts`

**Interfaces:**
- Produces: `TreeLeafMeta`, `TreeNodeData` types — consumed by `transforms.ts` (Task 8), `treeLayout.ts` (Task 7), `TreeCanvas.tsx` (Task 9).

- [ ] **Step 1: Create the types**

Create `frontend/src/features/visualize/tree.ts`:

```ts
export interface TreeLeafMeta {
  companyId: number;
  ticker: string;
  name: string;
  direction: string;
  rationale: string;
}

export interface TreeNodeData {
  id: string;
  label: string;
  kind: 'root' | 'branch' | 'leaf';
  color?: string;
  leaf?: TreeLeafMeta;
  children: TreeNodeData[];
}
```

- [ ] **Step 2: Verify it compiles**

Run (from `frontend/`): `npx tsc --noEmit`
Expected: no errors (this file has no runtime behavior to test; its correctness is verified by the consumers in later tasks)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/visualize/tree.ts
git commit -m "feat: add generic tree node type for the visualize feature"
```

---

### Task 7: Frontend — pure tree layout function

**Files:**
- Create: `frontend/src/features/visualize/treeLayout.ts`
- Test: `frontend/src/features/visualize/treeLayout.test.ts`

**Interfaces:**
- Consumes: `TreeNodeData` from `tree.ts` (Task 6)
- Produces: `layoutTree(root: TreeNodeData): { nodes: Node[]; edges: Edge[] }` (react-flow's `Node`/`Edge` types) — consumed by `TreeView.tsx` in Task 11.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/visualize/treeLayout.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { layoutTree } from './treeLayout';
import type { TreeNodeData } from './tree';

function leaf(id: string, label: string): TreeNodeData {
  return { id, label, kind: 'leaf', children: [] };
}

describe('layoutTree', () => {
  it('places a lone root with no children at the origin', () => {
    const { nodes, edges } = layoutTree({ id: 'root', label: 'Event', kind: 'root', children: [] });
    expect(nodes).toHaveLength(1);
    expect(nodes[0].position).toEqual({ x: 0, y: 0 });
    expect(edges).toHaveLength(0);
  });

  it('produces one node per tree node and one edge per parent-child link', () => {
    const tree: TreeNodeData = {
      id: 'root', label: 'Event', kind: 'root',
      children: [
        { id: 'b1', label: 'Bullish', kind: 'branch', children: [leaf('c1', 'Co1'), leaf('c2', 'Co2')] },
        { id: 'b2', label: 'Bearish', kind: 'branch', children: [leaf('c3', 'Co3')] },
      ],
    };
    const { nodes, edges } = layoutTree(tree);
    expect(nodes).toHaveLength(6);
    expect(edges).toHaveLength(5);
    expect(edges.map((e) => e.id)).toContain('root->b1');
  });

  it('increases y with depth so levels stack top to bottom', () => {
    const tree: TreeNodeData = {
      id: 'root', label: 'Event', kind: 'root',
      children: [{ id: 'b1', label: 'Bullish', kind: 'branch', children: [leaf('c1', 'Co1')] }],
    };
    const { nodes } = layoutTree(tree);
    const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
    expect(byId.root.position.y).toBeLessThan(byId.b1.position.y);
    expect(byId.b1.position.y).toBeLessThan(byId.c1.position.y);
  });

  it('centers a branch node above the midpoint of its leaves', () => {
    const tree: TreeNodeData = {
      id: 'root', label: 'Event', kind: 'root',
      children: [{ id: 'b1', label: 'Bullish', kind: 'branch', children: [leaf('c1', 'Co1'), leaf('c2', 'Co2')] }],
    };
    const { nodes } = layoutTree(tree);
    const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
    expect(byId.b1.position.x).toBe((byId.c1.position.x + byId.c2.position.x) / 2);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npx vitest run src/features/visualize/treeLayout.test.ts`
Expected: FAIL — `treeLayout.ts` does not exist

- [ ] **Step 3: Implement**

Create `frontend/src/features/visualize/treeLayout.ts`:

```ts
import type { Node, Edge } from 'reactflow';
import type { TreeNodeData } from './tree';

const LEAF_WIDTH = 220;
const LEVEL_HEIGHT = 160;

export function layoutTree(root: TreeNodeData): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  let nextLeafX = 0;

  function place(node: TreeNodeData, depth: number): number {
    if (node.children.length === 0) {
      const x = nextLeafX;
      nextLeafX += LEAF_WIDTH;
      nodes.push(toFlowNode(node, x, depth));
      return x;
    }
    const childXs = node.children.map((child) => place(child, depth + 1));
    const x = (childXs[0] + childXs[childXs.length - 1]) / 2;
    nodes.push(toFlowNode(node, x, depth));
    for (const child of node.children) {
      edges.push({ id: `${node.id}->${child.id}`, source: node.id, target: child.id });
    }
    return x;
  }

  place(root, 0);
  return { nodes, edges };
}

function toFlowNode(node: TreeNodeData, x: number, depth: number): Node {
  return {
    id: node.id,
    type: node.kind,
    position: { x, y: depth * LEVEL_HEIGHT },
    data: { label: node.label, color: node.color, leaf: node.leaf },
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/features/visualize/treeLayout.test.ts`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/visualize/treeLayout.ts frontend/src/features/visualize/treeLayout.test.ts
git commit -m "feat: add pure tree layout function for the visualize feature"
```

---

### Task 8: Frontend — Impact Tree and Sector Tree transforms

**Files:**
- Create: `frontend/src/features/visualize/transforms.ts`
- Test: `frontend/src/features/visualize/transforms.test.ts`

**Interfaces:**
- Consumes: `AlertCompany` from `frontend/src/lib/api.ts` (Task 3), `TreeNodeData` from `tree.ts` (Task 6), `sectorColor` from `colors.ts` (Task 5)
- Produces: `buildImpactTree(articleTitle: string, companies: AlertCompany[]): TreeNodeData`, `buildSectorTree(articleTitle: string, companies: AlertCompany[]): TreeNodeData` — consumed by `VisualizeModal.tsx` (Task 12).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/visualize/transforms.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { buildImpactTree, buildSectorTree } from './transforms';
import type { AlertCompany } from '../../lib/api';

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because',
    basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN', in_my_holdings: false,
    ...overrides,
  };
}

describe('buildImpactTree', () => {
  it('splits companies into Bullish and Bearish branches', () => {
    const tree = buildImpactTree('Some event', [
      company({ company_id: 1, direction: 'bullish' }),
      company({ company_id: 2, direction: 'bearish' }),
    ]);
    expect(tree.label).toBe('Some event');
    expect(tree.children.map((b) => b.label)).toEqual(['Bullish', 'Bearish']);
    expect(tree.children[0].children).toHaveLength(1);
    expect(tree.children[1].children).toHaveLength(1);
  });

  it('omits a branch with zero companies rather than rendering it empty', () => {
    const tree = buildImpactTree('Some event', [company({ direction: 'bullish' })]);
    expect(tree.children.map((b) => b.label)).toEqual(['Bullish']);
  });

  it('excludes companies whose direction is neither bullish nor bearish', () => {
    const tree = buildImpactTree('Some event', [company({ direction: 'unknown' })]);
    expect(tree.children).toHaveLength(0);
  });
});

describe('buildSectorTree', () => {
  it('groups companies by sector, alphabetically', () => {
    const tree = buildSectorTree('Some event', [
      company({ company_id: 1, sector: 'Financials' }),
      company({ company_id: 2, sector: 'Energy' }),
      company({ company_id: 3, sector: 'Energy' }),
    ]);
    expect(tree.children.map((b) => b.label)).toEqual(['Energy', 'Financials']);
    expect(tree.children[0].children).toHaveLength(2);
  });

  it('groups companies with no sector under "Other"', () => {
    const tree = buildSectorTree('Some event', [company({ sector: undefined })]);
    expect(tree.children.map((b) => b.label)).toEqual(['Other']);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npx vitest run src/features/visualize/transforms.test.ts`
Expected: FAIL — `transforms.ts` does not exist

- [ ] **Step 3: Implement**

Create `frontend/src/features/visualize/transforms.ts`:

```ts
import type { AlertCompany } from '../../lib/api';
import type { TreeNodeData } from './tree';
import { sectorColor } from './colors';

const BULLISH_COLOR = '#34C759';
const BEARISH_COLOR = '#FF453A';

function leafNode(company: AlertCompany): TreeNodeData {
  return {
    id: `company-${company.company_id}`,
    label: company.name,
    kind: 'leaf',
    leaf: {
      companyId: company.company_id,
      ticker: company.ticker,
      name: company.name,
      direction: company.direction,
      rationale: company.rationale,
    },
    children: [],
  };
}

export function buildImpactTree(articleTitle: string, companies: AlertCompany[]): TreeNodeData {
  const bullish = companies.filter((c) => c.direction === 'bullish');
  const bearish = companies.filter((c) => c.direction === 'bearish');

  const branches: TreeNodeData[] = [];
  if (bullish.length > 0) {
    branches.push({ id: 'branch-bullish', label: 'Bullish', kind: 'branch', color: BULLISH_COLOR, children: bullish.map(leafNode) });
  }
  if (bearish.length > 0) {
    branches.push({ id: 'branch-bearish', label: 'Bearish', kind: 'branch', color: BEARISH_COLOR, children: bearish.map(leafNode) });
  }

  return { id: 'root', label: articleTitle, kind: 'root', children: branches };
}

export function buildSectorTree(articleTitle: string, companies: AlertCompany[]): TreeNodeData {
  const bySector = new Map<string, AlertCompany[]>();
  for (const company of companies) {
    const sector = company.sector && company.sector.trim().length > 0 ? company.sector : 'Other';
    const group = bySector.get(sector) ?? [];
    group.push(company);
    bySector.set(sector, group);
  }

  const branches: TreeNodeData[] = [...bySector.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([sector, group]) => ({
      id: `branch-${sector}`, label: sector, kind: 'branch', color: sectorColor(sector), children: group.map(leafNode),
    }));

  return { id: 'root', label: articleTitle, kind: 'root', children: branches };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/features/visualize/transforms.test.ts`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/visualize/transforms.ts frontend/src/features/visualize/transforms.test.ts
git commit -m "feat: add Impact Tree and Sector Tree data transforms"
```

---

### Task 9: Frontend — ResizeObserver test polyfill (needed by react-flow)

**Files:**
- Modify: `frontend/src/test/setup.ts`

**Interfaces:**
- Produces: a global `ResizeObserver` stub available in every test — consumed by any test that renders `<ReactFlow>` (Tasks 10-13).

- [ ] **Step 1: Add the polyfill**

`frontend/src/test/setup.ts` currently contains only:

```ts
import '@testing-library/jest-dom';
```

Replace its full contents with:

```ts
import '@testing-library/jest-dom';

// react-flow (used by the visualize feature) calls ResizeObserver, which
// jsdom does not implement.
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}
```

- [ ] **Step 2: Verify existing tests are unaffected**

Run (from `frontend/`): `npm test`
Expected: `84 passed` (unchanged — this only adds a global that was previously undefined)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/test/setup.ts
git commit -m "test: polyfill ResizeObserver for react-flow in jsdom"
```

---

### Task 10: Frontend — `TreeCanvas` react-flow wrapper

**Files:**
- Create: `frontend/src/features/visualize/TreeCanvas.tsx`
- Test: `frontend/src/features/visualize/TreeCanvas.test.tsx`

**Interfaces:**
- Consumes: react-flow's `Node`/`Edge` types, `TreeLeafMeta` from `tree.ts` (Task 6)
- Produces: `<TreeCanvas nodes={Node[]} edges={Edge[]} onLeafClick={(companyId: number) => void} />` — consumed by `TreeView.tsx` (Task 11).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/visualize/TreeCanvas.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import TreeCanvas from './TreeCanvas';
import type { Node, Edge } from 'reactflow';

const nodes: Node[] = [
  { id: 'root', type: 'root', position: { x: 0, y: 0 }, data: { label: 'Event' } },
  {
    id: 'leaf1', type: 'leaf', position: { x: 0, y: 150 },
    data: { label: 'Alpha Co', leaf: { companyId: 7, ticker: 'AAA', name: 'Alpha Co', direction: 'bullish', rationale: 'r' } },
  },
];
const edges: Edge[] = [{ id: 'root->leaf1', source: 'root', target: 'leaf1' }];

describe('TreeCanvas', () => {
  it('renders every node label', () => {
    render(<TreeCanvas nodes={nodes} edges={edges} onLeafClick={() => {}} />);
    expect(screen.getByText('Event')).toBeInTheDocument();
    expect(screen.getByText('Alpha Co')).toBeInTheDocument();
  });

  it('calls onLeafClick with the company id when a leaf node is clicked', async () => {
    const onLeafClick = vi.fn();
    render(<TreeCanvas nodes={nodes} edges={edges} onLeafClick={onLeafClick} />);
    await userEvent.click(screen.getByText('Alpha Co'));
    expect(onLeafClick).toHaveBeenCalledWith(7);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npx vitest run src/features/visualize/TreeCanvas.test.tsx`
Expected: FAIL — `TreeCanvas.tsx` does not exist

- [ ] **Step 3: Implement**

Create `frontend/src/features/visualize/TreeCanvas.tsx`:

```tsx
import { useMemo } from 'react';
import ReactFlow, { Background, Controls, Handle, Position, type Node, type NodeProps, type Edge } from 'reactflow';
import 'reactflow/dist/style.css';
import type { TreeLeafMeta } from './tree';

interface TreeNodeRenderData {
  label: string;
  color?: string;
  leaf?: TreeLeafMeta;
}

function RootNode({ data }: NodeProps<TreeNodeRenderData>) {
  return (
    <div className="max-w-[260px] rounded-lg border border-hairline bg-surface px-4 py-3 font-display text-sm font-bold text-ink shadow-sm">
      <Handle type="source" position={Position.Bottom} className="opacity-0" />
      {data.label}
    </div>
  );
}

function BranchNode({ data }: NodeProps<TreeNodeRenderData>) {
  const color = data.color ?? '#262626';
  return (
    <div
      className="rounded-lg border px-3 py-2 text-xs font-bold uppercase tracking-widest text-ink"
      style={{ borderColor: color, backgroundColor: `${color}22` }}
    >
      <Handle type="target" position={Position.Top} className="opacity-0" />
      <Handle type="source" position={Position.Bottom} className="opacity-0" />
      {data.label}
    </div>
  );
}

function LeafNode({ data, selected }: NodeProps<TreeNodeRenderData>) {
  const bullish = data.leaf?.direction === 'bullish';
  return (
    <div
      className={`flex min-w-[160px] items-center gap-1.5 rounded-lg border bg-surface p-2.5 text-sm text-ink motion-safe:transition-colors ${
        selected ? 'border-ink' : 'border-hairline'
      }`}
    >
      <Handle type="target" position={Position.Top} className="opacity-0" />
      <span aria-hidden="true" className={bullish ? 'text-bullish' : 'text-bearish'}>
        {bullish ? '▲' : '▼'}
      </span>
      <span className="truncate">{data.label}</span>
    </div>
  );
}

const nodeTypes = { root: RootNode, branch: BranchNode, leaf: LeafNode };

export default function TreeCanvas({
  nodes,
  edges,
  onLeafClick,
}: {
  nodes: Node[];
  edges: Edge[];
  onLeafClick: (companyId: number) => void;
}) {
  const flowNodes = useMemo(
    () => nodes.map((n) => (n.type === 'leaf' ? { ...n, className: 'cursor-pointer' } : n)),
    [nodes],
  );

  function handleNodeClick(_event: unknown, node: Node) {
    const leaf = (node.data as TreeNodeRenderData).leaf;
    if (leaf) onLeafClick(leaf.companyId);
  }

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={flowNodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={handleNodeClick}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#262626" gap={24} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/features/visualize/TreeCanvas.test.tsx`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/visualize/TreeCanvas.tsx frontend/src/features/visualize/TreeCanvas.test.tsx
git commit -m "feat: add react-flow TreeCanvas with root/branch/leaf node styles"
```

---

### Task 11: Frontend — `TreeView` (transform + layout + canvas + reasoning panel)

**Files:**
- Create: `frontend/src/features/visualize/TreeView.tsx`
- Test: `frontend/src/features/visualize/TreeView.test.tsx`

**Interfaces:**
- Consumes: `AlertCompany` (Task 3), `TreeNodeData` (Task 6), `layoutTree` (Task 7), `TreeCanvas` (Task 10), existing `frontend/src/components/ReasoningPanel.tsx` (unmodified)
- Produces: `<TreeView articleTitle={string} companies={AlertCompany[]} build={(title, companies) => TreeNodeData} />` — consumed by `VisualizeModal.tsx` (Task 12).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/visualize/TreeView.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import TreeView from './TreeView';
import { buildImpactTree } from './transforms';
import type { AlertCompany } from '../../lib/api';

const companies: AlertCompany[] = [
  {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50', direction: 'bullish',
    magnitude_low: 1, magnitude_high: 2, rationale: 'Refiner up.', basis: 'direct_mention',
    confidence: 'llm_estimate', market: 'IN', in_my_holdings: false, sector: 'Energy',
  },
];

describe('TreeView', () => {
  it('renders the tree built by the given build function', () => {
    render(<TreeView articleTitle="Some event" companies={companies} build={buildImpactTree} />);
    expect(screen.getByText('Some event')).toBeInTheDocument();
    expect(screen.getByText('Alpha Co')).toBeInTheDocument();
  });

  it('shows the reasoning panel for a company after clicking its leaf', async () => {
    render(<TreeView articleTitle="Some event" companies={companies} build={buildImpactTree} />);
    await userEvent.click(screen.getByText('Alpha Co'));
    expect(screen.getByText('Refiner up.')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npx vitest run src/features/visualize/TreeView.test.tsx`
Expected: FAIL — `TreeView.tsx` does not exist

- [ ] **Step 3: Implement**

Create `frontend/src/features/visualize/TreeView.tsx`:

```tsx
import { useMemo, useState } from 'react';
import type { AlertCompany } from '../../lib/api';
import type { TreeNodeData } from './tree';
import { layoutTree } from './treeLayout';
import TreeCanvas from './TreeCanvas';
import ReasoningPanel from '../../components/ReasoningPanel';

export default function TreeView({
  articleTitle,
  companies,
  build,
}: {
  articleTitle: string;
  companies: AlertCompany[];
  build: (articleTitle: string, companies: AlertCompany[]) => TreeNodeData;
}) {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const { nodes, edges } = useMemo(() => layoutTree(build(articleTitle, companies)), [articleTitle, companies, build]);
  const selected = companies.find((c) => c.company_id === selectedId) ?? null;

  return (
    <div className="flex h-full">
      <div className="min-w-0 flex-1">
        <TreeCanvas nodes={nodes} edges={edges} onLeafClick={setSelectedId} />
      </div>
      {selected && (
        <div className="w-72 shrink-0 overflow-y-auto border-l border-hairline p-4">
          <ReasoningPanel company={selected} />
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/features/visualize/TreeView.test.tsx`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/visualize/TreeView.tsx frontend/src/features/visualize/TreeView.test.tsx
git commit -m "feat: add TreeView composing layout, canvas and reasoning panel"
```

---

### Task 12: Frontend — `ViewPicker` segmented control

**Files:**
- Create: `frontend/src/features/visualize/ViewPicker.tsx`
- Test: `frontend/src/features/visualize/ViewPicker.test.tsx`

**Interfaces:**
- Produces: `export type ViewType = 'impact' | 'sector'`, `<ViewPicker value={ViewType} onChange={(v: ViewType) => void} />` — consumed by `VisualizeModal.tsx` (Task 13).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/visualize/ViewPicker.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import ViewPicker from './ViewPicker';

describe('ViewPicker', () => {
  it('renders both view options', () => {
    render(<ViewPicker value="impact" onChange={() => {}} />);
    expect(screen.getByText('Impact Tree')).toBeInTheDocument();
    expect(screen.getByText('Sector Tree')).toBeInTheDocument();
  });

  it('calls onChange with the clicked view id', async () => {
    const onChange = vi.fn();
    render(<ViewPicker value="impact" onChange={onChange} />);
    await userEvent.click(screen.getByText('Sector Tree'));
    expect(onChange).toHaveBeenCalledWith('sector');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npx vitest run src/features/visualize/ViewPicker.test.tsx`
Expected: FAIL — `ViewPicker.tsx` does not exist

- [ ] **Step 3: Implement**

Create `frontend/src/features/visualize/ViewPicker.tsx`:

```tsx
export type ViewType = 'impact' | 'sector';

const VIEWS: { id: ViewType; label: string }[] = [
  { id: 'impact', label: 'Impact Tree' },
  { id: 'sector', label: 'Sector Tree' },
];

export default function ViewPicker({ value, onChange }: { value: ViewType; onChange: (v: ViewType) => void }) {
  return (
    <div className="flex gap-1 rounded-lg border border-hairline bg-surface p-1">
      {VIEWS.map((v) => (
        <button
          key={v.id}
          type="button"
          onClick={() => onChange(v.id)}
          className={`rounded-md px-3 py-1.5 text-xs uppercase tracking-widest motion-safe:transition-colors ${
            value === v.id ? 'bg-page text-ink' : 'text-muted hover:text-ink'
          }`}
        >
          {v.label}
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/features/visualize/ViewPicker.test.tsx`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/visualize/ViewPicker.tsx frontend/src/features/visualize/ViewPicker.test.tsx
git commit -m "feat: add ViewPicker segmented control for the visualize feature"
```

---

### Task 13: Frontend — `VisualizeModal`

**Files:**
- Create: `frontend/src/features/visualize/VisualizeModal.tsx`
- Test: `frontend/src/features/visualize/VisualizeModal.test.tsx`

**Interfaces:**
- Consumes: `Alert` from `frontend/src/lib/api.ts`, `ViewPicker`/`ViewType` (Task 12), `TreeView` (Task 11), `buildImpactTree`/`buildSectorTree` (Task 8)
- Produces: `<VisualizeModal alert={Alert} onClose={() => void} />` — consumed by `AlertCard.tsx` (Task 14).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/visualize/VisualizeModal.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import VisualizeModal from './VisualizeModal';
import type { Alert } from '../../lib/api';

const alert: Alert = {
  id: 1, category: 'oil_energy', created_at: '2026-07-09T10:00:00+00:00',
  article: { id: 1, title: 'US strikes Iran oil export sites', url: 'https://example.com/a' },
  companies: [
    {
      company_id: 1, ticker: 'RELIANCE.NS', name: 'Reliance Industries', index_tier: 'NIFTY50',
      direction: 'bullish', magnitude_low: 2, magnitude_high: 4, rationale: 'Refiner up.',
      basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN', in_my_holdings: true, sector: 'Energy',
    },
  ],
};

describe('VisualizeModal', () => {
  it('renders the article title and the impact tree by default', () => {
    render(<VisualizeModal alert={alert} onClose={() => {}} />);
    expect(screen.getAllByText('US strikes Iran oil export sites').length).toBeGreaterThan(0);
    expect(screen.getByText('Bullish')).toBeInTheDocument();
  });

  it('switches to the sector tree when picked', async () => {
    render(<VisualizeModal alert={alert} onClose={() => {}} />);
    await userEvent.click(screen.getByText('Sector Tree'));
    expect(screen.getByText('Energy')).toBeInTheDocument();
  });

  it('calls onClose when the close button is clicked', async () => {
    const onClose = vi.fn();
    render(<VisualizeModal alert={alert} onClose={onClose} />);
    await userEvent.click(screen.getByLabelText('Close'));
    expect(onClose).toHaveBeenCalled();
  });

  it('shows an empty-state message when the alert has no companies', () => {
    render(<VisualizeModal alert={{ ...alert, companies: [] }} onClose={() => {}} />);
    expect(screen.getByText('No affected companies for this story.')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npx vitest run src/features/visualize/VisualizeModal.test.tsx`
Expected: FAIL — `VisualizeModal.tsx` does not exist

- [ ] **Step 3: Implement**

Create `frontend/src/features/visualize/VisualizeModal.tsx`:

```tsx
import { useState } from 'react';
import type { Alert } from '../../lib/api';
import ViewPicker, { type ViewType } from './ViewPicker';
import TreeView from './TreeView';
import { buildImpactTree, buildSectorTree } from './transforms';

export default function VisualizeModal({ alert, onClose }: { alert: Alert; onClose: () => void }) {
  const [view, setView] = useState<ViewType>('impact');
  const build = view === 'impact' ? buildImpactTree : buildSectorTree;

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-page/95 backdrop-blur-sm" role="dialog" aria-modal="true">
      <div className="flex items-center justify-between border-b border-hairline px-6 py-4">
        <h2 className="truncate font-display text-lg font-bold text-ink">{alert.article.title}</h2>
        <div className="flex items-center gap-4">
          <ViewPicker value={view} onChange={setView} />
          <button type="button" onClick={onClose} aria-label="Close" className="text-muted hover:text-ink">
            ✕
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-hidden">
        {alert.companies.length === 0 ? (
          <p className="p-6 text-sm text-muted">No affected companies for this story.</p>
        ) : (
          <TreeView articleTitle={alert.article.title} companies={alert.companies} build={build} />
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/features/visualize/VisualizeModal.test.tsx`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/visualize/VisualizeModal.tsx frontend/src/features/visualize/VisualizeModal.test.tsx
git commit -m "feat: add VisualizeModal with view picker and empty state"
```

---

### Task 14: Frontend — wire the "Visualize" button into `AlertCard`

**Files:**
- Modify: `frontend/src/components/AlertCard.tsx`
- Test: `frontend/src/components/AlertCard.test.tsx` (append new tests)

**Interfaces:**
- Consumes: `VisualizeModal` (Task 13)

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/components/AlertCard.test.tsx`, inside the existing `describe('AlertCard', ...)` block (after the last `it`, before the closing `});`):

```tsx
  it('opens the visualize modal from the expanded card', async () => {
    render(<AlertCard alert={alert} isAuthenticated />);
    await userEvent.click(screen.getByText('US strikes Iran oil export sites'));
    await userEvent.click(screen.getByRole('button', { name: /visualize/i }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('closes the visualize modal without collapsing the card', async () => {
    render(<AlertCard alert={alert} isAuthenticated />);
    await userEvent.click(screen.getByText('US strikes Iran oil export sites'));
    await userEvent.click(screen.getByRole('button', { name: /visualize/i }));
    await userEvent.click(screen.getByLabelText('Close'));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByText('Reliance Industries')).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npx vitest run src/components/AlertCard.test.tsx`
Expected: FAIL — no button named "visualize" exists yet

- [ ] **Step 3: Implement**

In `frontend/src/components/AlertCard.tsx`:

Add the import, alongside the existing component imports:

```tsx
import VisualizeModal from '../features/visualize/VisualizeModal';
```

Add state, alongside the existing `useState` calls in the component body:

```tsx
  const [visualizeOpen, setVisualizeOpen] = useState(false);

  function openVisualize(e: MouseEvent) {
    e.stopPropagation(); // must not toggle the card, same reasoning as selectTab
    setVisualizeOpen(true);
  }
```

Change the expanded block to add a "Visualize" trigger row, and render the modal at the end of the returned `<article>`:

```tsx
      {expanded && (
        <div className="mt-4 flex flex-col gap-4 motion-safe:transition-all">
          <div className="flex justify-end">
            <button
              type="button"
              onClick={openVisualize}
              className="text-xs uppercase tracking-widest text-muted hover:text-ink"
            >
              Visualize →
            </button>
          </div>
          {visible.length === 0 ? (
            <p className="text-xs text-muted">{emptyCopy}</p>
          ) : (
            grouped.map((group) => (
              <div key={group.tier} className="flex flex-col gap-2">
                <p className="text-xs uppercase tracking-widest text-muted">{group.label}</p>
                <div className="grid grid-cols-1 items-start gap-2 sm:grid-cols-2">
                  {group.companies.map((company) => (
                    <CompanyChip key={company.company_id} company={company} />
                  ))}
                </div>
              </div>
            ))
          )}
        </div>
      )}
      {visualizeOpen && <VisualizeModal alert={alert} onClose={() => setVisualizeOpen(false)} />}
    </article>
```

(This replaces the previous closing `</article>` at the end of the returned JSX — the modal render sits just before it, inside the same top-level fragment returned by the component.)

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/components/AlertCard.test.tsx`
Expected: `12 passed` (10 existing + 2 new)

- [ ] **Step 5: Run the full frontend suite and typecheck**

Run (from `frontend/`): `npx tsc --noEmit && npm test`
Expected: no type errors; all test files pass (27 files, 108 tests: 84 baseline + 24 added across Tasks 5/7/8/10/11/12/13 + 2 new in this task)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/AlertCard.tsx frontend/src/components/AlertCard.test.tsx
git commit -m "feat: add Visualize button to AlertCard opening the impact/sector tree modal"
```

---

## Final verification (after all tasks)

- [ ] Run the full backend suite: `"C:\Users\ST269\Desktop\newsflo\backend\.venv\Scripts\python.exe" -m pytest -q` from `backend/` — expect all passing, 0 failures.
- [ ] Run the full frontend suite: `npx tsc --noEmit && npm test` from `frontend/` — expect all passing, 0 failures.
- [ ] Manually smoke-test: `npm run dev` (frontend) against a running backend, open a feed alert, click "Visualize →", confirm the Impact Tree renders with pan/zoom, switch to Sector Tree, click a leaf to see its `ReasoningPanel`, close the modal.
