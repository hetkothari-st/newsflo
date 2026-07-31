import { useMemo, useState } from 'react';
import type { AlertCompany, ImpactGraph } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { useCompanySelection } from '../charts/useCompanySelection';
import DeckChartFrame from './DeckChartFrame';
import DeckGraphSvg from './DeckGraphSvg';
import { EmptyGraphNote, GapsNote, PrunedToggle } from './DeckGraphShared';
import { radialLayout } from './radialLayout';

// Chart 2 -- Ripple Effect. A static, fully-visible radial SVG: news at
// the center, dashed guide circles making each impact ring legible, edges
// as straight direction-colored spokes. Replaces the React Flow pane,
// whose pan/zoom viewport kept opening on scattered/clipped nodes (the
// reported "always distorted" failure) -- a fitted viewBox cannot do that.
export default function DeckRipple({
  graph,
  companies,
  eventType,
  displayNumber = 2,
}: {
  graph: ImpactGraph;
  companies: AlertCompany[];
  eventType?: string | null;
  displayNumber?: number;
}) {
  const { toggle, selected, selectedId } = useCompanySelection(companies);
  const [showPruned, setShowPruned] = useState(true);

  const layout = useMemo(() => radialLayout(graph), [graph]);
  const visibleEdges = showPruned ? graph.edges : graph.edges.filter((e) => e.source !== 'rulebook_pruned');

  return (
    <DeckChartFrame
      number={displayNumber}
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
          <DeckGraphSvg
            positioned={layout.nodes}
            edges={visibleEdges}
            viewBox={layout}
            ringRadii={layout.ringRadii}
            edgeColor={(edge) =>
              edge.direction === 'bearish' ? 'rgb(var(--color-bearish))' : 'rgb(var(--color-bullish))'
            }
            selectedId={selectedId}
            onToggle={toggle}
            label="Ripple effect graph"
          />
          <GapsNote gaps={graph.gaps} />
          {selected && <ReasoningPanel company={selected} eventType={eventType} />}
        </>
      )}
    </DeckChartFrame>
  );
}
