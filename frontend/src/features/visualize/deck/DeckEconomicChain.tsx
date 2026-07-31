import type { AlertCompany, ImpactGraph } from '../../../lib/api';
import MechanismPill from '../charts/primitives/MechanismPill';
import { mechanismBackbone } from '../graph/model';
import { TIME_HORIZON_ORDER } from '../transforms';
import DeckChartFrame from './DeckChartFrame';
import { GapsNote } from './DeckGraphShared';
import './deck.css';

// Chart 9 -- Economic Chain (Doc-2 §6). The macro transmission backbone:
// mechanism nodes stacked vertically with orthogonal connectors and a
// right-side horizon label per step. When this event type has no rulebook
// chain (get_chain returns None for company-specific events -- correct, not
// a gap), the chart renders an HONEST empty state; a silently missing chart
// is indistinguishable from a bug, and that was a real defect.

// Every company_id reachable by walking forward from startId -- labels each
// mechanism step with the horizons of the companies its effects reach.
export function reachableCompanyIds(graph: ImpactGraph, startId: string): Set<number> {
  const outgoing = new Map<string, string[]>();
  for (const edge of graph.edges) {
    const list = outgoing.get(edge.from) ?? [];
    list.push(edge.to);
    outgoing.set(edge.from, list);
  }
  const nodesById = new Map(graph.nodes.map((n) => [n.id, n]));
  const visited = new Set<string>([startId]);
  const stack = [startId];
  const companyIds = new Set<number>();
  while (stack.length > 0) {
    const current = stack.pop() as string;
    for (const next of outgoing.get(current) ?? []) {
      if (visited.has(next)) continue;
      visited.add(next);
      const node = nodesById.get(next);
      if (node?.kind === 'company' && node.company_id != null) companyIds.add(node.company_id);
      stack.push(next);
    }
  }
  return companyIds;
}

export default function DeckEconomicChain({
  graph,
  companies,
}: {
  graph: ImpactGraph;
  companies: AlertCompany[];
}) {
  const mechanisms = mechanismBackbone(graph);

  return (
    <DeckChartFrame
      number={9}
      title="Economic Chain"
      description="The general macro mechanism this kind of news transmits through, step by step."
    >
      {mechanisms.length === 0 ? (
        <p className="deck-emptystate">
          No general transmission mechanism applies to this story — this event is company-specific, so
          its impact flows through the named companies directly.
        </p>
      ) : (
        <>
          <div className="deck-econ">
            {mechanisms.map((node, i) => {
              const reachedIds = reachableCompanyIds(graph, node.id);
              const horizons = TIME_HORIZON_ORDER.filter((h) =>
                companies.some((c) => reachedIds.has(c.company_id) && c.time_horizon === h),
              );
              return (
                <div key={node.id} className="deck-econstep">
                  {i > 0 && <span className="deck-econline" aria-hidden="true" />}
                  <div className="deck-econrow">
                    <MechanismPill label={node.label} />
                    {horizons.length > 0 && <span className="deck-econhorizon">{horizons.join(' · ')}</span>}
                  </div>
                </div>
              );
            })}
          </div>
          <GapsNote gaps={graph.gaps} />
        </>
      )}
    </DeckChartFrame>
  );
}
