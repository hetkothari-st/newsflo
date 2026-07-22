import type { AlertArticle, AlertCompany, ImpactGraph } from '../../../lib/api';
import { mechanismBackbone } from '../graph/model';
import { TIME_HORIZON_ORDER } from '../transforms';
import ChartCardShell from './ChartCardShell';
import ElbowConnector from './primitives/ElbowConnector';
import MechanismPill from './primitives/MechanismPill';
import NewsHeaderBlock from './primitives/NewsHeaderBlock';

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
  article,
  alertCreatedAt,
}: {
  graph: ImpactGraph;
  companies: AlertCompany[];
  article: AlertArticle;
  alertCreatedAt: string;
}) {
  const mechanisms = mechanismBackbone(graph);

  return (
    <ChartCardShell
      number={9}
      title="Economic Chain"
      description="The mechanism backbone of this news, from immediate effects to longer-term ones"
      accentColor="#6C8CD5"
    >
      <div className="flex flex-col items-center gap-4">
        <NewsHeaderBlock article={article} alertCreatedAt={alertCreatedAt} />
        {mechanisms.length === 0 ? (
          // This event type has no rulebook chain (see backend
          // app.reasoning.rulebook.CHAINS -- only 5 event types have one;
          // the rest build their graph purely from the LLM cascade's own
          // per-company edges, by design, not a gap). A silently missing
          // chart reads as broken; this says plainly why it's empty.
          <p className="px-1 py-2 text-center font-data text-xs uppercase tracking-widest text-muted">
            No mechanism chain modeled for this event type yet
          </p>
        ) : (
          <div className="flex w-full max-w-sm flex-col items-center">
            {mechanisms.map((node, i) => {
              const reachedIds = reachableCompanyIds(graph, node.id);
              const horizons = TIME_HORIZON_ORDER.filter((h) =>
                companies.some((c) => reachedIds.has(c.company_id) && c.time_horizon === h),
              );
              return (
                <div key={node.id} className="flex w-full flex-col items-center">
                  {i > 0 && <ElbowConnector />}
                  <div className="flex w-full items-center justify-between gap-3">
                    <MechanismPill label={node.label} />
                    {horizons.length > 0 && (
                      <span className="shrink-0 font-data text-[10px] uppercase tracking-widest text-muted">
                        {horizons.join(' · ')}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </ChartCardShell>
  );
}
