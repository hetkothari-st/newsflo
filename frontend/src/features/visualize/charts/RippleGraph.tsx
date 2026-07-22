import { useCallback, useMemo, useState } from 'react';
import {
  Background, Controls, Handle, Position, ReactFlow,
  type Edge, type Node, type NodeProps, type ReactFlowInstance,
} from '@xyflow/react';
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
      {/* nodrag/nopan: React Flow's documented convention for an interactive
          element inside a custom node (see @xyflow/react's own NodeToolbar/
          Handle usage docs) -- without it, tapping the chip's button also
          starts the node's own d3-drag pan/drag gesture, which is both a
          spurious UX side effect in a browser and, under jsdom/user-event
          (event.view unset on synthetic MouseEvents), throws inside
          d3-drag's nodrag() helper. */}
      <div className="nodrag nopan">
        <GraphNodeChip node={data.node} onClick={data.onClick} selected={data.selected} />
      </div>
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

  // The declarative `fitView` prop computes its transform against the
  // container's size at React Flow's own mount instant -- on a long page
  // with several charts above this one (fonts/images/other cards still
  // settling), that size isn't always final yet, producing a transform
  // that places every node outside the visible, overflow-hidden pane
  // (confirmed live: nodes existed in the DOM with correct content, just
  // positioned off-screen). Deferring the real fitView call to onInit,
  // inside a requestAnimationFrame, runs it after the browser's layout/
  // paint has genuinely settled instead.
  const onInit = useCallback((instance: ReactFlowInstance<Node<FlowNodeData>, Edge>) => {
    requestAnimationFrame(() => instance.fitView({ padding: 0.2 }));
  }, []);

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
        {/* h-[280px] sm:h-[420px]: fixed 420px on mobile left a huge dead
            zone above/below a ripple layout that's wide, not tall -- most
            of the pane's height went unused. minZoom raised 0.3->0.55:
            with 5+ nodes at a fixed 160px chip width, fitView on a ~340px-
            wide phone screen was clamping toward 0.3, shrinking node text
            to a few px (confirmed live: illegible). 0.55 keeps text
            readable; wide graphs pan/scroll horizontally instead of
            shrinking to fit, same tradeoff any node-link diagram makes. */}
        <div className="h-[280px] w-full overflow-hidden rounded-lg border border-hairline sm:h-[420px]">
          <ReactFlow nodes={flowNodes} edges={flowEdges} nodeTypes={nodeTypes} onInit={onInit} minZoom={0.55} maxZoom={1.5}>
            <Background />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
        {selected && <ReasoningPanel company={selected} eventType={eventType} />}
      </div>
    </ChartCardShell>
  );
}
