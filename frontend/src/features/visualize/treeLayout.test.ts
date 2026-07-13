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
