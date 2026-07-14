import type { AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { groupBySector } from '../transforms';
import { useCompanySelection } from './useCompanySelection';

export default function SectorTreemap({ companies }: { companies: AlertCompany[] }) {
  const { toggle, selected } = useCompanySelection(companies);
  const groups = groupBySector(companies);

  if (groups.length === 0) return null;

  return (
    <div className="flex flex-col gap-3 p-4">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {groups.map((group) => (
          <div
            key={group.key}
            className="flex flex-col gap-2 rounded-lg border border-hairline bg-surface p-3 theme-light:border-transparent theme-light:shadow-neu-sm"
            style={{ borderTop: `3px solid ${group.color}` }}
          >
            <p className="text-xs uppercase tracking-widest text-muted">{group.label}</p>
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
        ))}
      </div>
      {selected && <ReasoningPanel company={selected} />}
    </div>
  );
}
