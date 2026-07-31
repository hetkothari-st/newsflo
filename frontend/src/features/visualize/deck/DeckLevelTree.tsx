import type { AlertArticle, AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import CompanyNode from '../charts/primitives/CompanyNode';
import { useCompanySelection } from '../charts/useCompanySelection';
import DeckChartFrame from './DeckChartFrame';
import { groupByImpactLevel, newsKickerLabel, orderByParent } from './deckData';
import { renderTree } from './renderTree';

// Chart 4 -- Multi-Level Impact Tree (Doc-1 §4). Same engine and grouping
// as chart 1; what distinguishes it is the explicit level numbering + count
// in each band label and parent-ordered children (a company sits under the
// parent it was cascaded from, so the branch reads as caused-by).
const LEVEL_NAME: Record<string, string> = {
  direct: 'direct',
  indirect_l1: 'indirect',
  indirect_l2: 'ecosystem',
};

export default function DeckLevelTree({
  companies,
  article,
  alertCreatedAt,
  eventType,
  displayNumber = 4,
}: {
  companies: AlertCompany[];
  article: AlertArticle;
  alertCreatedAt: string;
  eventType?: string | null;
  displayNumber?: number;
}) {
  const { toggle, selected, selectedId } = useCompanySelection(companies);

  const grouped = [...groupByImpactLevel(companies).entries()].filter(([, members]) => members.length > 0);
  let previousLevelIds: number[] = [];
  const levels = grouped.map(([key, members], index) => {
    const ordered = orderByParent(members, previousLevelIds);
    previousLevelIds = ordered.map((c) => c.company_id);
    return {
      key,
      label: `Level ${index + 1}`,
      sub: `${LEVEL_NAME[key]} · ${members.length}`,
      companyIds: previousLevelIds,
    };
  });

  return (
    <DeckChartFrame
      number={displayNumber}
      title="Multi-Level Tree"
      description="Explicit cascade levels with counts; children sit under the company that caused them."
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
