import type { AlertArticle, AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import CompanyNode from '../charts/primitives/CompanyNode';
import { useCompanySelection } from '../charts/useCompanySelection';
import { rankByMove } from '../transforms';
import DeckChartFrame from './DeckChartFrame';
import './deck.css';

// Chart 6 -- Positive / Negative Split (Doc-1 §4). Both direction panels
// ALWAYS render, even when one side is empty (an honest "—"), so a one-
// sided alert still reads as one-sided rather than incomplete. Neutral
// companies get a third, quieter panel only when any exist.
function Panel({
  title,
  tone,
  companies,
  selectedId,
  onToggle,
}: {
  title: string;
  tone: 'up' | 'down' | 'neutral';
  companies: AlertCompany[];
  selectedId: number | null;
  onToggle: (id: number) => void;
}) {
  return (
    <div className="deck-splitpanel">
      <span className={`deck-groupheader deck-split-${tone}`}>
        {title}
        <span className="deck-groupsub"> · {companies.length}</span>
      </span>
      {companies.length === 0 ? (
        <span className="deck-emptymark" aria-label={`No ${title.toLowerCase()} companies`}>
          —
        </span>
      ) : (
        <div className="deck-nodewrap">
          {rankByMove(companies).map((c) => (
            <CompanyNode
              key={c.company_id}
              name={c.name}
              ticker={c.ticker}
              direction={c.direction}
              excessMovePct={c.excess_move_pct}
              inMyHoldings={c.in_my_holdings}
              onClick={() => onToggle(c.company_id)}
              selected={selectedId === c.company_id}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function DeckSplit({
  companies,
  article: _article,
  alertCreatedAt: _alertCreatedAt,
  eventType,
}: {
  companies: AlertCompany[];
  article: AlertArticle;
  alertCreatedAt: string;
  eventType?: string | null;
}) {
  const { toggle, selected, selectedId } = useCompanySelection(companies);
  const bullish = companies.filter((c) => c.direction === 'bullish');
  const bearish = companies.filter((c) => c.direction === 'bearish');
  const neutral = companies.filter((c) => c.direction !== 'bullish' && c.direction !== 'bearish');

  return (
    <DeckChartFrame
      number={6}
      title="Positive / Negative Split"
      description="Who gains and who loses, ranked by the size of the measured move."
    >
      <Panel title="Positive" tone="up" companies={bullish} selectedId={selectedId} onToggle={toggle} />
      <Panel title="Negative" tone="down" companies={bearish} selectedId={selectedId} onToggle={toggle} />
      {neutral.length > 0 && (
        <Panel title="No significant impact" tone="neutral" companies={neutral} selectedId={selectedId} onToggle={toggle} />
      )}
      {selected && <ReasoningPanel company={selected} eventType={eventType} />}
    </DeckChartFrame>
  );
}
