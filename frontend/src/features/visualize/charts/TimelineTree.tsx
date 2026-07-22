import type { AlertArticle, AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { groupByTimeHorizon } from '../transforms';
import ChartCardShell from './ChartCardShell';
import CompanyNode from './primitives/CompanyNode';
import NewsHeaderBlock from './primitives/NewsHeaderBlock';
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

// Reuses 4 already-validated hexes from colors.ts's SECTOR_COLOR palette
// (see that file's validation comment) -- one per horizon, so the rail's
// dots are visually distinct without introducing a new, unvalidated
// palette for a 4-value scale.
const HORIZON_COLOR: Record<string, string> = {
  Immediate: '#E85D4C',
  'Short-Term': '#4A90D9',
  'Medium-Term': '#C97F0E',
  'Long-Term': '#3E9B5C',
};

export default function TimelineTree({
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
  const groups = groupByTimeHorizon(companies);

  if (groups.length === 0) return null;

  return (
    <ChartCardShell
      number={7}
      title="Timeline Tree"
      description="Impact progression over different time horizons"
      accentColor={HORIZON_COLOR.Immediate}
    >
      <div className="flex flex-col items-center gap-4">
        <NewsHeaderBlock article={article} alertCreatedAt={alertCreatedAt} />
        <div className="flex w-full flex-col">
          {groups.map((group, i) => (
            <div key={group.key} className="flex gap-3">
              <div className="flex flex-col items-center">
                <span
                  aria-hidden="true"
                  className="mt-1 h-3 w-3 shrink-0 rounded-full"
                  style={{ backgroundColor: HORIZON_COLOR[group.key] ?? 'rgb(var(--color-ink))' }}
                />
                {i < groups.length - 1 && <span aria-hidden="true" className="w-px flex-1 bg-hairline" />}
              </div>
              <div className="flex-1 pb-4">
                <p className="text-xs uppercase tracking-widest text-ink">{group.label}</p>
                <p className="mt-0.5 text-xs text-muted">{HORIZON_CAPTION[group.key] ?? ''}</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {group.companies.map((c) => (
                    <CompanyNode
                      key={c.company_id}
                      name={c.name}
                      ticker={c.ticker}
                      direction={c.direction}
                      magnitudeLow={c.magnitude_low}
                      magnitudeHigh={c.magnitude_high}
                      inMyHoldings={c.in_my_holdings}
                      selected={selectedId === c.company_id}
                      onClick={() => toggle(c.company_id)}
                    />
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
        {selected && <ReasoningPanel company={selected} eventType={eventType} />}
      </div>
    </ChartCardShell>
  );
}
