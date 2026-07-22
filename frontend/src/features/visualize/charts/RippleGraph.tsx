import { useCallback, useMemo, useState } from 'react';
import {
  Background, Controls, Handle, Position, ReactFlow,
  type Edge, type EdgeMouseHandler, type Node, type NodeProps, type ReactFlowInstance,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import type { AlertArticle, AlertCompany, GraphNode, ImpactGraph } from '../../../lib/api';
import { useTheme } from '../../../lib/theme';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { ripplePositions } from '../graph/layout';
import ChartCardShell from './ChartCardShell';
import GraphFlowNode from './primitives/GraphFlowNode';
import NewsHeaderBlock from './primitives/NewsHeaderBlock';
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
        <GraphFlowNode node={data.node} onClick={data.onClick} selected={data.selected} />
      </div>
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
    </>
  );
}

const nodeTypes = { graphNode: FlowNode };

export default function RippleGraph({
  graph,
  companies,
  article,
  alertCreatedAt,
  eventType,
}: {
  graph: ImpactGraph;
  companies: AlertCompany[];
  article: AlertArticle;
  alertCreatedAt: string;
  eventType?: string | null;
}) {
  const { toggle, selected, selectedId } = useCompanySelection(companies);
  const { theme } = useTheme();
  const [showPruned, setShowPruned] = useState(false);
  // Relation labels only on hover (reference: docs/charts-reference.png) --
  // a permanent label on every edge is what made the reference call the
  // old build "spaghetti"; only the hovered edge's label shows.
  const [hoveredEdgeId, setHoveredEdgeId] = useState<string | null>(null);

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

  const flowEdges: Edge[] = visibleEdges.map((edge, i) => {
    const id = `${edge.from}-${edge.to}-${i}`;
    return {
      id,
      source: edge.from,
      target: edge.to,
      // Straight, not curved -- a radial ripple layout reads as spokes from
      // a center, which a bezier curve (React Flow's default) distorts into
      // the "spaghetti" the reference calls out.
      type: 'straight',
      label: hoveredEdgeId === id ? edge.relation : undefined,
      style: {
        stroke: edge.direction === 'bearish' ? 'rgb(var(--color-bearish))' : 'rgb(var(--color-bullish))',
        strokeDasharray: edge.source === 'rulebook_pruned' ? '4 4' : undefined,
        opacity: edge.source === 'rulebook_pruned' ? 0.4 : 1,
      },
    };
  });

  const onEdgeMouseEnter = useCallback<EdgeMouseHandler>((_event, edge) => setHoveredEdgeId(edge.id), []);
  const onEdgeMouseLeave = useCallback<EdgeMouseHandler>(() => setHoveredEdgeId(null), []);

  // `fitView` computes a transform that fits the WHOLE graph's bounding box
  // into the pane -- but ripplePositions() can lay a multi-ring graph out
  // very wide (RING_SPACING=240 per ring, up to 4 rings = ~1920px across),
  // while minZoom=0.55 (kept high so node text stays readable -- see below)
  // forbids fitView from zooming out far enough to actually fit that width.
  // fitView then clamps to minZoom and centers on the bounding box's
  // geometric center regardless -- on a narrow mobile pane, that centered
  // slice can miss every single node (confirmed live: a fresh mobile load
  // showed a completely empty canvas, just background dots, even though 7
  // nodes existed in the DOM with correct positions). This was a genuine
  // graph-shape bug, not the container-measurement-timing bug the original
  // onInit+rAF fix (and this comment, before this rewrite) targeted --
  // re-running the same fitView later via ResizeObserver reproduced the
  // identical empty crop, proving timing was never the cause here.
  //
  // setCenter sidesteps this entirely: it centers ONE known point (the news
  // node, always at the origin per ripplePositions) at a fixed, always-
  // readable zoom, instead of trying to fit an unbounded, possibly very
  // wide bounding box. The news node and its innermost ring are always
  // visible; outer rings are reached by panning, same as any node-link
  // diagram wider than its viewport.
  const onInit = useCallback((instance: ReactFlowInstance<Node<FlowNodeData>, Edge>) => {
    requestAnimationFrame(() => instance.setCenter(0, 0, { zoom: 0.7, duration: 0 }));
  }, []);

  if (graph.nodes.length <= 1) return null;

  return (
    <ChartCardShell
      number={2}
      title="Ripple Effect Graph"
      description="News radiating outward through mechanisms, sectors, and companies"
      accentColor="#4A90D9"
    >
      <div className="flex flex-col items-center gap-4">
        <NewsHeaderBlock article={article} alertCreatedAt={alertCreatedAt} />
        {hasPruned && (
          <button
            type="button"
            onClick={() => setShowPruned((v) => !v)}
            className="self-start rounded-md border border-hairline px-2 py-1 font-data text-[10px] uppercase tracking-widest text-muted hover:text-ink"
          >
            {showPruned ? 'Hide pruned edges' : 'Show pruned edges'}
          </button>
        )}
        <div className="h-[320px] w-full overflow-hidden rounded-lg border border-hairline sm:h-[480px]">
          {/* colorMode: @xyflow/react defaults to "light" and stamps that
              literal string as a class on its root div -- this app's own
              theming stylesheet defines `.light { --color-ink: ...; }` as a
              plain (unscoped) class selector, so React Flow's own default
              class silently collided with it and reset every themed color
              inside the canvas to the LIGHT palette even while the rest of
              the page was in dark mode (text-ink resolved near-black on a
              near-black canvas -- confirmed nearly invisible live). Passing
              the app's real theme keeps the two "light" class users in
              sync instead of colliding. */}
          <ReactFlow
            nodes={flowNodes}
            edges={flowEdges}
            nodeTypes={nodeTypes}
            onInit={onInit}
            onEdgeMouseEnter={onEdgeMouseEnter}
            onEdgeMouseLeave={onEdgeMouseLeave}
            colorMode={theme}
            minZoom={0.55}
            maxZoom={1.5}
          >
            <Background />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
        {selected && <ReasoningPanel company={selected} eventType={eventType} />}
      </div>
    </ChartCardShell>
  );
}
