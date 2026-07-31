import { describe, expect, it } from 'vitest';
import type { GraphNode, ImpactGraph } from '../../../lib/api';
import { radialLayout } from './radialLayout';

function companyNode(id: number, level: string): GraphNode {
  return {
    id: `company:${id}`, kind: 'company', company_id: id, ticker: `T${id}`,
    label: `Co ${id}`, name: `Co ${id}`, direction: 'bearish', impact_level: level,
  };
}

function graph(nodes: GraphNode[]): ImpactGraph {
  return { nodes: [{ id: 'news', kind: 'news', label: 'n' }, ...nodes], edges: [], gaps: [] };
}

describe('radialLayout (chart 2)', () => {
  it('places sparse one-per-ring alerts on real rings, never one straight line (Doc-2 §4)', () => {
    const layout = radialLayout(
      graph([companyNode(1, 'direct'), companyNode(2, 'indirect_l1'), companyNode(3, 'indirect_l2')]),
    );
    const companies = layout.nodes.filter((n) => n.node.kind === 'company');
    // Not collinear through the origin: y-coordinates must not all be 0,
    // and no two nodes may share a position.
    expect(companies.some((n) => Math.abs(n.cy) > 1)).toBe(true);
    const keys = new Set(companies.map((n) => `${Math.round(n.cx)},${Math.round(n.cy)}`));
    expect(keys.size).toBe(companies.length);
  });

  it('keeps every node box inside the fitted viewBox', () => {
    const layout = radialLayout(
      graph([
        companyNode(1, 'direct'), companyNode(2, 'direct'), companyNode(3, 'direct'),
        companyNode(4, 'indirect_l1'), companyNode(5, 'indirect_l1'),
        { id: 'sector:banking', kind: 'sector', label: 'banking' },
      ]),
    );
    for (const n of layout.nodes) {
      expect(n.x).toBeGreaterThanOrEqual(layout.minX);
      expect(n.y).toBeGreaterThanOrEqual(layout.minY);
      expect(n.x + n.w).toBeLessThanOrEqual(layout.minX + layout.width);
      expect(n.y + n.h).toBeLessThanOrEqual(layout.minY + layout.height);
    }
  });

  it('never overlaps two boxes on the same ring, growing the radius when crowded', () => {
    const many = Array.from({ length: 10 }, (_, i) => companyNode(i + 1, 'direct'));
    const layout = radialLayout(graph(many));
    const companies = layout.nodes.filter((n) => n.node.kind === 'company');
    for (let i = 0; i < companies.length; i++) {
      for (let j = i + 1; j < companies.length; j++) {
        const a = companies[i];
        const b = companies[j];
        const overlap = a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
        expect(overlap).toBe(false);
      }
    }
  });

  it('draws a guide radius per ring', () => {
    const layout = radialLayout(graph([companyNode(1, 'direct'), companyNode(2, 'indirect_l1')]));
    expect(layout.ringRadii).toHaveLength(2);
    expect(layout.ringRadii[1]).toBeGreaterThan(layout.ringRadii[0]);
  });
});
