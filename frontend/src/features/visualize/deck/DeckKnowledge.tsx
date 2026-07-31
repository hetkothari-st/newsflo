import { useCallback, useMemo, useState } from 'react';
import {
  Background, Controls, ReactFlow,
  type Edge, type Node, type ReactFlowInstance,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import type { AlertCompany, ImpactGraph } from '../../../lib/api';
import { useTheme } from '../../../lib/theme';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { EDGE_RELATIONS, relationColor } from '../colors';
import { deckForcePositions } from './forcePositions';
import { useCompanySelection } from '../charts/useCompanySelection';
import DeckChartFrame from './DeckChartFrame';
import { EmptyGraphNote, GapsNote, PrunedToggle, deckNodeTypes, type FlowNodeData } from './DeckGraphShared';

// Chart 10 -- Knowledge Graph (Doc-2 §6). The whole payload, force-directed:
// edge color by relation, node size by confidence_score, portfolio ring on
// holdings (CompanyNode's own treatment). Labels render through the shared
// primitives, which use --ink -- the dark-grey-on-black illegibility was a
// past bug this build must not reintroduce.
function sizeFor(confidenceScore: number | undefined): number {
  return 120 + (confidenceScore ?? 50) * 0.6;
}

export default function DeckKnowledge({
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

  const positions = useMemo(() => deckForcePositions(graph), [graph]);
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
            size: sizeFor(node.confidence_score),
          },
        };
      }),
    [graph.nodes, positions, selectedId, toggle],
  );

  const flowEdges: Edge[] = visibleEdges.map((edge, i) => ({
    id: `${edge.from}-${edge.to}-${i}`,
    source: edge.from,
    target: edge.to,
    type: 'straight',
    style: {
      stroke: relationColor(edge.relation),
      strokeDasharray: edge.source === 'rulebook_pruned' ? '4 4' : undefined,
      opacity: edge.source === 'rulebook_pruned' ? 0.35 : 1,
    },
  }));

  // fitView here, unlike DeckRipple's setCenter: a force-directed layout's
  // bounding box is bounded (forceCollide keeps it compact), so fitting it
  // is safe -- and centering (0,0) proved unreliable live (the simulation's
  // centroid drifts from the origin once collision pushes nodes around,
  // leaving the pane mostly empty). maxZoom 1 keeps node text full-size.
  const onInit = useCallback((instance: ReactFlowInstance<Node<FlowNodeData>, Edge>) => {
    requestAnimationFrame(() => instance.fitView({ padding: 0.1, maxZoom: 1, duration: 0 }));
  }, []);

  const presentRelations = new Set(graph.edges.map((e) => e.relation));
  const legend = EDGE_RELATIONS.filter((r) => presentRelations.has(r)).map((r) => ({
    label: r,
    color: relationColor(r),
  }));

  return (
    <DeckChartFrame
      number={10}
      title="Knowledge Graph"
      description="Every node and edge this alert resolved, laid out by connection strength; node size tracks confidence."
      legend={legend}
    >
      {graph.nodes.length <= 1 ? (
        <EmptyGraphNote text="No impact graph resolved for this alert yet." />
      ) : (
        <>
          <PrunedToggle graph={graph} showPruned={showPruned} onToggle={() => setShowPruned((v) => !v)} />
          <div className="deck-flowpane">
            <ReactFlow
              nodes={flowNodes}
              edges={flowEdges}
              nodeTypes={deckNodeTypes}
              onInit={onInit}
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
