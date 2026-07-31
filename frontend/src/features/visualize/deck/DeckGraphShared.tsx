import { Handle, Position, type Node, type NodeProps } from '@xyflow/react';
import type { GraphGap, GraphNode, ImpactGraph } from '../../../lib/api';
import GraphFlowNode from '../charts/primitives/GraphFlowNode';
import { sectorLabel } from '../transforms';
import './deck.css';

// Shared pieces for the deck's node-link charts (2 Ripple, 10 Knowledge)
// and the honesty affordances every graph view must carry (Doc-2 §6):
// pruned edges shown dimmed with a toggle, cascade gaps as a quiet note.

export interface FlowNodeData {
  node: GraphNode;
  onClick?: () => void;
  selected: boolean;
  size?: number;
  [key: string]: unknown;
}

export function FlowNode({ data }: NodeProps<Node<FlowNodeData>>) {
  return (
    <>
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      {/* nodrag/nopan: React Flow's convention for interactive elements
          inside a custom node -- without it a tap also starts the d3-drag
          gesture (and throws under jsdom/user-event). */}
      <div className="nodrag nopan">
        <GraphFlowNode node={data.node} onClick={data.onClick} selected={data.selected} width={data.size} />
      </div>
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
    </>
  );
}

export const deckNodeTypes = { graphNode: FlowNode };

// Pruned edges are stored and SHOWN (dimmed) by default -- the audit trail
// is what makes the graph trustworthy -- with a toggle to hide them.
export function PrunedToggle({
  graph,
  showPruned,
  onToggle,
}: {
  graph: ImpactGraph;
  showPruned: boolean;
  onToggle: () => void;
}) {
  const prunedCount = graph.edges.filter((e) => e.source === 'rulebook_pruned').length;
  if (prunedCount === 0) return null;
  return (
    <button type="button" onClick={onToggle} className="deck-prunedtoggle">
      {showPruned ? `Hide ${prunedCount} pruned` : `Show ${prunedCount} pruned`}
    </button>
  );
}

// Cascade gaps (sectors the pipeline flagged but could not resolve into
// companies) -- shown as a quiet honest note, never hidden (Doc-2 §6).
export function GapsNote({ gaps }: { gaps: GraphGap[] }) {
  if (gaps.length === 0) return null;
  return (
    <p className="deck-gapsnote">
      Unresolved: {gaps.map((g) => `${sectorLabel(g.sector)} (${g.reason})`).join(' · ')}
    </p>
  );
}

// Doc-2 §7.8: a graph chart may never be silently blank.
export function EmptyGraphNote({ text }: { text: string }) {
  return <p className="deck-emptystate">{text}</p>;
}
