import type { AlertCompany, GraphNode, ImpactGraph } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import CompanyNode from '../charts/primitives/CompanyNode';
import { useCompanySelection } from '../charts/useCompanySelection';
import { chainTree } from '../graph/model';
import DeckChartFrame from './DeckChartFrame';
import { EmptyGraphNote, GapsNote } from './DeckGraphShared';
import './deck.css';

// Chart 3 -- Supply Chain (Doc-2 §6). Columnar Upstream / Direct /
// Downstream, left to right, built from chainTree(graph) (real supplier/
// customer edges + the real cascade chain as downstream fallback). All
// three columns ALWAYS render; an empty one shows an honest "—" -- and it
// is never a single line of chips (the past failure this layout replaces).
function Column({
  label,
  nodes,
  selectedId,
  onToggle,
}: {
  label: string;
  nodes: GraphNode[];
  selectedId: number | null;
  onToggle: (id: number) => void;
}) {
  return (
    <div className="deck-chaincol">
      <span className="deck-groupheader">{label}</span>
      {nodes.length === 0 ? (
        <span className="deck-emptymark">—</span>
      ) : (
        nodes.map((node) => (
          <CompanyNode
            key={node.id}
            name={node.name ?? node.label}
            ticker={node.ticker ?? node.label}
            direction={node.direction}
            excessMovePct={node.excess_move_pct}
            inMyHoldings={node.in_my_holdings}
            onClick={node.company_id != null ? () => onToggle(node.company_id as number) : undefined}
            selected={node.company_id != null && selectedId === node.company_id}
          />
        ))
      )}
    </div>
  );
}

export default function DeckSupplyChain({
  graph,
  companies,
  eventType,
  displayNumber = 3,
}: {
  graph: ImpactGraph;
  companies: AlertCompany[];
  eventType?: string | null;
  displayNumber?: number;
}) {
  const { toggle, selected, selectedId } = useCompanySelection(companies);
  const { direct, upstream, downstream } = chainTree(graph, companies);

  return (
    <DeckChartFrame
      number={displayNumber}
      title="Supply Chain"
      description="Suppliers upstream and customers downstream of this alert's directly-hit company."
    >
      {direct === null ? (
        <EmptyGraphNote text="No company chain resolved for this alert." />
      ) : (
        <>
          <div className="deck-chain">
            <Column label="Upstream" nodes={upstream} selectedId={selectedId} onToggle={toggle} />
            <span className="deck-chainarrow" aria-hidden="true">
              →
            </span>
            <Column label="Direct" nodes={[direct]} selectedId={selectedId} onToggle={toggle} />
            <span className="deck-chainarrow" aria-hidden="true">
              →
            </span>
            <Column label="Downstream" nodes={downstream} selectedId={selectedId} onToggle={toggle} />
          </div>
          <GapsNote gaps={graph.gaps} />
          {selected && <ReasoningPanel company={selected} eventType={eventType} />}
        </>
      )}
    </DeckChartFrame>
  );
}
