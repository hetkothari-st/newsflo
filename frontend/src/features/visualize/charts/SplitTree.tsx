import type { AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { rankByMagnitude } from '../transforms';
import ChartCardShell from './ChartCardShell';
import CompanyRow from './cards/CompanyRow';
import { useCompanySelection } from './useCompanySelection';

function SplitColumn({
  title,
  tone,
  companies,
  selectedId,
  onSelect,
}: {
  title: string;
  tone: 'bullish' | 'bearish';
  companies: AlertCompany[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  if (companies.length === 0) return null;
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-hairline p-3.5 theme-light:border-transparent theme-light:shadow-neu-sm">
      <div className="flex items-center justify-between">
        <p className={`text-xs uppercase tracking-widest ${tone === 'bullish' ? 'text-bullish' : 'text-bearish'}`}>{title}</p>
        <span className="text-xs text-muted">{companies.length}</span>
      </div>
      <div className="flex flex-col gap-1">
        {companies.map((c) => (
          <CompanyRow key={c.company_id} company={c} selected={selectedId === c.company_id} onClick={() => onSelect(c.company_id)} />
        ))}
      </div>
    </div>
  );
}

export default function SplitTree({
  companies,
  eventType,
}: {
  companies: AlertCompany[];
  eventType?: string | null;
}) {
  const { toggle, selected, selectedId } = useCompanySelection(companies);
  const bullish = rankByMagnitude(companies.filter((c) => c.direction === 'bullish'));
  const bearish = rankByMagnitude(companies.filter((c) => c.direction === 'bearish'));

  if (bullish.length === 0 && bearish.length === 0) return null;

  return (
    <ChartCardShell
      number={6}
      title="Positive / Negative Split"
      description="Clear separation of positive and negative impact"
      legend={[
        { label: 'Positive Impact', color: '#34C759' },
        { label: 'Negative Impact', color: '#FF453A' },
      ]}
    >
      <div className="flex flex-col gap-3 p-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <SplitColumn title="Positive Impact" tone="bullish" companies={bullish} selectedId={selectedId} onSelect={toggle} />
          <SplitColumn title="Negative Impact" tone="bearish" companies={bearish} selectedId={selectedId} onSelect={toggle} />
        </div>
        {selected && <ReasoningPanel company={selected} eventType={eventType} />}
      </div>
    </ChartCardShell>
  );
}
