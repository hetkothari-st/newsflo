import { describe, expect, it } from 'vitest';
import { forceDirectedPositions, ripplePositions } from './layout';
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

  // Regression: real data (the Lockheed Martin alert, one company per
  // impact level) rendered as a perfectly flat horizontal line -- every
  // node's y-coordinate was 0. placeRing's angle formula ignored ringIndex
  // entirely, so every single-node ring (count === 1) landed at angle 0.
  it('does not collapse a sparse graph (one company per level) into a flat, collinear row', () => {
    const sparse: ImpactGraph = {
      nodes: [
        { id: 'news', kind: 'news', label: 'Lockheed to make cheaper Patriot interceptors' },
        { id: 'sector:defense', kind: 'sector', label: 'defense' },
        { id: 'company:1', kind: 'company', company_id: 1, ticker: 'LMT', label: 'Lockheed Martin', name: 'Lockheed Martin', direction: 'bullish', confidence_score: 82, impact_level: 'direct' },
        { id: 'company:2', kind: 'company', company_id: 2, ticker: 'RTX', label: 'RTX Corporation', name: 'RTX Corporation', direction: 'bearish', confidence_score: 61, impact_level: 'indirect_l1' },
        { id: 'company:3', kind: 'company', company_id: 3, ticker: 'HINDALCO.NS', label: 'Hindalco Industries', name: 'Hindalco Industries', direction: 'bearish', confidence_score: 45, impact_level: 'indirect_l2' },
      ],
      edges: [],
      gaps: [],
    };

    const positions = ripplePositions(sparse);
    const nonNewsIds = ['sector:defense', 'company:1', 'company:2', 'company:3'];

    // Not every node landed on y=0 (the flat-row bug's signature).
    expect(nonNewsIds.some((id) => positions[id].y !== 0)).toBe(true);

    // No two nodes share the exact same (x, y) -- distinct rings, distinct
    // radii, and now distinct angles too.
    const seen = new Set<string>();
    for (const id of [...nonNewsIds, 'news']) {
      const key = `${positions[id].x},${positions[id].y}`;
      expect(seen.has(key)).toBe(false);
      seen.add(key);
    }
  });
});

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
