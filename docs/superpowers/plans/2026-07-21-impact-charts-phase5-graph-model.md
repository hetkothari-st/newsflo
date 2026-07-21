# Impact Charts — Phase 5 (Frontend Graph Model + `buildGraph`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the frontend a single, typed entry point (`buildGraph(alert)`) for the graph payload Phase 4's API exposes, with a legacy-alert fallback (synthesizes a minimal graph from `alert.companies` when `alert.graph` is absent) so every graph chart (Phases 6-7) can consume one consistent shape regardless of whether the alert predates Phase 3/4.

**Architecture:** New TS types in `frontend/src/lib/api.ts` mirroring Phase 4's JSON response exactly. New `frontend/src/features/visualize/graph/model.ts`: `buildGraph` plus three pure selectors (`longestChainPath`, `mechanismBackbone`, `ringsByImpactLevel`), each consumed by one specific Phase 7 chart. Pure TypeScript, no new dependency, no chart mounted yet.

**Tech Stack:** TypeScript, Vitest.

## Global Constraints

- `Alert.companies`'s existing shape is untouched — this plan only ADDS a `graph?: ImpactGraph` field to the `Alert` interface.
- Verified current code this plan is grounded against (read directly): `frontend/src/lib/api.ts`'s `AlertCompany`/`Alert` interfaces (confirmed `event_type?: string | null` already exists on `Alert` — Phase 4's backend serializer already sends it, nothing to add there; only `graph` is new). Phase 4's actual `_build_graph` output shape (`backend/app/routers/alerts.py`): `nodes: [{id, kind, label, direction?, company_id?, ticker?, name?, confidence_score?, impact_level?, in_my_holdings?}]`, `edges: [{from, to, relation, direction, note, source}]`, `gaps: [{sector, impact_level, reason}]`.
- Node `kind` values: `"news" | "mechanism" | "sector" | "company"`. Edge `source` values: `"rulebook_verified" | "rulebook_pruned" | "llm_only"`.
- `buildGraph` never mutates its input `alert` and never throws — an alert with no `companies` and no `graph` returns a graph with just the `news` node, empty `edges`/`gaps`, not a crash.
- Test file convention in this codebase (confirmed via `frontend/src/features/visualize/transforms.test.ts`): Vitest `describe`/`it`, a local `company(overrides: Partial<AlertCompany>)` factory function providing sane defaults so each test only specifies what it cares about. This plan's tests follow the same convention with an equivalent `alertCompany`/`alert` factory pair.

---

### Task 1: Types + `buildGraph` + selectors

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/features/visualize/graph/model.ts`
- Test: `frontend/src/features/visualize/graph/model.test.ts`

**Interfaces:**
- Produces: `GraphNode`, `GraphEdge`, `GraphGap`, `ImpactGraph` types and `Alert.graph?: ImpactGraph` (`app/lib/api.ts`). `buildGraph(alert: Alert): ImpactGraph`, `longestChainPath(graph: ImpactGraph): GraphNode[]`, `mechanismBackbone(graph: ImpactGraph): GraphNode[]`, `ringsByImpactLevel(graph: ImpactGraph): { level: string; nodes: GraphNode[] }[]` (`frontend/src/features/visualize/graph/model.ts`), for Phase 7's four graph charts to consume (`longestChainPath` → Supply Chain #3, `mechanismBackbone` → Economic Chain #9, `ringsByImpactLevel` → Ripple Effect #2; `buildGraph` itself feeds Knowledge Graph #10 directly).

- [ ] **Step 1: Add graph types to `api.ts`**

In `frontend/src/lib/api.ts`, add after the `AlertCompany` interface (right before `export interface Alert {`):

```typescript
export interface GraphNode {
  id: string;
  kind: 'news' | 'mechanism' | 'sector' | 'company';
  label: string;
  // Root/news nodes have no direction of their own -- null/absent there.
  direction?: string | null; // bullish | bearish | null
  // Company-kind nodes only:
  company_id?: number;
  ticker?: string;
  name?: string;
  confidence_score?: number;
  impact_level?: string;
  in_my_holdings?: boolean;
}

export interface GraphEdge {
  from: string;
  to: string;
  relation: string;
  direction: string; // bullish | bearish
  note: string;
  source: string; // rulebook_verified | rulebook_pruned | llm_only
}

export interface GraphGap {
  sector: string;
  impact_level: string;
  reason: string;
}

export interface ImpactGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  gaps: GraphGap[];
}
```

Then change the `Alert` interface's existing `event_type` field (currently the last field, ending the interface):

```typescript
  // Optional: legacy alerts (persisted before this feature shipped) have
  // no event_type.
  event_type?: string | null;
}
```

to:

```typescript
  // Optional: legacy alerts (persisted before this feature shipped) have
  // no event_type.
  event_type?: string | null;
  // Optional: only present on GET /api/alerts/{id} (never on the list
  // endpoint, and absent on any alert predating Phase 3/4's rollout). Use
  // buildGraph(alert) (see features/visualize/graph/model.ts) rather than
  // reading this field directly -- it synthesizes a fallback for the
  // absent case so every graph chart has one consistent shape to consume.
  graph?: ImpactGraph;
}
```

- [ ] **Step 2: Write the failing tests**

Create `frontend/src/features/visualize/graph/model.test.ts`:

```typescript
import { describe, expect, it } from 'vitest';
import { buildGraph, longestChainPath, mechanismBackbone, ringsByImpactLevel } from './model';
import type { Alert, AlertCompany, ImpactGraph } from '../../../lib/api';

