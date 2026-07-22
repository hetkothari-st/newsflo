import { useMemo } from 'react';
import type { AlertArticle, AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { IMPACT_LEVEL_ORDER, impactLevelColor, impactLevelKey, impactLevelLabel } from '../impactLevels';
import ChartCardShell from './ChartCardShell';
import CompanyNode from './primitives/CompanyNode';
import ElbowConnector from './primitives/ElbowConnector';
import LevelBand from './primitives/LevelBand';
import NewsHeaderBlock from './primitives/NewsHeaderBlock';
import { useCompanySelection } from './useCompanySelection';

const LEGEND = [
  { label: impactLevelLabel('direct'), color: impactLevelColor('direct') },
  { label: impactLevelLabel('indirect_l1'), color: impactLevelColor('indirect_l1') },
  { label: impactLevelLabel('indirect_l2'), color: impactLevelColor('indirect_l2') },
];

export default function LevelTree({
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

  const levels = useMemo(
    () =>
      IMPACT_LEVEL_ORDER.map((level) => ({
        level,
        companies: companies.filter((c) => impactLevelKey(c) === level),
      })).filter((l) => l.companies.length > 0),
    [companies],
  );

  if (levels.length === 0) return null;

  return (
    <ChartCardShell
      number={4}
      title="Cascade Levels"
      description="Companies affected at each cascade level -- direct, and the ripple effects it triggers"
      legend={LEGEND}
      accentColor="#4A90D9"
    >
      <div className="flex flex-col items-center gap-4">
        <NewsHeaderBlock article={article} alertCreatedAt={alertCreatedAt} />
        {levels.map(({ level, companies: levelCompanies }, i) => (
          <div key={level} className="flex w-full flex-col items-center gap-3">
            {i > 0 && <ElbowConnector />}
            <LevelBand label={impactLevelLabel(level)}>
              {levelCompanies.map((c) => (
                <CompanyNode
                  key={c.company_id}
                  name={c.name}
                  ticker={c.ticker}
                  direction={c.direction}
                  magnitudeLow={c.magnitude_low}
                  magnitudeHigh={c.magnitude_high}
                  inMyHoldings={c.in_my_holdings}
                  onClick={() => toggle(c.company_id)}
                  selected={selectedId === c.company_id}
                />
              ))}
            </LevelBand>
          </div>
        ))}
        {selected && <ReasoningPanel company={selected} eventType={eventType} />}
      </div>
    </ChartCardShell>
  );
}
