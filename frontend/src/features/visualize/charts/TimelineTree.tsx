import type { AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { groupByTimeHorizon } from '../transforms';
import CompanyRow from './cards/CompanyRow';
import { useCompanySelection } from './useCompanySelection';

// Plain-language gloss for each horizon, matching the definitions
// analysts are actually instructed to use (backend ANALYSIS_INSTRUCTIONS
// rule 10) rather than the mockup's specific day-ranges, which would
// overstate precision this app doesn't have.
const HORIZON_CAPTION: Record<string, string> = {
  Immediate: 'Already priced in, or resolves within days',
  'Short-Term': 'Plays out over the next few weeks to a quarter',
  'Medium-Term': 'Multi-quarter',
  'Long-Term': 'Structural, multi-year',
};

export default function TimelineTree({
  companies,
  eventType,
}: {
  companies: AlertCompany[];
  eventType?: string | null;
}) {
  const { toggle, selected, selectedId } = useCompanySelection(companies);
  const groups = groupByTimeHorizon(companies);

  if (groups.length === 0) return null;

  return (
    <div className="flex flex-col p-4">
      {groups.map((group, i) => (
        <div key={group.key} className="flex gap-3">
          <div className="flex flex-col items-center">
            <span aria-hidden="true" className="mt-1 h-3 w-3 shrink-0 rounded-full bg-ink" />
            {i < groups.length - 1 && <span aria-hidden="true" className="w-px flex-1 bg-hairline" />}
          </div>
          <div className="flex-1 pb-4">
            <p className="text-xs uppercase tracking-widest text-ink">{group.label}</p>
            <p className="mt-0.5 text-xs text-muted">{HORIZON_CAPTION[group.key] ?? ''}</p>
            <div className="mt-2 grid grid-cols-1 gap-1 sm:grid-cols-2">
              {group.companies.map((c) => (
                <CompanyRow key={c.company_id} company={c} selected={selectedId === c.company_id} onClick={() => toggle(c.company_id)} />
              ))}
            </div>
          </div>
        </div>
      ))}
      {selected && (
        <div className="mt-2">
          <ReasoningPanel company={selected} eventType={eventType} />
        </div>
      )}
    </div>
  );
}
