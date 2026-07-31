import { describe, expect, it } from 'vitest';
import { TREE, layoutTree, type TreeLevelSpec, type TreeNodePos } from './treeLayout';

function level(key: string, ids: number[]): TreeLevelSpec {
  return { key, label: key.toUpperCase(), sub: 'sub', companyIds: ids };
}

function overlaps(a: TreeNodePos, b: TreeNodePos): boolean {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

describe('layoutTree geometry (Doc-1 §3.2)', () => {
  it('places 3 nodes per level from startX 12 to endX 368, inside W=380', () => {
    const { levels } = layoutTree([level('direct', [1, 2, 3])]);
    const nodes = levels[0].nodes;
    expect(nodes[0].x).toBe(12);
    expect(nodes[2].x + nodes[2].w).toBe(368);
    for (const n of nodes) {
      expect(n.x).toBeGreaterThanOrEqual(0);
      expect(n.x + n.w).toBeLessThanOrEqual(TREE.W);
    }
  });

  it('keeps exactly GAPX between siblings and never overlaps', () => {
    const { levels } = layoutTree([level('direct', [1, 2, 3])]);
    const [a, b, c] = levels[0].nodes;
    expect(b.x - (a.x + a.w)).toBe(TREE.GAPX);
    expect(c.x - (b.x + b.w)).toBe(TREE.GAPX);
    expect(overlaps(a, b)).toBe(false);
    expect(overlaps(b, c)).toBe(false);
  });

  it('centers a single-node level', () => {
    const { levels, W } = layoutTree([level('direct', [7])]);
    const node = levels[0].nodes[0];
    expect(node.x + node.w / 2).toBe(W / 2);
  });

  it('wraps a level with more nodes than fit one row, without overlap', () => {
    const ids = [1, 2, 3, 4, 5, 6, 7];
    const { levels } = layoutTree([level('direct', ids)]);
    const lvl = levels[0];
    expect(lvl.rows.length).toBe(3); // 3 + 3 + 1 at NW=112
    expect(lvl.nodes.length).toBe(ids.length);
    for (const n of lvl.nodes) {
      expect(n.x).toBeGreaterThanOrEqual(0);
      expect(n.x + n.w).toBeLessThanOrEqual(TREE.W);
    }
    for (let i = 0; i < lvl.nodes.length; i++) {
      for (let j = i + 1; j < lvl.nodes.length; j++) {
        expect(overlaps(lvl.nodes[i], lvl.nodes[j])).toBe(false);
      }
    }
    // The lone last-row node is centered.
    const last = lvl.rows[2][0];
    expect(last.x + last.w / 2).toBe(TREE.W / 2);
  });

  it('accumulates height top-down: sparse trees are shorter than full ones', () => {
    const sparse = layoutTree([level('a', [1]), level('b', [2]), level('c', [3])]);
    const full = layoutTree([level('a', [1, 2, 3]), level('b', [4, 5, 6, 7]), level('c', [8, 9])]);
    expect(sparse.H).toBeLessThan(full.H);
    const expectedSparseH =
      TREE.newsH + 3 * (TREE.levelGap + TREE.bandH + TREE.NH) + TREE.BOTTOM_PAD;
    expect(sparse.H).toBe(expectedSparseH);
  });

  it('with no levels renders just the news root and no edges', () => {
    const { edges, H, news } = layoutTree([]);
    expect(edges).toHaveLength(0);
    expect(H).toBe(TREE.newsH + TREE.BOTTOM_PAD);
    expect(news.x + news.w / 2).toBe(TREE.W / 2);
  });
});

describe('layoutTree edges (Doc-1 §3.3)', () => {
  const centerX = TREE.W / 2;

  it('draws the news trunk at centerX down to the first band', () => {
    const { edges, news, levels } = layoutTree([level('direct', [1, 2])]);
    expect(edges[0]).toEqual({ x1: centerX, y1: news.y + news.h, x2: centerX, y2: levels[0].labelY });
  });

  it('draws a bus only for multi-node rows, plus one drop per node', () => {
    const multi = layoutTree([level('direct', [1, 2, 3])]);
    const single = layoutTree([level('direct', [1])]);
    const horizontal = (es: typeof multi.edges) => es.filter((e) => e.y1 === e.y2);
    expect(horizontal(multi.edges)).toHaveLength(1);
    expect(horizontal(single.edges)).toHaveLength(0);

    const busY = multi.levels[0].nodes[0].y - TREE.BUS_RISE;
    const drops = multi.edges.filter((e) => e.y1 === busY && e.y2 === multi.levels[0].nodes[0].y && e.x1 === e.x2);
    expect(drops).toHaveLength(3);
    // Each drop lands on its node's top-center.
    const dropXs = drops.map((d) => d.x1).sort((a, b) => a - b);
    const centers = multi.levels[0].nodes.map((n) => n.x + n.w / 2).sort((a, b) => a - b);
    expect(dropXs).toEqual(centers);
  });

  it('connects each level bottom to the next band at centerX', () => {
    const { edges, levels } = layoutTree([level('a', [1]), level('b', [2])]);
    const trunk = edges.find((e) => e.y1 === levels[0].bottomY && e.y2 === levels[1].labelY);
    expect(trunk).toBeDefined();
    expect(trunk!.x1).toBe(centerX);
    expect(trunk!.x2).toBe(centerX);
  });

  it('keeps every edge orthogonal (vertical or horizontal only)', () => {
    const { edges } = layoutTree([level('a', [1, 2, 3]), level('b', [4, 5, 6, 7]), level('c', [8])]);
    for (const e of edges) {
      expect(e.x1 === e.x2 || e.y1 === e.y2).toBe(true);
    }
  });
});
