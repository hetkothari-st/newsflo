# Impact Charts — Phase 7 (Charts 2, 3, 9, 10 — the Graph Charts) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the 4 remaining charts — all are views of the one `ImpactGraph` payload from `buildGraph(alert)` (Phase 5). Supply Chain Graph (#3) and Economic Chain (#9) are linear, hand-rolled, no new dependency. Ripple Effect Graph (#2) and Knowledge Graph (#10) are genuine node-link diagrams, built with `@xyflow/react` (React Flow); Knowledge Graph additionally uses `d3-force` for real force-directed layout (per explicit user decision this session — `@xyflow/react` alone has no physics simulation, and "force-directed" is a literal requirement of this specific chart, not a suggestion).

**Architecture:** A new shared `GraphNodeChip` component (mirrors `CompanyCard`'s visual language for a `GraphNode` instead of an `AlertCompany`, covering all 4 node kinds: news/mechanism/sector/company) is reused by all 4 charts. Each chart takes `{ graph: ImpactGraph, companies: AlertCompany[], eventType?: string | null }` — `graph` is computed ONCE at the page level via `buildGraph(alert)` and passed down, not recomputed per chart. Company-kind node clicks reuse the existing `useCompanySelection`/`ReasoningPanel` drawer pattern (looked up by `company_id`, the one field every company-kind `GraphNode` carries that both this graph payload and `AlertCompany[]` share).

**Tech Stack:** React, TypeScript, Vitest, Testing Library, `@xyflow/react` (new), `d3-force` (new).

## Global Constraints

- **Task ordering is NOT fully parallelizable in this phase** (unlike prior phases): Task 3 adds `@xyflow/react` to `package.json`; Task 4 adds `d3-force` AND assumes `@xyflow/react` is already installed. Task 4 MUST run after Task 3 completes (same file, `package.json`/`package-lock.json`, sequential edits). Tasks 1 and 2 have no such constraint and may run in parallel with each other and with Task 3.
- Node id scheme, edge shape, and all `ImpactGraph`/`GraphNode`/`GraphEdge`/`GraphGap` types are exactly as Phase 5 shipped them (`frontend/src/lib/api.ts`) — this plan adds no new types there, only consumes existing ones. Verified current shape (read directly): `GraphNode = {id, kind: 'news'|'mechanism'|'sector'|'company', label, direction?, company_id?, ticker?, name?, confidence_score?, impact_level?, in_my_holdings?}`, `GraphEdge = {from, to, relation, direction, note, source}`.
- Every company-kind node click opens the SAME `ReasoningPanel` drawer pattern already used by all 6 grouping charts (Phase 6) — via `useCompanySelection(companies)` + `toggle(node.company_id!)` + `{selected && <ReasoningPanel company={selected} eventType={eventType} />}`. Mechanism/sector/news nodes are never clickable (they aren't companies — the aesthetic bar's "every company node clickable" requirement is scoped to company nodes specifically).
- Colors: no new hex values. `EDGE_RELATIONS` (10 values, mirrored from `backend/app/reasoning/rulebook.py`'s `EDGE_RELATIONS` since the frontend has no equivalent constant yet) gets its own color mapping in `colors.ts` by REUSING `SECTOR_COLOR`'s already-validated 10 hex values positionally (both lists have exactly 10 entries — confirmed) — no new palette validation needed. Portfolio ring (`ring-accent-secondary`) and direction colors (`bullish`/`bearish`) are also already-validated, reused as-is.
- **d3-force's layout is non-deterministic between runs** (default internal RNG jitters initial positions) — tests on `forceDirectedPositions` must assert STRUCTURAL properties (every node gets a finite, non-NaN `x`/`y`; no two nodes share the exact same io the point at start; the function returns an entry for every node id), never exact pixel coordinates.
- `@xyflow/react` requires a `ResizeObserver` in its rendering environment; jsdom (this project's test environment) does not provide one by default. If a chart test rendering `<ReactFlow>` fails with a `ResizeObserver is not defined` error, add a minimal polyfill to `frontend/src/test/setup.ts` (or wherever this project's global Vitest setup file lives — confirm the exact path first, don't guess) rather than avoiding the render. A minimal polyfill is sufficient for tests (React Flow only calls `observe`/`unobserve`/`disconnect`): `class ResizeObserver { observe() {} unobserve() {} disconnect() {} } global.ResizeObserver = ResizeObserver;`.
- Manual browser verification (drag/zoom/pan feel, dark AND light theme, a real repo-rate-cut alert through all 4 charts) is EXPLICITLY a required follow-up per this project's own established convention (no browser access in this environment) — flag it, do not claim it as done.
- Verified current code this plan is grounded against (read directly): `frontend/src/pages/AlertChartsPage.tsx` (current post-Phase-6 state, all 6 grouping charts already mounted, `1,4,5,6,7,8`), `frontend/src/features/visualize/graph/model.ts` (Phase 5's `buildGraph`/`longestChainPath`/`mechanismBackbone`/`ringsByImpactLevel`), `frontend/src/features/visualize/colors.ts` (`SECTOR_COLOR`'s exact 10 validated hex values), `frontend/src/features/visualize/charts/cards/CompanyCard.tsx` (the visual pattern `GraphNodeChip` mirrors), `frontend/src/features/visualize/charts/useCompanySelection.ts`, `frontend/src/components/ReasoningPanel.tsx`, `frontend/src/features/visualize/transforms.ts` (`TIME_HORIZON_ORDER`), `frontend/package.json` (no chart/graph library present yet).

---

### Task 1: `GraphNodeChip` (shared) + Supply Chain Graph (#3)

**Files:**
- Create: `frontend/src/features/visualize/charts/cards/GraphNodeChip.tsx`
- Test: `frontend/src/features/visualize/charts/cards/GraphNodeChip.test.tsx`
- Create: `frontend/src/features/visualize/charts/SupplyChainGraph.tsx`
- Test: `frontend/src/features/visualize/charts/SupplyChainGraph.test.tsx`

**Interfaces:**
- Produces: `GraphNodeChip({ node, onClick?, selected? })` (`./cards/GraphNodeChip`), reused by Tasks 2-4. `SupplyChainGraph({ graph, companies, eventType? })`, `ChartCardShell number={3}`.

- [ ] **Step 1: Write the failing `GraphNodeChip` tests**

Create `frontend/src/features/visualize/charts/cards/GraphNodeChip.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import GraphNodeChip from './GraphNodeChip';
import type { GraphNode } from '../../../../lib/api';

function node(overrides: Partial<GraphNode>): GraphNode {
  return { id: 'n1', kind: 'sector', label: 'banking', ...overrides };
}

describe('GraphNodeChip', () => {
  it('renders a company node with ticker, name, and direction glyph/confidence', () => {
    render(<GraphNodeChip node={node({ kind: 'company', company_id: 1, ticker: 'HDFCBANK.NS', label: 'HDFC Bank', name: 'HDFC Bank', direction: 'bullish', confidence_score: 80 })} />);
    expect(screen.getByText('HDFCBANK.NS')).toBeInTheDocument();
    expect(screen.getByText('HDFC Bank')).toBeInTheDocument();
    expect(screen.getByText('▲ 80%')).toBeInTheDocument();
  });

  it('renders a sector node with its label, not a ticker/confidence', () => {
    render(<GraphNodeChip node={node({ kind: 'sector', label: 'banking' })} />);
    expect(screen.getByText('Banking')).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it('renders a mechanism node with its raw label', () => {
    render(<GraphNodeChip node={node({ kind: 'mechanism', label: 'Repo Rate ↓' })} />);
    expect(screen.getByText('Repo Rate ↓')).toBeInTheDocument();
  });

  it('renders a news node with its label', () => {
    render(<GraphNodeChip node={node({ kind: 'news', label: 'RBI cuts repo rate by 25bps' })} />);
    expect(screen.getByText('RBI cuts repo rate by 25bps')).toBeInTheDocument();
  });

  it('shows the portfolio ring for a held company node', () => {
    render(<GraphNodeChip node={node({ kind: 'company', company_id: 1, ticker: 'AAA', label: 'Alpha', name: 'Alpha', direction: 'bullish', confidence_score: 50, in_my_holdings: true })} />);
    expect(screen.getByText('AAA').closest('div')).toHaveClass('ring-2', 'ring-accent-secondary');
  });

  it('is a clickable button when onClick is provided', async () => {
    const { default: userEvent } = await import('@testing-library/user-event');
    const onClick = vi.fn();
    render(<GraphNodeChip node={node({ kind: 'company', company_id: 1, ticker: 'AAA', label: 'Alpha', name: 'Alpha', direction: 'bullish', confidence_score: 50 })} onClick={onClick} />);
    await userEvent.click(screen.getByText('AAA'));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it('is a plain non-interactive block when onClick is omitted', () => {
    render(<GraphNodeChip node={node({ kind: 'sector', label: 'banking' })} />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `frontend/`): `npx vitest run src/features/visualize/charts/cards/GraphNodeChip.test.tsx`
Expected: FAIL (`Cannot find module './GraphNodeChip'`).

- [ ] **Step 3: Implement `GraphNodeChip.tsx`**

Create `frontend/src/features/visualize/charts/cards/GraphNodeChip.tsx`:

```tsx
import type { GraphNode } from '../../../../lib/api';
import { sectorColor } from '../../colors';
import { sectorLabel } from '../../transforms';

// Renders any ImpactGraph node (news/mechanism/sector/company) with the
// same visual language as CompanyCard, so a graph chart reads as part of
// the same system as the 6 grouping charts. Company-kind nodes get the
// portfolio ring (in_my_holdings) exactly like CompanyCard does; non-
// company kinds never do (only companies can be "held").
export default function GraphNodeChip({
  node,
  onClick,
  selected = false,
}: {
  node: GraphNode;
  onClick?: () => void;
  selected?: boolean;
}) {
  const isCompany = node.kind === 'company';
  const bearish = node.direction === 'bearish';

  const content = isCompany ? (
    <>
      <span className="font-data text-xs font-semibold text-ink">{node.ticker}</span>
      <span className="truncate font-editorial text-sm text-ink">{node.name}</span>
      {node.confidence_score != null && (
        <span className={`font-data text-xs ${bearish ? 'text-bearish' : 'text-bullish'}`}>
          <span aria-hidden="true">{bearish ? '▼' : '▲'}</span> {node.confidence_score}%
        </span>
      )}
    </>
  ) : (
    <>
      <span className="font-data text-[10px] uppercase tracking-widest text-muted">
        {node.kind === 'sector' ? 'Sector' : node.kind === 'mechanism' ? 'Mechanism' : 'News'}
      </span>
      <span className="truncate font-editorial text-sm text-ink">
        {node.kind === 'sector' ? sectorLabel(node.label) : node.label}
      </span>
    </>
  );

  const ringClass = isCompany && node.in_my_holdings ? 'ring-2 ring-accent-secondary' : '';
  const sectorBorder = node.kind === 'sector' ? sectorColor(node.label) : undefined;

  const className = `flex w-40 flex-col gap-0.5 rounded-lg border p-2.5 text-left theme-light:shadow-neu-sm ${
    selected ? 'border-ink theme-light:border-ink' : 'border-hairline theme-light:border-transparent'
  } ${ringClass}`;
  const style = sectorBorder ? { borderColor: sectorBorder } : undefined;

  if (!onClick) {
    return <div className={className} style={style}>{content}</div>;
  }

  return (
    <button type="button" onClick={onClick} aria-pressed={selected} className={className} style={style}>
      {content}
    </button>
  );
}
```

- [ ] **Step 4: Run `GraphNodeChip` tests to verify they pass**

Run: `npx vitest run src/features/visualize/charts/cards/GraphNodeChip.test.tsx`
Expected: PASS, all 7 tests.

- [ ] **Step 5: Write the failing `SupplyChainGraph` tests**

Create `frontend/src/features/visualize/charts/SupplyChainGraph.test.tsx`:

```tsx
import { render as rtlRender, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import SupplyChainGraph, { edgeBetween } from './SupplyChainGraph';
import type { AlertCompany, ImpactGraph } from '../../../lib/api';
import { LanguageProvider } from '../../../lib/language';

function render(graph: ImpactGraph, companies: AlertCompany[] = [], eventType?: string | null) {
  return rtlRender(
    <MemoryRouter>
      <LanguageProvider>
        <SupplyChainGraph graph={graph} companies={companies} eventType={eventType} />
      </LanguageProvider>
    </MemoryRouter>,
  );
}

function alertCompany(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because',
    key_points: [], confidence_score: 50, time_horizon: 'Short-Term', basis: 'direct_mention',
    confidence: 'llm_estimate', market: 'IN', in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

const chainGraph: ImpactGraph = {
  nodes: [
    { id: 'news', kind: 'news', label: 'Repo rate cut announced' },
    { id: 'mech:repo_rate_down', kind: 'mechanism', label: 'Repo Rate ↓' },
    { id: 'sector:banking', kind: 'sector', label: 'banking' },
    { id: 'company:1', kind: 'company', company_id: 1, ticker: 'HDFCBANK.NS', label: 'HDFC Bank', name: 'HDFC Bank', direction: 'bullish', confidence_score: 80 },
  ],
  edges: [
    { from: 'news', to: 'mech:repo_rate_down', relation: 'correlation', direction: 'bullish', note: 'n0', source: 'llm_only' },
    { from: 'mech:repo_rate_down', to: 'sector:banking', relation: 'credit_cost', direction: 'bullish', note: 'n1', source: 'rulebook_verified' },
    { from: 'sector:banking', to: 'company:1', relation: 'demand', direction: 'bullish', note: 'n2', source: 'llm_only' },
  ],
  gaps: [],
};

describe('SupplyChainGraph', () => {
  it('renders wrapped in ChartCardShell with number 3', () => {
    render(chainGraph);
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('Supply Chain Graph')).toBeInTheDocument();
  });

  it('renders the longest chain path left-to-right with relation labels on connectors', () => {
    render(chainGraph);
    expect(screen.getByText('Repo Rate ↓')).toBeInTheDocument();
    expect(screen.getByText('Banking')).toBeInTheDocument();
    expect(screen.getByText('HDFCBANK.NS')).toBeInTheDocument();
    expect(screen.getByText('credit_cost')).toBeInTheDocument();
    expect(screen.getByText('demand')).toBeInTheDocument();
  });

  it('renders nothing when the graph has no real path (news node only)', () => {
    const { container } = render({ nodes: [{ id: 'news', kind: 'news', label: 'x' }], edges: [], gaps: [] });
    expect(container).toBeEmptyDOMElement();
  });

  it('opens the ReasoningPanel when the terminal company node is tapped', async () => {
    render(chainGraph, [alertCompany({ company_id: 1, rationale: 'Lower rates lift loan demand.' })]);
    await userEvent.click(screen.getByText('HDFCBANK.NS'));
    expect(screen.getByText(/Lower rates lift loan demand/)).toBeInTheDocument();
  });

  it('does not make mechanism/sector nodes clickable', () => {
    render(chainGraph);
    expect(screen.getByText('Repo Rate ↓').closest('button')).toBeNull();
    expect(screen.getByText('Banking').closest('button')).toBeNull();
  });
});

describe('edgeBetween', () => {
  it('finds the edge connecting two given node ids', () => {
    const edge = edgeBetween(chainGraph, 'mech:repo_rate_down', 'sector:banking');
    expect(edge?.relation).toBe('credit_cost');
  });

  it('returns undefined when no edge connects the two ids', () => {
    expect(edgeBetween(chainGraph, 'news', 'company:1')).toBeUndefined();
  });
});
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `npx vitest run src/features/visualize/charts/SupplyChainGraph.test.tsx`
Expected: FAIL (`Cannot find module './SupplyChainGraph'`).

- [ ] **Step 7: Implement `SupplyChainGraph.tsx`**

Create `frontend/src/features/visualize/charts/SupplyChainGraph.tsx`:

```tsx
import type { AlertCompany, ImpactGraph } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { longestChainPath } from '../graph/model';
import ChartCardShell from './ChartCardShell';
import GraphNodeChip from './cards/GraphNodeChip';
import { useCompanySelection } from './useCompanySelection';

export function edgeBetween(graph: ImpactGraph, fromId: string, toId: string) {
  return graph.edges.find((e) => e.from === fromId && e.to === toId);
}

export default function SupplyChainGraph({
  graph,
  companies,
  eventType,
}: {
  graph: ImpactGraph;
  companies: AlertCompany[];
  eventType?: string | null;
}) {
  const { toggle, selected, selectedId } = useCompanySelection(companies);
  const path = longestChainPath(graph);

  if (path.length <= 1) return null;

  return (
    <ChartCardShell
      number={3}
      title="Supply Chain Graph"
      description="The longest single transmission path from this news to a company"
    >
      <div className="flex flex-col items-center gap-3 p-4">
        <div className="flex flex-wrap items-center justify-center gap-2">
          {path.map((node, i) => {
            const edge = i > 0 ? edgeBetween(graph, path[i - 1].id, node.id) : null;
            const isCompany = node.kind === 'company' && node.company_id != null;
            return (
              <div key={node.id} className="flex items-center gap-2">
                {i > 0 && (
                  <div className="flex flex-col items-center px-1 text-center">
                    <span aria-hidden="true" className="text-muted">→</span>
                    {edge && <span className="font-data text-[9px] uppercase tracking-widest text-muted">{edge.relation}</span>}
                  </div>
                )}
                <GraphNodeChip
                  node={node}
                  onClick={isCompany ? () => toggle(node.company_id as number) : undefined}
                  selected={isCompany && selectedId === node.company_id}
                />
              </div>
            );
          })}
        </div>
        {selected && <ReasoningPanel company={selected} eventType={eventType} />}
      </div>
    </ChartCardShell>
  );
}
```

- [ ] **Step 8: Run `SupplyChainGraph` tests to verify they pass**

Run: `npx vitest run src/features/visualize/charts/SupplyChainGraph.test.tsx`
Expected: PASS, all 7 tests.

- [ ] **Step 9: Run the full frontend suite + typecheck**

Run (from `frontend/`): `npx vitest run` and `npx tsc --noEmit`
Expected: both PASS, no regressions.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/features/visualize/charts/cards/GraphNodeChip.tsx frontend/src/features/visualize/charts/cards/GraphNodeChip.test.tsx frontend/src/features/visualize/charts/SupplyChainGraph.tsx frontend/src/features/visualize/charts/SupplyChainGraph.test.tsx
git commit -m "feat: add GraphNodeChip + Supply Chain Graph chart (#3)"
```

---

### Task 2: Economic Chain (#9)

**Files:**
- Create: `frontend/src/features/visualize/charts/EconomicChain.tsx`
- Test: `frontend/src/features/visualize/charts/EconomicChain.test.tsx`

**Interfaces:**
- Consumes: `GraphNodeChip` (Task 1), `mechanismBackbone` (Phase 5, `../graph/model`), `TIME_HORIZON_ORDER` (Phase 5-adjacent, already exists in `../transforms`).
- Produces: `EconomicChain({ graph, companies })`, `ChartCardShell number={9}`. No `eventType`/`ReasoningPanel` — this chart shows ONLY mechanism-kind nodes (no company nodes to click), so there is nothing to open a drawer for.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/features/visualize/charts/EconomicChain.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import EconomicChain, { reachableCompanyIds } from './EconomicChain';
import type { AlertCompany, ImpactGraph } from '../../../lib/api';

function alertCompany(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because',
    key_points: [], confidence_score: 50, time_horizon: 'Short-Term', basis: 'direct_mention',
    confidence: 'llm_estimate', market: 'IN', in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

const chainGraph: ImpactGraph = {
  nodes: [
    { id: 'news', kind: 'news', label: 'x' },
    { id: 'mech:a', kind: 'mechanism', label: 'Repo Rate ↓' },
    { id: 'mech:b', kind: 'mechanism', label: 'Borrowing Costs ↓' },
    { id: 'sector:banking', kind: 'sector', label: 'banking' },
    { id: 'company:1', kind: 'company', company_id: 1, ticker: 'HDFCBANK.NS', label: 'HDFC Bank', name: 'HDFC Bank', direction: 'bullish', confidence_score: 80 },
  ],
  edges: [
    { from: 'news', to: 'mech:a', relation: 'correlation', direction: 'bullish', note: 'n', source: 'llm_only' },
    { from: 'mech:a', to: 'mech:b', relation: 'credit_cost', direction: 'bullish', note: 'n', source: 'rulebook_verified' },
    { from: 'mech:b', to: 'sector:banking', relation: 'credit_cost', direction: 'bullish', note: 'n', source: 'rulebook_verified' },
    { from: 'sector:banking', to: 'company:1', relation: 'demand', direction: 'bullish', note: 'n', source: 'llm_only' },
  ],
  gaps: [],
};

describe('EconomicChain', () => {
  it('renders wrapped in ChartCardShell with number 9', () => {
    render(<EconomicChain graph={chainGraph} companies={[]} />);
    expect(screen.getByText('9')).toBeInTheDocument();
    expect(screen.getByText('Economic Chain')).toBeInTheDocument();
  });

  it('renders every mechanism-kind node vertically', () => {
    render(<EconomicChain graph={chainGraph} companies={[]} />);
    expect(screen.getByText('Repo Rate ↓')).toBeInTheDocument();
    expect(screen.getByText('Borrowing Costs ↓')).toBeInTheDocument();
  });

  it('never renders sector/company/news nodes', () => {
    render(<EconomicChain graph={chainGraph} companies={[]} />);
    expect(screen.queryByText('Banking')).not.toBeInTheDocument();
    expect(screen.queryByText('HDFCBANK.NS')).not.toBeInTheDocument();
  });

  it('labels a mechanism node with the time horizon of the companies it reaches', () => {
    render(
      <EconomicChain
        graph={chainGraph}
        companies={[alertCompany({ company_id: 1, time_horizon: 'Medium-Term' })]}
      />,
    );
    expect(screen.getAllByText('Medium-Term').length).toBeGreaterThan(0);
  });

  it('renders nothing when the graph has no mechanism nodes', () => {
    const { container } = render(
      <EconomicChain
        graph={{ nodes: [{ id: 'news', kind: 'news', label: 'x' }], edges: [], gaps: [] }}
        companies={[]}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe('reachableCompanyIds', () => {
  it('returns every company id reachable via any forward path from a node', () => {
    expect(reachableCompanyIds(chainGraph, 'mech:a')).toEqual(new Set([1]));
  });

  it('returns an empty set for a node with no downstream companies', () => {
    expect(reachableCompanyIds(chainGraph, 'company:1')).toEqual(new Set());
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `frontend/`): `npx vitest run src/features/visualize/charts/EconomicChain.test.tsx`
Expected: FAIL (`Cannot find module './EconomicChain'`).

- [ ] **Step 3: Implement `EconomicChain.tsx`**

Create `frontend/src/features/visualize/charts/EconomicChain.tsx`:

```tsx
import type { AlertCompany, ImpactGraph } from '../../../lib/api';
import { mechanismBackbone } from '../graph/model';
import { TIME_HORIZON_ORDER } from '../transforms';
import ChartCardShell from './ChartCardShell';
import GraphNodeChip from './cards/GraphNodeChip';

// Every company_id reachable by walking forward (via graph.edges) from
// startId -- used to find which companies a given mechanism node's effects
// eventually reach, so the chain can be labeled with their time horizons.
export function reachableCompanyIds(graph: ImpactGraph, startId: string): Set<number> {
  const outgoing = new Map<string, string[]>();
  for (const edge of graph.edges) {
    const list = outgoing.get(edge.from) ?? [];
    list.push(edge.to);
    outgoing.set(edge.from, list);
  }
  const nodesById = new Map(graph.nodes.map((n) => [n.id, n]));
  const visited = new Set<string>([startId]);
  const stack = [startId];
  const companyIds = new Set<number>();

  while (stack.length > 0) {
    const current = stack.pop() as string;
    for (const next of outgoing.get(current) ?? []) {
      if (visited.has(next)) continue;
      visited.add(next);
      const node = nodesById.get(next);
      if (node?.kind === 'company' && node.company_id != null) companyIds.add(node.company_id);
      stack.push(next);
    }
  }
  return companyIds;
}

export default function EconomicChain({
  graph,
  companies,
}: {
  graph: ImpactGraph;
  companies: AlertCompany[];
}) {
  const mechanisms = mechanismBackbone(graph);

  if (mechanisms.length === 0) return null;

  return (
    <ChartCardShell
      number={9}
      title="Economic Chain"
      description="The mechanism backbone of this news, from immediate effects to longer-term ones"
    >
      <div className="flex flex-col items-center gap-3 p-4">
        {mechanisms.map((node, i) => {
          const reachedIds = reachableCompanyIds(graph, node.id);
          const horizons = TIME_HORIZON_ORDER.filter((h) =>
            companies.some((c) => reachedIds.has(c.company_id) && c.time_horizon === h),
          );
          return (
            <div key={node.id} className="flex w-full max-w-xs flex-col items-center gap-1">
              {i > 0 && <span aria-hidden="true" className="text-muted">↓</span>}
              <GraphNodeChip node={node} />
              {horizons.length > 0 && (
                <span className="font-data text-[10px] uppercase tracking-widest text-muted">{horizons.join(' · ')}</span>
              )}
            </div>
          );
        })}
      </div>
    </ChartCardShell>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/features/visualize/charts/EconomicChain.test.tsx`
Expected: PASS, all 7 tests.

- [ ] **Step 5: Run the full frontend suite + typecheck**

Run (from `frontend/`): `npx vitest run` and `npx tsc --noEmit`
Expected: both PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/visualize/charts/EconomicChain.tsx frontend/src/features/visualize/charts/EconomicChain.test.tsx
git commit -m "feat: add Economic Chain chart (#9)"
```

---

### Task 3: Ripple Effect Graph (#2) — adds `@xyflow/react`

**Files:**
- Modify: `frontend/package.json` (adds `@xyflow/react`)
- Modify: `frontend/src/features/visualize/colors.ts` (adds `EDGE_RELATIONS` + `relationColor`)
- Modify: `frontend/src/features/visualize/colors.test.ts`
- Create: `frontend/src/features/visualize/graph/layout.ts` (pure layout math, framework-independent)
- Test: `frontend/src/features/visualize/graph/layout.test.ts`
- Create: `frontend/src/features/visualize/charts/RippleGraph.tsx`
- Test: `frontend/src/features/visualize/charts/RippleGraph.test.tsx`

**Interfaces:**
- Produces: `ripplePositions(graph) -> Record<string, {x: number; y: number}>` (`../graph/layout`), `RippleGraph({ graph, companies, eventType? })`, `ChartCardShell number={2}`, `EDGE_RELATIONS: string[]` + `relationColor(relation) -> string` (`../colors`).

- [ ] **Step 1: Add the `@xyflow/react` dependency**

Run (from `frontend/`): `npm install @xyflow/react`
Verify `frontend/package.json`'s `dependencies` now includes `"@xyflow/react": "^..."` (whatever version npm resolves — do not hand-edit the version string, let npm write it).

- [ ] **Step 2: Write the failing `relationColor` tests**

Add to `frontend/src/features/visualize/colors.test.ts` (read the file first to match its existing style/imports):

```typescript
describe('relationColor', () => {
  it('returns a distinct color for each of the 10 EDGE_RELATIONS values', () => {
    const colors = new Set(EDGE_RELATIONS.map((r) => relationColor(r)));
    expect(colors.size).toBe(10);
  });

  it('falls back to the "other" sector color for an unrecognized relation', () => {
    expect(relationColor('not_a_real_relation')).toBe(sectorColor('other'));
  });
});
```

(`sectorColor` is the existing function this file already imports/exports from — add it to this test file's import line alongside `relationColor`/`EDGE_RELATIONS` if it isn't already imported there.)

- [ ] **Step 3: Run tests to verify they fail**

Run (from `frontend/`): `npx vitest run src/features/visualize/colors.test.ts`
Expected: FAIL (`EDGE_RELATIONS`/`relationColor` don't exist yet).

- [ ] **Step 4: Add `EDGE_RELATIONS` + `relationColor` to `colors.ts`**

Add to `frontend/src/features/visualize/colors.ts`, after `sectorColor`'s definition:

```typescript
// Mirrors backend/app/reasoning/rulebook.py's EDGE_RELATIONS exactly (the
// frontend has no equivalent constant yet -- GraphEdge.relation is typed
// as a plain string, not a literal union, so this is the closest thing to
// a canonical list on this side).
export const EDGE_RELATIONS = [
  'input_cost', 'credit_cost', 'demand', 'supplier', 'customer',
  'competitor', 'commodity', 'regulation', 'currency', 'correlation',
] as const;

// Same 10 already-validated hex values as SECTOR_COLOR above (see its own
// validation comment), reassigned to EDGE_RELATIONS positionally -- both
// lists have exactly 10 entries, so no new hex/no new validator run is
// needed.
const RELATION_COLOR: Record<string, string> = {
  input_cost: '#E85D4C',
  credit_cost: '#4A90D9',
  demand: '#C97F0E',
  supplier: '#12A08C',
  customer: '#9B7EDE',
  competitor: '#3E9B5C',
  commodity: '#A0522D',
  regulation: '#D4708C',
  currency: '#6C8CD5',
  correlation: '#557C30',
};

export function relationColor(relation: string): string {
  return RELATION_COLOR[relation] ?? FALLBACK_COLOR;
}
```

- [ ] **Step 5: Run `colors.test.ts` to verify it passes**

Run: `npx vitest run src/features/visualize/colors.test.ts`
Expected: PASS.

- [ ] **Step 6: Write the failing `ripplePositions` tests**

Create `frontend/src/features/visualize/graph/layout.test.ts`:

```typescript
import { describe, expect, it } from 'vitest';
import { ripplePositions } from './layout';
import type { ImpactGraph } from '../../../lib/api';

const graph: ImpactGraph = {
  nodes: [
    { id: 'news', kind: 'news', label: 'x' },
    { id: 'mech:a', kind: 'mechanism', label: 'A' },
    { id: 'sector:banking', kind: 'sector', label: 'banking' },
    { id: 'company:1', kind: 'company', company_id: 1, ticker: 'AAA', label: 'Alpha', name: 'Alpha', direction: 'bullish', confidence_score: 50, impact_level: 'direct' },
    { id: 'company:2', kind: 'company', company_id: 2, ticker: 'BBB', label: 'Beta', name: 'Beta', direction: 'bearish', confidence_score: 40, impact_level: 'indirect_l1' },
  ],
  edges: [],
  gaps: [],
};

describe('ripplePositions', () => {
  it('places the news node at the origin', () => {
    const positions = ripplePositions(graph);
    expect(positions.news).toEqual({ x: 0, y: 0 });
  });

  it('places every non-news node away from the origin', () => {
    const positions = ripplePositions(graph);
    for (const id of ['mech:a', 'sector:banking', 'company:1', 'company:2']) {
      expect(positions[id].x !== 0 || positions[id].y !== 0).toBe(true);
    }
  });

  it('places direct-impact companies closer to the center than indirect_l1 companies', () => {
    const positions = ripplePositions(graph);
    const dist = (p: { x: number; y: number }) => Math.sqrt(p.x ** 2 + p.y ** 2);
    expect(dist(positions['company:1'])).toBeLessThan(dist(positions['company:2']));
  });

  it('returns a position for every node in the graph', () => {
    const positions = ripplePositions(graph);
    for (const node of graph.nodes) {
      expect(positions[node.id]).toBeDefined();
    }
  });

  it('handles a graph with no news node without throwing', () => {
    const noNews: ImpactGraph = { nodes: [{ id: 'sector:banking', kind: 'sector', label: 'banking' }], edges: [], gaps: [] };
    expect(() => ripplePositions(noNews)).not.toThrow();
  });
});
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `npx vitest run src/features/visualize/graph/layout.test.ts`
Expected: FAIL (`Cannot find module './layout'`).

- [ ] **Step 8: Implement `ripplePositions` in `graph/layout.ts`**

Create `frontend/src/features/visualize/graph/layout.ts`:

```typescript
import type { ImpactGraph } from '../../../lib/api';
import { ringsByImpactLevel } from './model';

const RING_SPACING = 160;

function placeRing(positions: Record<string, { x: number; y: number }>, ids: string[], ringIndex: number) {
  const radius = ringIndex * RING_SPACING;
  const count = ids.length;
  ids.forEach((id, i) => {
    const angle = (2 * Math.PI * i) / count;
    positions[id] = { x: radius * Math.cos(angle), y: radius * Math.sin(angle) };
  });
}

// Pure layout math for the Ripple Effect Graph (#2) -- news at the center,
// mechanism/sector nodes on one middle ring, then company nodes on
// successive rings by impact_level (direct innermost). Framework-
// independent (no React Flow types here) so it's unit-testable without
// mounting any chart.
export function ripplePositions(graph: ImpactGraph): Record<string, { x: number; y: number }> {
  const positions: Record<string, { x: number; y: number }> = {};

  const news = graph.nodes.find((n) => n.kind === 'news');
  if (news) positions[news.id] = { x: 0, y: 0 };

  const midLayer = graph.nodes.filter((n) => n.kind === 'mechanism' || n.kind === 'sector');
  if (midLayer.length > 0) placeRing(positions, midLayer.map((n) => n.id), 1);

  ringsByImpactLevel(graph).forEach((ring, ringIndex) => {
    placeRing(positions, ring.nodes.map((n) => n.id), ringIndex + 2);
  });

  return positions;
}
```

- [ ] **Step 9: Run `layout.test.ts` to verify it passes**

Run: `npx vitest run src/features/visualize/graph/layout.test.ts`
Expected: PASS, all 5 tests.

- [ ] **Step 10: Write the failing `RippleGraph` tests**

Confirm the exact path of this project's global Vitest setup file first (check `frontend/vite.config.ts` or `vitest.config.ts` for a `setupFiles` entry) — you'll need it in Step 12 if a `ResizeObserver` polyfill turns out to be necessary.

Create `frontend/src/features/visualize/charts/RippleGraph.test.tsx`:

```tsx
import { render as rtlRender, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import RippleGraph from './RippleGraph';
import type { AlertCompany, ImpactGraph } from '../../../lib/api';
import { LanguageProvider } from '../../../lib/language';

function render(graph: ImpactGraph, companies: AlertCompany[] = [], eventType?: string | null) {
  return rtlRender(
    <MemoryRouter>
      <LanguageProvider>
        <RippleGraph graph={graph} companies={companies} eventType={eventType} />
      </LanguageProvider>
    </MemoryRouter>,
  );
}

function alertCompany(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because',
    key_points: [], confidence_score: 50, time_horizon: 'Short-Term', basis: 'direct_mention',
    confidence: 'llm_estimate', market: 'IN', in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

const graph: ImpactGraph = {
  nodes: [
    { id: 'news', kind: 'news', label: 'Repo rate cut' },
    { id: 'sector:banking', kind: 'sector', label: 'banking' },
    { id: 'company:1', kind: 'company', company_id: 1, ticker: 'HDFCBANK.NS', label: 'HDFC Bank', name: 'HDFC Bank', direction: 'bullish', confidence_score: 80, impact_level: 'direct' },
  ],
  edges: [
    { from: 'news', to: 'sector:banking', relation: 'correlation', direction: 'bullish', note: 'n0', source: 'llm_only' },
    { from: 'sector:banking', to: 'company:1', relation: 'demand', direction: 'bullish', note: 'n1', source: 'rulebook_pruned' },
  ],
  gaps: [],
};

describe('RippleGraph', () => {
  it('renders wrapped in ChartCardShell with number 2', () => {
    render(graph);
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.getByText('Ripple Effect Graph')).toBeInTheDocument();
  });

  it('renders nothing for a graph with only the news node', () => {
    const { container } = render({ nodes: [{ id: 'news', kind: 'news', label: 'x' }], edges: [], gaps: [] });
    expect(container).toBeEmptyDOMElement();
  });

  it('shows a toggle for pruned edges only when at least one exists', () => {
    render(graph);
    expect(screen.getByText(/pruned edges/i)).toBeInTheDocument();
  });

  it('does not show a pruned-edge toggle when there are none', () => {
    const noPruned: ImpactGraph = {
      ...graph,
      edges: graph.edges.map((e) => ({ ...e, source: 'llm_only' })),
    };
    render(noPruned);
    expect(screen.queryByText(/pruned edges/i)).not.toBeInTheDocument();
  });

  it('opens the ReasoningPanel when a company node is tapped', async () => {
    render(graph, [alertCompany({ company_id: 1, rationale: 'Lower rates lift loan demand.' })]);
    await userEvent.click(screen.getByText('HDFCBANK.NS'));
    expect(screen.getByText(/Lower rates lift loan demand/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 11: Run tests to verify they fail**

Run: `npx vitest run src/features/visualize/charts/RippleGraph.test.tsx`
Expected: FAIL (`Cannot find module './RippleGraph'`).

- [ ] **Step 12: Implement `RippleGraph.tsx`**

Create `frontend/src/features/visualize/charts/RippleGraph.tsx`:

```tsx
import { useMemo, useState } from 'react';
import { Background, Controls, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import type { AlertCompany, GraphNode, ImpactGraph } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { ripplePositions } from '../graph/layout';
import ChartCardShell from './ChartCardShell';
import GraphNodeChip from './cards/GraphNodeChip';
import { useCompanySelection } from './useCompanySelection';

interface FlowNodeData {
  node: GraphNode;
  onClick?: () => void;
  selected: boolean;
  [key: string]: unknown;
}

function FlowNode({ data }: NodeProps<Node<FlowNodeData>>) {
  return (
    <>
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      <GraphNodeChip node={data.node} onClick={data.onClick} selected={data.selected} />
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
    </>
  );
}

const nodeTypes = { graphNode: FlowNode };

export default function RippleGraph({
  graph,
  companies,
  eventType,
}: {
  graph: ImpactGraph;
  companies: AlertCompany[];
  eventType?: string | null;
}) {
  const { toggle, selected, selectedId } = useCompanySelection(companies);
  const [showPruned, setShowPruned] = useState(false);

  const positions = useMemo(() => ripplePositions(graph), [graph]);
  const hasPruned = graph.edges.some((e) => e.source === 'rulebook_pruned');
  const visibleEdges = showPruned ? graph.edges : graph.edges.filter((e) => e.source !== 'rulebook_pruned');

  const flowNodes: Node<FlowNodeData>[] = useMemo(
    () =>
      graph.nodes.map((node) => {
        const isCompany = node.kind === 'company' && node.company_id != null;
        return {
          id: node.id,
          type: 'graphNode',
          position: positions[node.id] ?? { x: 0, y: 0 },
          data: {
            node,
            onClick: isCompany ? () => toggle(node.company_id as number) : undefined,
            selected: isCompany && selectedId === node.company_id,
          },
        };
      }),
    [graph.nodes, positions, selectedId, toggle],
  );

  const flowEdges: Edge[] = visibleEdges.map((edge, i) => ({
    id: `${edge.from}-${edge.to}-${i}`,
    source: edge.from,
    target: edge.to,
    label: edge.relation,
    style: {
      stroke: edge.direction === 'bearish' ? 'rgb(var(--color-bearish))' : 'rgb(var(--color-bullish))',
      strokeDasharray: edge.source === 'rulebook_pruned' ? '4 4' : undefined,
      opacity: edge.source === 'rulebook_pruned' ? 0.4 : 1,
    },
  }));

  if (graph.nodes.length <= 1) return null;

  return (
    <ChartCardShell
      number={2}
      title="Ripple Effect Graph"
      description="News radiating outward through mechanisms, sectors, and companies"
    >
      <div className="flex flex-col gap-2 p-4">
        {hasPruned && (
          <button
            type="button"
            onClick={() => setShowPruned((v) => !v)}
            className="self-start rounded-md border border-hairline px-2 py-1 font-data text-[10px] uppercase tracking-widest text-muted hover:text-ink"
          >
            {showPruned ? 'Hide pruned edges' : 'Show pruned edges'}
          </button>
        )}
        <div style={{ height: 420 }} className="w-full overflow-hidden rounded-lg border border-hairline">
          <ReactFlow nodes={flowNodes} edges={flowEdges} nodeTypes={nodeTypes} fitView minZoom={0.3} maxZoom={1.5}>
            <Background />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
        {selected && <ReasoningPanel company={selected} eventType={eventType} />}
      </div>
    </ChartCardShell>
  );
}
```

- [ ] **Step 13: Run `RippleGraph` tests to verify they pass**

Run: `npx vitest run src/features/visualize/charts/RippleGraph.test.tsx`

If this fails with `ReferenceError: ResizeObserver is not defined` (a real possibility -- `@xyflow/react` calls it internally and jsdom doesn't provide one): add a minimal polyfill to this project's global Vitest setup file (the path you confirmed in Step 10) --

```typescript
class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
// @ts-expect-error -- jsdom has no ResizeObserver; @xyflow/react needs one present to mount.
global.ResizeObserver = ResizeObserver;
```

Re-run after adding the polyfill. Expected: PASS, all 5 tests.

- [ ] **Step 14: Run the full frontend suite + typecheck**

Run (from `frontend/`): `npx vitest run` and `npx tsc --noEmit`
Expected: both PASS, no regressions. If the `ResizeObserver` polyfill was added to a shared setup file, confirm it doesn't change behavior for any unrelated existing test (it shouldn't -- a no-op class only used by code that calls it).

- [ ] **Step 15: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/features/visualize/colors.ts frontend/src/features/visualize/colors.test.ts frontend/src/features/visualize/graph/layout.ts frontend/src/features/visualize/graph/layout.test.ts frontend/src/features/visualize/charts/RippleGraph.tsx frontend/src/features/visualize/charts/RippleGraph.test.tsx
git add frontend/src/test/setup.ts 2>/dev/null || true
git commit -m "feat: add Ripple Effect Graph chart (#2), first @xyflow/react usage"
```

---

### Task 4: Knowledge Graph (#10) — adds `d3-force`

**Files:**
- Modify: `frontend/package.json` (adds `d3-force` — MUST run after Task 3, same file)
- Create: `frontend/src/features/visualize/charts/KnowledgeGraph.tsx`
- Test: `frontend/src/features/visualize/charts/KnowledgeGraph.test.tsx`
- Modify: `frontend/src/features/visualize/graph/layout.ts`
- Modify: `frontend/src/features/visualize/graph/layout.test.ts`

**Interfaces:**
- Consumes: `GraphNodeChip`, `nodeTypes`/`FlowNode` pattern (Task 3, `@xyflow/react` already installed), `EDGE_RELATIONS`/`relationColor` (Task 3, `../colors`).
- Produces: `forceDirectedPositions(graph) -> Record<string, {x: number; y: number}>` (`../graph/layout`), `KnowledgeGraph({ graph, companies, eventType? })`, `ChartCardShell number={10}` with a `legend` built from `EDGE_RELATIONS`/`relationColor`.

- [ ] **Step 1: Add the `d3-force` dependency**

Run (from `frontend/`): `npm install d3-force` and `npm install --save-dev @types/d3-force`
Verify `frontend/package.json`'s `dependencies` includes `"d3-force": "^..."` and `devDependencies` includes `"@types/d3-force": "^..."`.

- [ ] **Step 2: Write the failing `forceDirectedPositions` tests**

In `frontend/src/features/visualize/graph/layout.test.ts` (created by Task 3), change the existing `import { ripplePositions } from './layout';` line to:

```typescript
import { forceDirectedPositions, ripplePositions } from './layout';
```

Then add, appended after the existing `describe('ripplePositions', ...)` block:

```typescript
describe('forceDirectedPositions', () => {
  const smallGraph: ImpactGraph = {
    nodes: [
      { id: 'news', kind: 'news', label: 'x' },
      { id: 'sector:banking', kind: 'sector', label: 'banking' },
      { id: 'company:1', kind: 'company', company_id: 1, ticker: 'AAA', label: 'Alpha', name: 'Alpha', direction: 'bullish', confidence_score: 50 },
    ],
    edges: [
      { from: 'news', to: 'sector:banking', relation: 'correlation', direction: 'bullish', note: 'n', source: 'llm_only' },
      { from: 'sector:banking', to: 'company:1', relation: 'demand', direction: 'bullish', note: 'n', source: 'llm_only' },
    ],
    gaps: [],
  };

  it('returns a finite, non-NaN position for every node', () => {
    const positions = forceDirectedPositions(smallGraph);
    for (const node of smallGraph.nodes) {
      expect(Number.isFinite(positions[node.id].x)).toBe(true);
      expect(Number.isFinite(positions[node.id].y)).toBe(true);
    }
  });

  it('does not throw on a graph with no edges (isolated nodes)', () => {
    const isolated: ImpactGraph = { nodes: smallGraph.nodes, edges: [], gaps: [] };
    expect(() => forceDirectedPositions(isolated)).not.toThrow();
  });

  it('does not throw on an empty graph', () => {
    expect(() => forceDirectedPositions({ nodes: [], edges: [], gaps: [] })).not.toThrow();
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run (from `frontend/`): `npx vitest run src/features/visualize/graph/layout.test.ts -t forceDirectedPositions`
Expected: FAIL (`forceDirectedPositions` doesn't exist yet).

- [ ] **Step 4: Implement `forceDirectedPositions` in `graph/layout.ts`**

Add to `frontend/src/features/visualize/graph/layout.ts`:

```typescript
import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation } from 'd3-force';

interface SimNode {
  id: string;
  x?: number;
  y?: number;
}

// One-shot (not live-animated) force simulation: run a fixed number of
// ticks synchronously, then return the settled positions. A live/
// continuously-animated simulation would be more visually dynamic but is
// materially riskier to get right without browser access to actually see
// it settle -- a deterministic tick count keeps this reliable and fast.
// Positions ARE non-deterministic between calls (d3-force's default
// internal RNG jitters initial placement) -- callers/tests must never
// assert exact coordinates, only structural properties (finite, no throw).
export function forceDirectedPositions(graph: ImpactGraph): Record<string, { x: number; y: number }> {
  const nodes: SimNode[] = graph.nodes.map((n) => ({ id: n.id }));
  if (nodes.length === 0) return {};

  const links = graph.edges
    .filter((e) => graph.nodes.some((n) => n.id === e.from) && graph.nodes.some((n) => n.id === e.to))
    .map((e) => ({ source: e.from, target: e.to }));

  const simulation = forceSimulation(nodes)
    .force('link', forceLink(links).id((d) => (d as SimNode).id).distance(140))
    .force('charge', forceManyBody().strength(-260))
    .force('center', forceCenter(0, 0))
    .force('collide', forceCollide(70))
    .stop();

  for (let i = 0; i < 300; i += 1) simulation.tick();

  const positions: Record<string, { x: number; y: number }> = {};
  for (const node of nodes) {
    positions[node.id] = { x: node.x ?? 0, y: node.y ?? 0 };
  }
  return positions;
}
```

- [ ] **Step 5: Run `layout.test.ts` to verify it passes**

Run: `npx vitest run src/features/visualize/graph/layout.test.ts`
Expected: PASS, all tests (the 5 `ripplePositions` tests from Task 3 plus the 3 new `forceDirectedPositions` tests).

- [ ] **Step 6: Write the failing `KnowledgeGraph` tests**

Create `frontend/src/features/visualize/charts/KnowledgeGraph.test.tsx`:

```tsx
import { render as rtlRender, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import KnowledgeGraph from './KnowledgeGraph';
import type { AlertCompany, ImpactGraph } from '../../../lib/api';
import { LanguageProvider } from '../../../lib/language';

function render(graph: ImpactGraph, companies: AlertCompany[] = [], eventType?: string | null) {
  return rtlRender(
    <MemoryRouter>
      <LanguageProvider>
        <KnowledgeGraph graph={graph} companies={companies} eventType={eventType} />
      </LanguageProvider>
    </MemoryRouter>,
  );
}

function alertCompany(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1, ticker: 'AAA', name: 'Alpha Co', index_tier: 'NIFTY50',
    direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'because',
    key_points: [], confidence_score: 50, time_horizon: 'Short-Term', basis: 'direct_mention',
    confidence: 'llm_estimate', market: 'IN', in_my_holdings: false, past_mentions: [],
    ...overrides,
  };
}

const graph: ImpactGraph = {
  nodes: [
    { id: 'news', kind: 'news', label: 'Repo rate cut' },
    { id: 'sector:banking', kind: 'sector', label: 'banking' },
    { id: 'company:1', kind: 'company', company_id: 1, ticker: 'HDFCBANK.NS', label: 'HDFC Bank', name: 'HDFC Bank', direction: 'bullish', confidence_score: 80, in_my_holdings: true },
  ],
  edges: [
    { from: 'news', to: 'sector:banking', relation: 'correlation', direction: 'bullish', note: 'n0', source: 'llm_only' },
    { from: 'sector:banking', to: 'company:1', relation: 'demand', direction: 'bullish', note: 'n1', source: 'llm_only' },
  ],
  gaps: [],
};

describe('KnowledgeGraph', () => {
  it('renders wrapped in ChartCardShell with number 10', () => {
    render(graph);
    expect(screen.getByText('10')).toBeInTheDocument();
    expect(screen.getByText('Knowledge Graph')).toBeInTheDocument();
  });

  it('renders nothing for a graph with only the news node', () => {
    const { container } = render({ nodes: [{ id: 'news', kind: 'news', label: 'x' }], edges: [], gaps: [] });
    expect(container).toBeEmptyDOMElement();
  });

  it('shows a legend covering every relation actually present in the graph', () => {
    render(graph);
    expect(screen.getByText('correlation')).toBeInTheDocument();
    expect(screen.getByText('demand')).toBeInTheDocument();
  });

  it('opens the ReasoningPanel when a held company node is tapped', async () => {
    render(graph, [alertCompany({ company_id: 1, in_my_holdings: true, rationale: 'Lower rates lift loan demand.' })]);
    await userEvent.click(screen.getByText('HDFCBANK.NS'));
    expect(screen.getByText(/Lower rates lift loan demand/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `npx vitest run src/features/visualize/charts/KnowledgeGraph.test.tsx`
Expected: FAIL (`Cannot find module './KnowledgeGraph'`).

- [ ] **Step 8: Implement `KnowledgeGraph.tsx`**

Create `frontend/src/features/visualize/charts/KnowledgeGraph.tsx`:

```tsx
import { useMemo } from 'react';
import { Background, Controls, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import type { AlertCompany, GraphNode, ImpactGraph } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { EDGE_RELATIONS, relationColor } from '../colors';
import { forceDirectedPositions } from '../graph/layout';
import ChartCardShell from './ChartCardShell';
import GraphNodeChip from './cards/GraphNodeChip';
import { useCompanySelection } from './useCompanySelection';

interface FlowNodeData {
  node: GraphNode;
  onClick?: () => void;
  selected: boolean;
  size: number;
  [key: string]: unknown;
}

function FlowNode({ data }: NodeProps<Node<FlowNodeData>>) {
  return (
    <div style={{ width: data.size }}>
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      <GraphNodeChip node={data.node} onClick={data.onClick} selected={data.selected} />
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
    </div>
  );
}

const nodeTypes = { graphNode: FlowNode };

function sizeFor(confidenceScore: number | undefined): number {
  return 120 + (confidenceScore ?? 50) * 0.6;
}

export default function KnowledgeGraph({
  graph,
  companies,
  eventType,
}: {
  graph: ImpactGraph;
  companies: AlertCompany[];
  eventType?: string | null;
}) {
  const { toggle, selected, selectedId } = useCompanySelection(companies);

  const positions = useMemo(() => forceDirectedPositions(graph), [graph]);

  const flowNodes: Node<FlowNodeData>[] = useMemo(
    () =>
      graph.nodes.map((node) => {
        const isCompany = node.kind === 'company' && node.company_id != null;
        return {
          id: node.id,
          type: 'graphNode',
          position: positions[node.id] ?? { x: 0, y: 0 },
          data: {
            node,
            onClick: isCompany ? () => toggle(node.company_id as number) : undefined,
            selected: isCompany && selectedId === node.company_id,
            size: sizeFor(node.confidence_score),
          },
        };
      }),
    [graph.nodes, positions, selectedId, toggle],
  );

  const presentRelations = new Set(graph.edges.map((e) => e.relation));
  const flowEdges: Edge[] = graph.edges.map((edge, i) => ({
    id: `${edge.from}-${edge.to}-${i}`,
    source: edge.from,
    target: edge.to,
    style: {
      stroke: relationColor(edge.relation),
      strokeDasharray: edge.source === 'rulebook_pruned' ? '4 4' : undefined,
      opacity: edge.source === 'rulebook_pruned' ? 0.4 : 1,
    },
  }));

  if (graph.nodes.length <= 1) return null;

  const legend = EDGE_RELATIONS.filter((r) => presentRelations.has(r)).map((r) => ({
    label: r,
    color: relationColor(r),
  }));

  return (
    <ChartCardShell
      number={10}
      title="Knowledge Graph"
      description="The full picture -- every node and verified edge, laid out by real connection strength"
      legend={legend}
    >
      <div style={{ height: 480 }} className="w-full overflow-hidden rounded-lg border border-hairline">
        <ReactFlow nodes={flowNodes} edges={flowEdges} nodeTypes={nodeTypes} fitView minZoom={0.2} maxZoom={1.5}>
          <Background />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      {selected && (
        <div className="p-4">
          <ReasoningPanel company={selected} eventType={eventType} />
        </div>
      )}
    </ChartCardShell>
  );
}
```

- [ ] **Step 9: Run `KnowledgeGraph` tests to verify they pass**

Run: `npx vitest run src/features/visualize/charts/KnowledgeGraph.test.tsx`
Expected: PASS, all 4 tests (the `ResizeObserver` polyfill from Task 3, if it was needed there, already covers this chart too — no new polyfill work expected here).

- [ ] **Step 10: Run the full frontend suite + typecheck**

Run (from `frontend/`): `npx vitest run` and `npx tsc --noEmit`
Expected: both PASS, no regressions.

- [ ] **Step 11: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/features/visualize/charts/KnowledgeGraph.tsx frontend/src/features/visualize/charts/KnowledgeGraph.test.tsx frontend/src/features/visualize/graph/layout.ts frontend/src/features/visualize/graph/layout.test.ts
git commit -m "feat: add Knowledge Graph chart (#10), real force-directed layout via d3-force"
```

---

### Task 5: Mount all 4 graph charts on `AlertChartsPage`

**Files:**
- Modify: `frontend/src/pages/AlertChartsPage.tsx`
- Modify: `frontend/src/pages/AlertChartsPage.test.tsx`

**Interfaces:**
- Consumes: `buildGraph` (Phase 5, `../features/visualize/graph/model`), `SupplyChainGraph`/`EconomicChain`/`RippleGraph`/`KnowledgeGraph` (Tasks 1-4).

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/pages/AlertChartsPage.test.tsx` (same file/conventions Phase 6 Task 3 already established — `alert()` factory, `renderPage()` helper, `vi.spyOn(api, 'getAlert')`):

```tsx
it('renders all ten charts in numeric order for an alert with a rich cascade', async () => {
  vi.spyOn(api, 'getAlert').mockResolvedValue(alert({
    event_type: 'repo_rate_change',
    companies: [
      {
        company_id: 1, ticker: 'HDFCBANK.NS', name: 'HDFC Bank', index_tier: 'NIFTY50',
        sector: 'banking', direction: 'bullish', magnitude_low: 2, magnitude_high: 4,
        rationale: 'Lower rates lift loan demand.', key_points: ['Rates ease'], confidence_score: 80,
        time_horizon: 'Short-Term', basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN',
        in_my_holdings: false, past_mentions: [], impact_level: 'direct', parent_company_id: null,
      },
    ],
    graph: {
      nodes: [
        { id: 'news', kind: 'news', label: 'Repo rate cut announced' },
        { id: 'mech:repo_rate_down', kind: 'mechanism', label: 'Repo Rate ↓' },
        { id: 'sector:banking', kind: 'sector', label: 'banking' },
        { id: 'company:1', kind: 'company', company_id: 1, ticker: 'HDFCBANK.NS', label: 'HDFC Bank', name: 'HDFC Bank', direction: 'bullish', confidence_score: 80, impact_level: 'direct' },
      ],
      edges: [
        { from: 'news', to: 'mech:repo_rate_down', relation: 'correlation', direction: 'bullish', note: 'n0', source: 'llm_only' },
        { from: 'mech:repo_rate_down', to: 'sector:banking', relation: 'credit_cost', direction: 'bullish', note: 'n1', source: 'rulebook_verified' },
        { from: 'sector:banking', to: 'company:1', relation: 'demand', direction: 'bullish', note: 'n2', source: 'llm_only' },
      ],
      gaps: [{ sector: 'consumer_durables', impact_level: 'indirect_l1', reason: 'resolution failed after retries' }],
    },
  }));
  renderPage('1');

  expect(await screen.findByText('Multi-Level Impact Tree')).toBeInTheDocument();
  expect(screen.getByText('Ripple Effect Graph')).toBeInTheDocument();
  expect(screen.getByText('Supply Chain Graph')).toBeInTheDocument();
  expect(screen.getByText('Cascade Levels')).toBeInTheDocument();
  expect(screen.getByText('Confidence Tree')).toBeInTheDocument();
  expect(screen.getByText('Positive / Negative Split')).toBeInTheDocument();
  expect(screen.getByText('Timeline Tree')).toBeInTheDocument();
  expect(screen.getByText('Sector Tree')).toBeInTheDocument();
  expect(screen.getByText('Economic Chain')).toBeInTheDocument();
  expect(screen.getByText('Knowledge Graph')).toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `frontend/`): `npx vitest run src/pages/AlertChartsPage.test.tsx`
Expected: FAIL (only 6 charts render today).

- [ ] **Step 3: Wire the 4 new charts into `AlertChartsPage.tsx`**

Add to the import block (currently ending `import SectorTree from '../features/visualize/charts/SectorTree';`):

```tsx
import RippleGraph from '../features/visualize/charts/RippleGraph';
import SupplyChainGraph from '../features/visualize/charts/SupplyChainGraph';
import EconomicChain from '../features/visualize/charts/EconomicChain';
import KnowledgeGraph from '../features/visualize/charts/KnowledgeGraph';
import { buildGraph } from '../features/visualize/graph/model';
```

Right after the `if (!alert) { ... }` guard and before the `return (`, add:

```tsx
  const graph = buildGraph(alert);
```

Change the chart-rendering block (currently mounting `ImpactTree` then `LevelTree`/`ConfidenceTree`/`SplitTree`/`TimelineTree`/`SectorTree`) to insert the 4 new charts at their correct numeric positions:

```tsx
        <ImpactTree companies={alert.companies} article={alert.article} alertCreatedAt={alert.created_at} eventType={alert.event_type} />
        <div className="border-t border-hairline">
          <RippleGraph graph={graph} companies={alert.companies} eventType={alert.event_type} />
        </div>
        <div className="border-t border-hairline">
          <SupplyChainGraph graph={graph} companies={alert.companies} eventType={alert.event_type} />
        </div>
        <div className="border-t border-hairline">
          <LevelTree companies={alert.companies} eventType={alert.event_type} />
        </div>
        <div className="border-t border-hairline">
          <ConfidenceTree companies={alert.companies} eventType={alert.event_type} />
        </div>
        <div className="border-t border-hairline">
          <SplitTree companies={alert.companies} eventType={alert.event_type} />
        </div>
        <div className="border-t border-hairline">
          <TimelineTree companies={alert.companies} eventType={alert.event_type} />
        </div>
        <div className="border-t border-hairline">
          <SectorTree companies={alert.companies} eventType={alert.event_type} />
        </div>
        <div className="border-t border-hairline">
          <EconomicChain graph={graph} companies={alert.companies} />
        </div>
        <div className="border-t border-hairline">
          <KnowledgeGraph graph={graph} companies={alert.companies} eventType={alert.event_type} />
        </div>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/pages/AlertChartsPage.test.tsx`
Expected: PASS, including the new all-ten-charts test and every pre-existing test.

- [ ] **Step 5: Run the full frontend suite + typecheck + build**

Run (from `frontend/`): `npx vitest run`, `npx tsc --noEmit`, `npm run build`
Expected: all three PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/AlertChartsPage.tsx frontend/src/pages/AlertChartsPage.test.tsx
git commit -m "feat: mount all four graph charts, all 10 impact charts now live"
```

---

## Explicitly out of scope (this plan)

Live-animated (continuously ticking) force simulation for Knowledge Graph — a one-shot settle is used instead, for reliability without browser verification (see Global Constraints). Drag-to-reposition persistence (React Flow supports dragging nodes by default; this plan doesn't persist a dragged position anywhere — every reload resets to the computed layout, which is correct/expected). Any chart-level dark/light theme-specific styling beyond what `GraphNodeChip`/`ChartCardShell`/existing CSS vars already provide for free. Mobile/touch-specific pan-zoom tuning for the two React Flow charts.

## Definition of done (this plan only)

1. All 10 charts from the reference image render for a repo-rate-cut alert fixture, numbered 1-10 with no gaps, in ascending DOM order.
2. Every company node across all 10 charts is clickable and opens the same `ReasoningPanel` drawer; mechanism/sector/news nodes are never clickable.
3. Held companies show the portfolio ring in all 10 charts (inherited automatically via `GraphNodeChip`/`CompanyCard`/`CompanyRow`).
4. Pruned edges are visible-but-dimmed by default in Ripple Effect Graph, with a working show/hide toggle; Knowledge Graph shows them dimmed with no toggle (per its "the full picture" framing — no toggle specified for this chart in the source doc).
5. `graph.gaps` is not yet surfaced as UI text anywhere in this plan (no task above renders a gap note) — this is a real gap relative to the source doc's "show `graph.gaps` as a small honest muted note under any chart where a ripple path was unresolved" instruction. Flagged explicitly: NOT implemented in this plan, a legitimate follow-up, not an oversight — scoping decision made to keep this already-large phase's tasks bounded. If needed, a 6th task (or its own small follow-up plan) adds a `GapsNote` component reading `graph.gaps` and mounts it once near the top of the graph-chart section.
6. Full frontend test suite green, `tsc --noEmit` clean, `npm run build` succeeds.
7. **NOT done by this plan, requires human follow-up**: manual browser verification (one repo-rate alert through all 10 charts, dark + light theme, pan/zoom feel, pruned-edge toggle, real drag interaction) — no browser access in this environment.
