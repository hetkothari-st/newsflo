import { useCallback, useMemo } from 'react';
import {
  Background, Controls, Handle, Position, ReactFlow,
  type Edge, type Node, type NodeProps, type ReactFlowInstance,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import type { AlertCompany, GraphNode, ImpactGraph } from '../../../lib/api';
import { useTheme } from '../../../lib/theme';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { EDGE_RELATIONS, relationColor } from '../colors';
import { forceDirectedPositions } from '../graph/layout';
import ChartCardShell from './ChartCardShell';
import GraphFlowNode from './primitives/GraphFlowNode';
import { useCompanySelection } from './useCompanySelection';

interface FlowNodeData {
  node: GraphNode;
  onClick?: () => void;
  selected: boolean;
  size: number;
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
          d3-drag's nodrag() helper. Same fix RippleGraph.tsx (Task 3)
          already needed for the identical GraphNodeChip-in-FlowNode shape. */}
      <div className="nodrag nopan">
        {/* width only affects company nodes (see GraphFlowNode) -- only
            company nodes carry a real confidence_score to size by. */}
        <GraphFlowNode node={data.node} onClick={data.onClick} selected={data.selected} width={data.size} />
      </div>
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
    </>
  );
}

const nodeTypes = { graphNode: FlowNode };

function sizeFor(confidenceScore: number | undefined): number {
  return 120 + (confidenceScore ?? 50) * 0.6;
}

export default function KnowledgeGraph({
  graph,
  companies,
  eventType,
}: {
  graph: ImpactGraph;
  companies: AlertCompany[];
  eventType?: string | null;
}) {
  const { toggle, selected, selectedId } = useCompanySelection(companies);
  const { theme } = useTheme();

  const positions = useMemo(() => forceDirectedPositions(graph), [graph]);

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
            size: sizeFor(node.confidence_score),
          },
        };
      }),
    [graph.nodes, positions, selectedId, toggle],
  );

  const presentRelations = new Set(graph.edges.map((e) => e.relation));
  const flowEdges: Edge[] = graph.edges.map((edge, i) => ({
    id: `${edge.from}-${edge.to}-${i}`,
    source: edge.from,
    target: edge.to,
    // Straight, not curved -- see RippleGraph.tsx's identical note.
    type: 'straight',
    style: {
      stroke: relationColor(edge.relation),
      strokeDasharray: edge.source === 'rulebook_pruned' ? '4 4' : undefined,
      opacity: edge.source === 'rulebook_pruned' ? 0.4 : 1,
    },
  }));

  // Same fitView-vs-minZoom empty-crop bug as RippleGraph.tsx (#2) -- see
  // its comment for the full story. forceDirectedPositions applies
  // forceCenter(0,0) to the whole simulation, so (0,0) is the real
  // centroid; centering there at a fixed, readable zoom is robust
  // regardless of how far the simulation spread the outer nodes.
  const onInit = useCallback((instance: ReactFlowInstance<Node<FlowNodeData>, Edge>) => {
    requestAnimationFrame(() => instance.setCenter(0, 0, { zoom: 0.7, duration: 0 }));
  }, []);

  if (graph.nodes.length <= 1) return null;

  const legend = EDGE_RELATIONS.filter((r) => presentRelations.has(r)).map((r) => ({
    label: r,
    color: relationColor(r),
  }));

  return (
    <ChartCardShell
      number={10}
      title="Knowledge Graph"
      description="The full picture -- every node and verified edge, laid out by real connection strength"
      legend={legend}
      accentColor="#557C30"
    >
      {/* Same mobile fix as RippleGraph.tsx (#2): responsive height instead
          of a fixed 480px dead zone, and minZoom raised so force-directed
          layout's spread doesn't shrink node text to illegible on a narrow
          screen. */}
      <div className="h-[320px] w-full overflow-hidden rounded-lg border border-hairline sm:h-[480px]">
        {/* colorMode: same theme-class collision fix as RippleGraph.tsx
            (#2) -- see its comment. */}
        <ReactFlow nodes={flowNodes} edges={flowEdges} nodeTypes={nodeTypes} onInit={onInit} colorMode={theme} minZoom={0.55} maxZoom={1.5}>
          <Background />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      {selected && (
        <div className="p-4">
          <ReasoningPanel company={selected} eventType={eventType} />
        </div>
      )}
    </ChartCardShell>
  );
}
