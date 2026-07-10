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
