import type { AlertArticle, AlertCompany, GraphNode, ImpactGraph } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { chainTree } from '../graph/model';
import ChartCardShell from './ChartCardShell';
import CompanyNode from './primitives/CompanyNode';
import NewsHeaderBlock from './primitives/NewsHeaderBlock';
import { useCompanySelection } from './useCompanySelection';

export function edgeBetween(graph: ImpactGraph, fromId: string, toId: string) {
  return graph.edges.find((e) => e.from === fromId && e.to === toId);
}

function CompanyTile({
  node, selected, onClick,
}: {
  node: GraphNode; selected: boolean; onClick?: () => void;
}) {
  return (
    <CompanyNode
      name={node.name ?? node.label}
      ticker={node.ticker ?? node.label}
      direction={node.direction}
      inMyHoldings={node.in_my_holdings}
      onClick={onClick}
      selected={selected}
    />
  );
}

// Column header + a vertical stack of company tiles, or a quiet "--" when
// this column has no real data (Sparse Data Rule: "an empty column shows a
// quiet --", never a fabricated entry and never a hidden/missing column).
function Column({
  label, nodes, selectedId, onToggle,
}: {
  label: string; nodes: GraphNode[]; selectedId: number | null; onToggle: (id: number) => void;
}) {
  return (
    <div className="flex flex-1 flex-col items-center gap-2">
      <p className="font-data text-[10px] uppercase tracking-widest text-muted">{label}</p>
      <div className="flex flex-col items-center gap-2">
        {nodes.length === 0 ? (
          <p className="font-data text-xs text-muted">—</p>
        ) : (
          nodes.map((node) => (
            <CompanyTile
              key={node.id}
              node={node}
              selected={node.company_id != null && selectedId === node.company_id}
              onClick={node.company_id != null ? () => onToggle(node.company_id as number) : undefined}
            />
          ))
        )}
      </div>
    </div>
  );
}

function ColumnArrow() {
  return <span aria-hidden="true" className="self-center px-1 text-muted">→</span>;
}

export default function SupplyChainGraph({
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
  const { direct, upstream, downstream } = chainTree(graph);

  if (direct === null) return null;

  return (
    <ChartCardShell
      number={3}
      title="Supply Chain Graph"
      description="Upstream suppliers and downstream customers around this alert's direct company"
      legend={[
        { label: 'Supplier', color: '#12A08C' },
        { label: 'Direct', color: '#E85D4C' },
        { label: 'Customer', color: '#9B7EDE' },
      ]}
      accentColor="#12A08C"
    >
      <div className="flex flex-col items-center gap-4">
        <NewsHeaderBlock article={article} alertCreatedAt={alertCreatedAt} />
        <div className="flex w-full items-start justify-center gap-1">
          <Column label="Upstream (Suppliers)" nodes={upstream} selectedId={selectedId} onToggle={toggle} />
          <ColumnArrow />
          <Column label="Direct Company" nodes={[direct]} selectedId={selectedId} onToggle={toggle} />
          <ColumnArrow />
          <Column label="Downstream (Customers)" nodes={downstream} selectedId={selectedId} onToggle={toggle} />
        </div>
        {selected && <ReasoningPanel company={selected} eventType={eventType} />}
      </div>
    </ChartCardShell>
  );
}
