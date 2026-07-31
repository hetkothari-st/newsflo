import { useMemo, useState } from 'react';
import type { AlertCompany, ImpactGraph } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { EDGE_RELATIONS, relationColor } from '../colors';
import { useCompanySelection } from '../charts/useCompanySelection';
import DeckChartFrame from './DeckChartFrame';
import DeckGraphSvg, { type PositionedNode } from './DeckGraphSvg';
import { EmptyGraphNote, GapsNote, PrunedToggle } from './DeckGraphShared';
import { deckForcePositions } from './forcePositions';

// Chart 10 -- Knowledge Graph. Whole payload, force-directed (deck-local
// layout with a centering pull so sparse graphs stay compact), rendered as
// one static fitted SVG -- every node visible at once, same as DeckRipple.
// Edge color by relation, node size by confidence_score, portfolio ring
// via CompanyNode's own treatment.
function sizeFor(confidenceScore: number | undefined): number {
  return 104 + (confidenceScore ?? 50) * 0.5;
}

export default function DeckKnowledge({
  graph,
  companies,
  eventType,
  displayNumber = 10,
}: {
  graph: ImpactGraph;
  companies: AlertCompany[];
  eventType?: string | null;
  displayNumber?: number;
}) {
  const { toggle, selected, selectedId } = useCompanySelection(companies);
  const [showPruned, setShowPruned] = useState(true);

  const layout = useMemo(() => {
    const positions = deckForcePositions(graph);
    const positioned: PositionedNode[] = graph.nodes.map((node) => {
      const { x: cx, y: cy } = positions[node.id] ?? { x: 0, y: 0 };
      const w = node.kind === 'company' ? sizeFor(node.confidence_score) : node.kind === 'news' ? 148 : 110;
      const h = node.kind === 'company' ? 66 : node.kind === 'news' ? 56 : 44;
      return { node, cx, cy, x: cx - w / 2, y: cy - h / 2, w, h };
    });
    const PAD = 16;
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const p of positioned) {
      minX = Math.min(minX, p.x);
      minY = Math.min(minY, p.y);
      maxX = Math.max(maxX, p.x + p.w);
      maxY = Math.max(maxY, p.y + p.h);
    }
    if (positioned.length === 0) {
      minX = minY = 0;
      maxX = maxY = 1;
    }
    return {
      positioned,
      minX: minX - PAD,
      minY: minY - PAD,
      width: maxX - minX + PAD * 2,
      height: maxY - minY + PAD * 2,
    };
  }, [graph]);

  const visibleEdges = showPruned ? graph.edges : graph.edges.filter((e) => e.source !== 'rulebook_pruned');
  const presentRelations = new Set(graph.edges.map((e) => e.relation));
  const legend = EDGE_RELATIONS.filter((r) => presentRelations.has(r)).map((r) => ({
    label: r,
    color: relationColor(r),
  }));

  return (
    <DeckChartFrame
      number={displayNumber}
      title="Knowledge Graph"
      description="Every node and edge this alert resolved, laid out by connection strength; node size tracks confidence."
      legend={legend}
    >
      {graph.nodes.length <= 1 ? (
        <EmptyGraphNote text="No impact graph resolved for this alert yet." />
      ) : (
        <>
          <PrunedToggle graph={graph} showPruned={showPruned} onToggle={() => setShowPruned((v) => !v)} />
          <DeckGraphSvg
            positioned={layout.positioned}
            edges={visibleEdges}
            viewBox={layout}
            edgeColor={(edge) => relationColor(edge.relation)}
            selectedId={selectedId}
            onToggle={toggle}
            label="Knowledge graph"
          />
          <GapsNote gaps={graph.gaps} />
          {selected && <ReasoningPanel company={selected} eventType={eventType} />}
        </>
      )}
    </DeckChartFrame>
  );
}
