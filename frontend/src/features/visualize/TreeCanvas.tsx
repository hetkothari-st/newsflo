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
        nodesDraggable={false}
      >
        <Background color="#262626" gap={24} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
