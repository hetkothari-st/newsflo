import type { AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { groupByTier } from '../transforms';
import { useCompanySelection } from './useCompanySelection';

function netSentiment(companies: AlertCompany[]): 'bullish' | 'bearish' | 'even' {
  const bullish = companies.filter((c) => c.direction === 'bullish').length;
  const bearish = companies.filter((c) => c.direction === 'bearish').length;
  if (bullish === bearish) return 'even';
  return bullish > bearish ? 'bullish' : 'bearish';
}

export default function TierRows({ companies }: { companies: AlertCompany[] }) {
  const { toggle, selected } = useCompanySelection(companies);
  const groups = groupByTier(companies);

  if (groups.length === 0) return null;

  return (
    <div className="flex flex-col gap-3 p-4">
      {groups.map((group) => {
        const net = netSentiment(group.companies);
        return (
          <div
            key={group.key}
            className="flex flex-col gap-2 rounded-lg border border-hairline bg-surface p-3 theme-light:border-transparent theme-light:shadow-neu-sm"
          >
            <div className="flex items-center justify-between">
              <p className="text-xs uppercase tracking-widest text-muted">{group.label}</p>
              {net === 'even' ? (
                <span aria-label="Evenly split" className="text-xs text-muted">
                  ▬
                </span>
              ) : (
                <span aria-label={net === 'bullish' ? 'Net bullish' : 'Net bearish'} className={net === 'bullish' ? 'text-bullish' : 'text-bearish'}>
                  {net === 'bullish' ? '▲' : '▼'}
                </span>
              )}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {group.companies.map((company) => {
                const bullish = company.direction === 'bullish';
                return (
                  <button
                    key={company.company_id}
                    type="button"
                    onClick={() => toggle(company.company_id)}
                    className="flex items-center gap-1 rounded-md bg-page px-2 py-1 text-xs text-ink hover:border-muted"
                  >
                    <span className={bullish ? 'text-bullish' : 'text-bearish'} aria-hidden="true">
                      {bullish ? '▲' : '▼'}
                    </span>
                    {company.ticker}
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}
      {selected && <ReasoningPanel company={selected} />}
    </div>
  );
}