function alertCompany(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because',
    key_points: [], confidence_score: 50, time_horizon: 'Short-Term', basis: 'direct_mention',
    confidence: 'llm_estimate', market: 'IN', in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

function alert(overrides: Partial<Alert>): Alert {
  return {
    id: 1, category: 'oil_gas', category_label: 'Oil & Gas', created_at: '2026-07-21T00:00:00Z',
    article: { id: 1, title: 'Test article', url: 'https://example.com', image_url: null },
    companies: [],
    ...overrides,
  };
}

describe('buildGraph', () => {
  it('returns alert.graph verbatim when present, including a pruned edge unchanged', () => {
    const realGraph: ImpactGraph = {
      nodes: [{ id: 'news', kind: 'news', label: 'x' }],
      edges: [{
        from: 'mech:a', to: 'mech:b', relation: 'credit_cost', direction: 'bullish',
        note: 'n [PRUNED: no lending angle]', source: 'rulebook_pruned',
      }],
      gaps: [{ sector: 'banking', impact_level: 'indirect_l1', reason: 'r' }],
    };

    const graph = buildGraph(alert({ graph: realGraph }));

    expect(graph).toBe(realGraph);
    expect(graph.edges[0].source).toBe('rulebook_pruned');
    expect(graph.edges[0].note).toContain('[PRUNED');
  });

  it('synthesizes a minimal graph from companies when alert.graph is absent', () => {
    const a = alert({
      companies: [alertCompany({ company_id: 1, ticker: 'RELIANCE.NS', name: 'Reliance', sector: 'oil_gas', direction: 'bullish' })],
    });

    const graph = buildGraph(a);

    const nodeIds = graph.nodes.map((n) => n.id);
    expect(nodeIds).toContain('news');
    expect(nodeIds).toContain('sector:oil_gas');
    expect(nodeIds).toContain('company:1');
    expect(graph.edges.some((e) => e.from === 'sector:oil_gas' && e.to === 'company:1')).toBe(true);
    expect(graph.gaps).toEqual([]);
  });

  it('synthesized graph has no duplicate node ids when two companies share a sector', () => {
    const a = alert({
      companies: [
        alertCompany({ company_id: 1, ticker: 'HDFCBANK.NS', sector: 'banking' }),
        alertCompany({ company_id: 2, ticker: 'ICICIBANK.NS', sector: 'banking' }),
      ],
    });

    const graph = buildGraph(a);

    const ids = graph.nodes.map((n) => n.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids.filter((id) => id === 'sector:banking')).toHaveLength(1);
  });

  it('a company with no sector connects straight to news, no sector node', () => {
    const a = alert({ companies: [alertCompany({ company_id: 1, ticker: 'AAA', sector: undefined })] });

    const graph = buildGraph(a);

    expect(graph.edges.some((e) => e.from === 'news' && e.to === 'company:1')).toBe(true);
    expect(graph.nodes.some((n) => n.kind === 'sector')).toBe(false);
  });

  it('an alert with zero companies and no graph still returns just the news node', () => {
    const graph = buildGraph(alert({ companies: [] }));

    expect(graph.nodes).toEqual([{ id: 'news', kind: 'news', label: 'Test article' }]);
    expect(graph.edges).toEqual([]);
    expect(graph.gaps).toEqual([]);
  });
});

describe('longestChainPath', () => {
  it('walks the longest from-news path through the graph', () => {
    const graph: ImpactGraph = {
      nodes: [
        { id: 'news', kind: 'news', label: 'x' },
        { id: 'mech:a', kind: 'mechanism', label: 'A' },
        { id: 'sector:banking', kind: 'sector', label: 'banking' },
        { id: 'company:1', kind: 'company', label: 'C1' },
      ],
      edges: [
        { from: 'news', to: 'mech:a', relation: 'correlation', direction: 'bullish', note: 'n', source: 'llm_only' },
        { from: 'mech:a', to: 'sector:banking', relation: 'credit_cost', direction: 'bullish', note: 'n', source: 'rulebook_verified' },
        { from: 'sector:banking', to: 'company:1', relation: 'demand', direction: 'bullish', note: 'n', source: 'llm_only' },
      ],
      gaps: [],
    };

    const path = longestChainPath(graph);

    expect(path.map((n) => n.id)).toEqual(['news', 'mech:a', 'sector:banking', 'company:1']);
  });

  it('returns just the news node when there are no edges', () => {
    const graph: ImpactGraph = { nodes: [{ id: 'news', kind: 'news', label: 'x' }], edges: [], gaps: [] };

    expect(longestChainPath(graph).map((n) => n.id)).toEqual(['news']);
  });

  it('returns an empty array when there is no news node at all', () => {
    const graph: ImpactGraph = { nodes: [], edges: [], gaps: [] };

    expect(longestChainPath(graph)).toEqual([]);
  });
});

describe('mechanismBackbone', () => {
  it('returns only mechanism-kind nodes, in their original order', () => {
    const graph: ImpactGraph = {
      nodes: [
        { id: 'news', kind: 'news', label: 'x' },
        { id: 'mech:a', kind: 'mechanism', label: 'A' },
        { id: 'sector:banking', kind: 'sector', label: 'banking' },
        { id: 'mech:b', kind: 'mechanism', label: 'B' },
      ],
      edges: [], gaps: [],
    };

    expect(mechanismBackbone(graph).map((n) => n.id)).toEqual(['mech:a', 'mech:b']);
  });
});

describe('ringsByImpactLevel', () => {
  it('groups company nodes into direct/indirect_l1/indirect_l2 rings, inner-first', () => {
    const graph: ImpactGraph = {
      nodes: [
        { id: 'news', kind: 'news', label: 'x' },
        { id: 'company:1', kind: 'company', label: 'C1', impact_level: 'indirect_l1' },
        { id: 'company:2', kind: 'company', label: 'C2', impact_level: 'direct' },
        { id: 'company:3', kind: 'company', label: 'C3', impact_level: 'indirect_l2' },
      ],
      edges: [], gaps: [],
    };

    const rings = ringsByImpactLevel(graph);

    expect(rings.map((r) => r.level)).toEqual(['direct', 'indirect_l1', 'indirect_l2']);
    expect(rings[0].nodes.map((n) => n.id)).toEqual(['company:2']);
    expect(rings[1].nodes.map((n) => n.id)).toEqual(['company:1']);
    expect(rings[2].nodes.map((n) => n.id)).toEqual(['company:3']);
  });

  it('omits a ring with zero companies rather than rendering it empty', () => {
    const graph: ImpactGraph = {
      nodes: [{ id: 'company:1', kind: 'company', label: 'C1', impact_level: 'direct' }],
      edges: [], gaps: [],
    };

    expect(ringsByImpactLevel(graph).map((r) => r.level)).toEqual(['direct']);
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run (from `frontend/`): `npx vitest run src/features/visualize/graph/model.test.ts`
Expected: FAIL (`Cannot find module './model'` or similar — the file doesn't exist yet).

- [ ] **Step 4: Implement `graph/model.ts`**

Create `frontend/src/features/visualize/graph/model.ts`:

```typescript
import type { Alert, AlertCompany, GraphEdge, GraphNode, ImpactGraph } from '../../../lib/api';

function synthesizeLegacyGraph(alert: Alert): ImpactGraph {
  const nodes: GraphNode[] = [{ id: 'news', kind: 'news', label: alert.article.title }];
  const edges: GraphEdge[] = [];
  const seenNodeIds = new Set(['news']);

  for (const company of alert.companies) {
    const companyId = `company:${company.company_id}`;
    if (seenNodeIds.has(companyId)) continue; // defensive: never emit a duplicate node id
    seenNodeIds.add(companyId);
    nodes.push({
      id: companyId, kind: 'company', label: company.name,
      company_id: company.company_id, ticker: company.ticker, name: company.name,
      direction: company.direction, confidence_score: company.confidence_score,
      impact_level: company.impact_level, in_my_holdings: company.in_my_holdings,
    });

    const sector = company.sector && company.sector.trim().length > 0 ? company.sector : null;
    if (sector) {
      const sectorId = `sector:${sector}`;
      if (!seenNodeIds.has(sectorId)) {
        seenNodeIds.add(sectorId);
        nodes.push({ id: sectorId, kind: 'sector', label: sector });
        edges.push({
          from: 'news', to: sectorId, relation: 'correlation', direction: company.direction,
          note: 'This news directly names companies in this sector.', source: 'llm_only',
        });
      }
      edges.push({
        from: sectorId, to: companyId, relation: 'demand', direction: company.direction,
        note: `${company.name} is affected by this news.`, source: 'llm_only',
      });
    } else {
      edges.push({
        from: 'news', to: companyId, relation: 'correlation', direction: company.direction,
        note: 'This news directly names this company.', source: 'llm_only',
      });
    }
  }

  return { nodes, edges, gaps: [] };
}

// Returns alert.graph verbatim when the backend already computed one
// (Phase 4's GET /api/alerts/{id}) -- pruned edges, gaps, and every other
// field pass through unchanged, no re-filtering. Falls back to a minimal
// synthesized graph (news -> sector -> company, no mechanism layer) for a
// legacy alert (predates Phase 3/4) so every graph chart still has a
// consistent ImpactGraph to render, never undefined/a crash.
export function buildGraph(alert: Alert): ImpactGraph {
  if (alert.graph) return alert.graph;
  return synthesizeLegacyGraph(alert);
}

// Supply Chain Graph (#3): the single longest from-"news" path through the
// graph, by edge count. Small graphs, no cycles expected in practice (the
// backend's edge generation is a DAG by construction) -- the `visited`
// guard below is defense-in-depth, not a case this data is expected to hit.
export function longestChainPath(graph: ImpactGraph): GraphNode[] {
  const nodesById = new Map(graph.nodes.map((n) => [n.id, n]));
  const outgoing = new Map<string, GraphEdge[]>();
  for (const edge of graph.edges) {
    const list = outgoing.get(edge.from) ?? [];
    list.push(edge);
    outgoing.set(edge.from, list);
  }

  function longestFrom(nodeId: string, visited: Set<string>): string[] {
    let best: string[] = [nodeId];
    for (const edge of outgoing.get(nodeId) ?? []) {
      if (visited.has(edge.to)) continue;
      const candidate = [nodeId, ...longestFrom(edge.to, new Set(visited).add(edge.to))];
      if (candidate.length > best.length) best = candidate;
    }
    return best;
  }

  if (!nodesById.has('news')) return [];
  return longestFrom('news', new Set(['news']))
    .map((id) => nodesById.get(id))
    .filter((n): n is GraphNode => n !== undefined);
}

// Economic Chain (#9): mechanism-kind nodes only, in their existing order
// (the order _build_graph/synthesizeLegacyGraph already inserted them in --
// insertion order for a dict-backed structure is stable, matching the
// chain's own natural sequence). The chart itself (Phase 7) is responsible
// for labeling each with the time_horizon bucket of the companies it
// reaches -- this selector only narrows down to the relevant nodes.
export function mechanismBackbone(graph: ImpactGraph): GraphNode[] {
  return graph.nodes.filter((n) => n.kind === 'mechanism');
}

export interface ImpactRing {
  level: string; // direct | indirect_l1 | indirect_l2
  nodes: GraphNode[];
}

const RING_ORDER = ['direct', 'indirect_l1', 'indirect_l2'];

// Ripple Effect Graph (#2): company nodes grouped into concentric rings by
// impact_level, direct = innermost. Only company-kind nodes carry
// impact_level, so mechanism/sector/news nodes are never in any ring.
export function ringsByImpactLevel(graph: ImpactGraph): ImpactRing[] {
  return RING_ORDER.map((level) => ({
    level,
    nodes: graph.nodes.filter((n) => n.kind === 'company' && n.impact_level === level),
  })).filter((ring) => ring.nodes.length > 0);
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run (from `frontend/`): `npx vitest run src/features/visualize/graph/model.test.ts`
Expected: PASS, all tests.

- [ ] **Step 6: Run the full frontend suite + typecheck**

Run (from `frontend/`): `npx vitest run` and `npx tsc --noEmit`
Expected: both PASS, no regressions, no type errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/features/visualize/graph/model.ts frontend/src/features/visualize/graph/model.test.ts
git commit -m "feat: add ImpactGraph types + buildGraph/selectors (frontend graph model)"
```

---

## Explicitly out of scope (this plan)

Mounting any chart that consumes `buildGraph`/the selectors (Phases 6-7). Adding `@xyflow/react` or any new rendering dependency (Phase 7's concern, only for charts #2/#10). Any UI/visual work at all — this plan is pure data-shape/logic, no `.tsx` file touched.

## Definition of done (this plan only)

1. `buildGraph` returns `alert.graph` unchanged when present (pruned edges/gaps intact, no re-filtering).
2. `buildGraph` synthesizes a valid, duplicate-free graph from `alert.companies` when `alert.graph` is absent, for both sectored and unsectored companies, and for zero companies.
3. `longestChainPath`, `mechanismBackbone`, `ringsByImpactLevel` each return the documented, tested subset of a graph.
4. Full frontend test suite green, `tsc --noEmit` clean.
