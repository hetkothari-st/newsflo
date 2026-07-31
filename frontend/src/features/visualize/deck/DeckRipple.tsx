import { useCallback, useMemo, useState } from 'react';
import {
  Background, Controls, ReactFlow,
  type Edge, type EdgeMouseHandler, type Node, type ReactFlowInstance,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import type { AlertCompany, ImpactGraph } from '../../../lib/api';
import { useTheme } from '../../../lib/theme';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { ripplePositions } from '../graph/layout';
import { useCompanySelection } from '../charts/useCompanySelection';
import DeckChartFrame from './DeckChartFrame';
import { EmptyGraphNote, GapsNote, PrunedToggle, deckNodeTypes, type FlowNodeData } from './DeckGraphShared';

// Chart 2 -- Ripple Effect (Doc-2 §6). News at the center, concentric rings
// by impact_level (direct innermost). Uses graph/layout.ts's ripple
// placement, which staggers each ring's angle so sparse alerts (one company
// per ring -- the common case) render as real rings, never a flat collinear
// row (the §4 bug, fixed + regression-tested in layout.test.ts).
export default function DeckRipple({
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
  const [showPruned, setShowPruned] = useState(true);
  // Relation label only on the hovered edge -- a permanent label on every
  // edge is what turned earlier builds into spaghetti.
  const [hoveredEdgeId, setHoveredEdgeId] = useState<string | null>(null);

  const positions = useMemo(() => ripplePositions(graph), [graph]);
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
      // Straight spokes, not beziers -- a radial layout curves into mush.
      type: 'straight',
      label: hoveredEdgeId === id ? edge.relation : undefined,
      style: {
        stroke: edge.direction === 'bearish' ? 'rgb(var(--color-bearish))' : 'rgb(var(--color-bullish))',
        strokeDasharray: edge.source === 'rulebook_pruned' ? '4 4' : undefined,
        opacity: edge.source === 'rulebook_pruned' ? 0.35 : 1,
      },
    };
  });

  const onEdgeMouseEnter = useCallback<EdgeMouseHandler>((_event, edge) => setHoveredEdgeId(edge.id), []);
  const onEdgeMouseLeave = useCallback<EdgeMouseHandler>(() => setHoveredEdgeId(null), []);

  // setCenter, not fitView: fitView + a readable minZoom can crop every
  // node out of a narrow pane (confirmed live on the prior build). The
  // news node is always at (0,0); center there at a fixed readable zoom
  // and let panning reach the outer rings.
  const onInit = useCallback((instance: ReactFlowInstance<Node<FlowNodeData>, Edge>) => {
    requestAnimationFrame(() => instance.setCenter(0, 0, { zoom: 0.7, duration: 0 }));
  }, []);

  return (
    <DeckChartFrame
      number={2}
      title="Ripple Effect"
      description="News at the center, radiating outward ring by ring through the companies it touches."
      legend={[
        { label: 'Positive edge', color: 'rgb(var(--color-bullish))' },
        { label: 'Negative edge', color: 'rgb(var(--color-bearish))' },
      ]}
    >
      {graph.nodes.length <= 1 ? (
        <EmptyGraphNote text="No impact graph resolved for this alert yet." />
      ) : (
        <>
          <PrunedToggle graph={graph} showPruned={showPruned} onToggle={() => setShowPruned((v) => !v)} />
          <div className="deck-flowpane">
            {/* colorMode keeps React Flow's own "light" class in sync with
                the app theme -- they collide otherwise (live bug). */}
            <ReactFlow
              nodes={flowNodes}
              edges={flowEdges}
              nodeTypes={deckNodeTypes}
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
          <GapsNote gaps={graph.gaps} />
          {selected && <ReasoningPanel company={selected} eventType={eventType} />}
        </>
      )}
    </DeckChartFrame>
  );
}
