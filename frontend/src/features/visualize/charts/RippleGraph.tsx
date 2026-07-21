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
