import type { AlertCompany } from '../../../../lib/api';
import CompanyAvatar from '../../../../components/CompanyAvatar';

// One company row inside an ImpactCard -- avatar monogram, name/ticker
// stacked, direction-colored confidence % right-aligned. Shared by every
// rebuilt chart (Sector, Levels, Confidence, Split, Timeline) so a company
// looks identical no matter which card grouping it's shown under.
export default function CompanyRow({
  company,
  onClick,
  selected = false,
}: {
  company: AlertCompany;
  onClick: () => void;
  selected?: boolean;
}) {
  const bullish = company.direction === 'bullish';
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-page ${
        selected ? 'bg-page ring-1 ring-inset ring-hairline' : ''
      }`}
    >
      <CompanyAvatar ticker={company.ticker} />
      <span className="flex min-w-0 flex-col">
        <span className="truncate text-sm text-ink">{company.name}</span>
        <span className="truncate font-mono text-[11px] tracking-tight text-muted">{company.ticker}</span>
      </span>
      <span
        aria-hidden="true"
        className={`ml-auto shrink-0 whitespace-nowrap text-sm font-medium ${bullish ? 'text-bullish' : 'text-bearish'}`}
      >
        {bullish ? '▲' : '▼'} {company.confidence_score}%
      </span>
    </button>
  );
}
