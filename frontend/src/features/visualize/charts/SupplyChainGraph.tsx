import type { AlertCompany, ImpactGraph } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { longestChainPath } from '../graph/model';
import ChartCardShell from './ChartCardShell';
import GraphNodeChip from './cards/GraphNodeChip';
import { useCompanySelection } from './useCompanySelection';

export function edgeBetween(graph: ImpactGraph, fromId: string, toId: string) {
  return graph.edges.find((e) => e.from === fromId && e.to === toId);
}

export default function SupplyChainGraph({
  graph,
  companies,
  eventType,
}: {
  graph: ImpactGraph;
  companies: AlertCompany[];
  eventType?: string | null;
}) {
  const { toggle, selected, selectedId } = useCompanySelection(companies);
  const path = longestChainPath(graph);

  if (path.length <= 1) return null;

  return (
    <ChartCardShell
      number={3}
      title="Supply Chain Graph"
      description="The longest single transmission path from this news to a company"
    >
      <div className="flex flex-col items-center gap-3 p-4">
        <div className="flex flex-wrap items-center justify-center gap-2">
          {path.map((node, i) => {
            const edge = i > 0 ? edgeBetween(graph, path[i - 1].id, node.id) : null;
            const isCompany = node.kind === 'company' && node.company_id != null;
            return (
              <div key={node.id} className="flex items-center gap-2">
                {i > 0 && (
                  <div className="flex flex-col items-center px-1 text-center">
                    <span aria-hidden="true" className="text-muted">→</span>
                    {edge && <span className="font-data text-[9px] uppercase tracking-widest text-muted">{edge.relation}</span>}
                  </div>
                )}
                <GraphNodeChip
                  node={node}
                  onClick={isCompany ? () => toggle(node.company_id as number) : undefined}
                  selected={isCompany && selectedId === node.company_id}
                />
              </div>
            );
          })}
        </div>
        {selected && <ReasoningPanel company={selected} eventType={eventType} />}
      </div>
    </ChartCardShell>
  );
}
