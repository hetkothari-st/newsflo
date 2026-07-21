import type { AlertCompany, ImpactGraph } from '../../../lib/api';
import { mechanismBackbone } from '../graph/model';
import { TIME_HORIZON_ORDER } from '../transforms';
import ChartCardShell from './ChartCardShell';
import GraphNodeChip from './cards/GraphNodeChip';

// Every company_id reachable by walking forward (via graph.edges) from
// startId -- used to find which companies a given mechanism node's effects
// eventually reach, so the chain can be labeled with their time horizons.
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

export default function EconomicChain({
  graph,
  companies,
}: {
  graph: ImpactGraph;
  companies: AlertCompany[];
}) {
  const mechanisms = mechanismBackbone(graph);

  if (mechanisms.length === 0) return null;

  return (
    <ChartCardShell
      number={9}
      title="Economic Chain"
      description="The mechanism backbone of this news, from immediate effects to longer-term ones"
    >
      <div className="flex flex-col items-center gap-3 p-4">
        {mechanisms.map((node, i) => {
          const reachedIds = reachableCompanyIds(graph, node.id);
          const horizons = TIME_HORIZON_ORDER.filter((h) =>
            companies.some((c) => reachedIds.has(c.company_id) && c.time_horizon === h),
          );
          return (
            <div key={node.id} className="flex w-full max-w-xs flex-col items-center gap-1">
              {i > 0 && <span aria-hidden="true" className="text-muted">↓</span>}
              <GraphNodeChip node={node} />
              {horizons.length > 0 && (
                <span className="font-data text-[10px] uppercase tracking-widest text-muted">{horizons.join(' · ')}</span>
              )}
            </div>
          );
        })}
      </div>
    </ChartCardShell>
  );
}
