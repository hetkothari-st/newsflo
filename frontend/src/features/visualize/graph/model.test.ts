import { describe, expect, it } from 'vitest';
import { buildGraph, chainTree, longestChainPath, mechanismBackbone, ringsByImpactLevel } from './model';
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

describe('chainTree', () => {
  const baseNodes = [
    { id: 'news', kind: 'news' as const, label: 'x' },
    { id: 'sector:banking', kind: 'sector' as const, label: 'banking' },
    { id: 'company:1', kind: 'company' as const, label: 'C1', company_id: 1, ticker: 'C1', impact_level: 'direct' },
  ];
  const baseEdges = [
    { from: 'news', to: 'sector:banking', relation: 'correlation', direction: 'bullish', note: 'n', source: 'llm_only' },
    { from: 'sector:banking', to: 'company:1', relation: 'demand', direction: 'bullish', note: 'n', source: 'llm_only' },
  ];

  it('picks the company node whose own impact_level is "direct"', () => {
    const graph: ImpactGraph = { nodes: baseNodes, edges: baseEdges, gaps: [] };
    const result = chainTree(graph);
    expect(result.direct?.id).toBe('company:1');
  });

  it('renders both upstream and downstream empty when no supplier/customer edges exist', () => {
    const graph: ImpactGraph = { nodes: baseNodes, edges: baseEdges, gaps: [] };
    const result = chainTree(graph);
    expect(result.upstream).toEqual([]);
    expect(result.downstream).toEqual([]);
  });

  it('populates upstream from real supplier edges into the direct company', () => {
    const graph: ImpactGraph = {
      nodes: [...baseNodes, { id: 'company:2', kind: 'company', label: 'Supplier Co', company_id: 2, ticker: 'SUP' }],
      edges: [...baseEdges, { from: 'company:2', to: 'company:1', relation: 'supplier', direction: 'bullish', note: 'n', source: 'llm_only' }],
      gaps: [],
    };
    const result = chainTree(graph);
    expect(result.upstream.map((n) => n.id)).toEqual(['company:2']);
    expect(result.downstream).toEqual([]);
  });

  it('populates downstream from real customer edges out of the direct company, without shifting which company is "direct"', () => {
    const graph: ImpactGraph = {
      nodes: [...baseNodes, { id: 'company:2', kind: 'company', label: 'Customer Co', company_id: 2, ticker: 'CUST' }],
      edges: [...baseEdges, { from: 'company:1', to: 'company:2', relation: 'customer', direction: 'bullish', note: 'n', source: 'llm_only' }],
      gaps: [],
    };
    const result = chainTree(graph);
    expect(result.direct?.id).toBe('company:1');
    expect(result.downstream.map((n) => n.id)).toEqual(['company:2']);
    expect(result.upstream).toEqual([]);
  });

  it('returns a null direct and empty columns when the graph has no company node', () => {
    const graph: ImpactGraph = { nodes: [{ id: 'news', kind: 'news', label: 'x' }], edges: [], gaps: [] };
    const result = chainTree(graph);
    expect(result).toEqual({ direct: null, upstream: [], downstream: [] });
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
