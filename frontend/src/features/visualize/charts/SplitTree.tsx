import type { AlertArticle, AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { rankByMagnitude } from '../transforms';
import ChartCardShell from './ChartCardShell';
import CompanyRow from './cards/CompanyRow';
import NewsHeaderBlock from './primitives/NewsHeaderBlock';
import { useCompanySelection } from './useCompanySelection';

// Grouped-panel structure (reference: docs/charts-reference.png) -- a
// colored header strip, then rows inside. Always renders, even with zero
// companies on this side (Sparse Data Rule: "Panel charts still show both
// panels even if one is empty") -- an em dash reads as a deliberate,
// honest "nothing here," not a broken/missing panel.
function SplitColumn({
  title,
  colorVar,
  companies,
  selectedId,
  onSelect,
}: {
  title: string;
  colorVar: string;
  companies: AlertCompany[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  return (
    <div className="flex flex-col gap-2 overflow-hidden rounded-xl border border-hairline theme-light:border-transparent theme-light:shadow-neu-sm">
      <div className="flex items-center justify-between px-3.5 py-2" style={{ backgroundColor: `rgb(var(${colorVar}) / 0.12)` }}>
        <p className="font-data text-xs uppercase tracking-widest" style={{ color: `rgb(var(${colorVar}))` }}>{title}</p>
        <span className="font-data text-xs text-muted">{companies.length}</span>
      </div>
      <div className="flex flex-col gap-1 px-3.5 pb-3.5">
        {companies.length === 0 ? (
          <p className="px-2 py-1 font-data text-xs text-muted">—</p>
        ) : (
          companies.map((c) => (
            <CompanyRow key={c.company_id} company={c} selected={selectedId === c.company_id} onClick={() => onSelect(c.company_id)} />
          ))
        )}
      </div>
    </div>
  );
}

export default function SplitTree({
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
  const bullish = rankByMagnitude(companies.filter((c) => c.direction === 'bullish'));
  const bearish = rankByMagnitude(companies.filter((c) => c.direction === 'bearish'));

  if (bullish.length === 0 && bearish.length === 0) return null;

  return (
    <ChartCardShell
      number={6}
      title="Positive / Negative Split"
      description="Clear separation of positive and negative impact"
      legend={[
        { label: 'Positive Impact', color: 'rgb(var(--color-bullish))' },
        { label: 'Negative Impact', color: 'rgb(var(--color-bearish))' },
      ]}
      accentColor="rgb(var(--color-bullish))"
    >
      <div className="flex flex-col items-center gap-4">
        <NewsHeaderBlock article={article} alertCreatedAt={alertCreatedAt} />
        <div className="grid w-full grid-cols-1 gap-3 sm:grid-cols-2">
          <SplitColumn title="Positive Impact" colorVar="--color-bullish" companies={bullish} selectedId={selectedId} onSelect={toggle} />
          <SplitColumn title="Negative Impact" colorVar="--color-bearish" companies={bearish} selectedId={selectedId} onSelect={toggle} />
        </div>
        {selected && <ReasoningPanel company={selected} eventType={eventType} />}
      </div>
    </ChartCardShell>
  );
}
