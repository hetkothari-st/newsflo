import type { AlertArticle, AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import CompanyNode from '../charts/primitives/CompanyNode';
import { useCompanySelection } from '../charts/useCompanySelection';
import DeckChartFrame from './DeckChartFrame';
import { groupByImpactLevel, newsKickerLabel } from './deckData';
import { renderTree } from './renderTree';

// Chart 1 -- Impact Tree (Doc-1 §4). Three levels by impact_level; a level
// with no companies is omitted entirely, never rendered as an empty band.
const LEVEL_META: Record<string, { label: string; sub: string }> = {
  direct: { label: 'Primary', sub: 'directly affected' },
  indirect_l1: { label: 'Secondary', sub: 'indirect' },
  indirect_l2: { label: 'Tertiary', sub: 'wider ecosystem' },
};

export default function DeckImpactTree({
  companies,
  article,
  alertCreatedAt,
  eventType,
}: {
  companies: AlertCompany[];
  article: AlertArticle;
  alertCreatedAt: string;
  eventType?: string | null;
}) {
  const { toggle, selected, selectedId } = useCompanySelection(companies);

  const levels = [...groupByImpactLevel(companies).entries()]
    .filter(([, members]) => members.length > 0)
    .map(([key, members]) => ({
      key,
      label: LEVEL_META[key].label,
      sub: LEVEL_META[key].sub,
      companyIds: members.map((c) => c.company_id),
    }));

  return (
    <DeckChartFrame
      number={1}
      title="Impact Tree"
      description="How the news branches from directly-hit companies down through the ripple."
      legend={[
        { label: 'Positive', color: 'rgb(var(--color-bullish))' },
        { label: 'Negative', color: 'rgb(var(--color-bearish))' },
      ]}
    >
      {renderTree(
        {
          newsLabel: newsKickerLabel(alertCreatedAt),
          newsHeadline: article.title,
          levels,
          nodeContent: (c) => (
            <CompanyNode
              name={c.name}
              ticker={c.ticker}
              direction={c.direction}
              excessMovePct={c.excess_move_pct}
              inMyHoldings={c.in_my_holdings}
              onClick={() => toggle(c.company_id)}
              selected={selectedId === c.company_id}
            />
          ),
        },
        companies,
      )}
      {selected && <ReasoningPanel company={selected} eventType={eventType} />}
    </DeckChartFrame>
  );
}
