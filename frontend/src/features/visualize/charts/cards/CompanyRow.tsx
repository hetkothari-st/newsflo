import type { AlertCompany } from '../../../../lib/api';
import CompanyAvatar from '../../../../components/CompanyAvatar';
import { sectorColor } from '../../colors';
import { sectorLabel } from '../../transforms';

// One company row inside an ImpactCard -- avatar monogram, name/ticker
// stacked, direction-colored confidence % right-aligned. Shared by every
// rebuilt chart (Sector, Levels, Confidence, Split, Timeline) so a company
// looks identical no matter which card grouping it's shown under.
//
// `onClick` is optional -- when omitted (e.g. a chart with no tap-to-expand
// behavior), the row renders as a plain, non-interactive block instead of a
// button, so it doesn't imply an action that does nothing.
//
// `showSector` is optional -- pass it to show a sector chip alongside the
// ticker (reads `company.sector` directly, no separate value to keep in
// sync). Useful when the row's own card grouping doesn't already imply a
// single sector (e.g. a cascade/parent-linked group can mix sectors).
export default function CompanyRow({
  company,
  onClick,
  selected = false,
  showSector = false,
}: {
  company: AlertCompany;
  onClick?: () => void;
  selected?: boolean;
  showSector?: boolean;
}) {
  const bullish = company.direction === 'bullish';
  const content = (
    <>
      <CompanyAvatar ticker={company.ticker} />
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="truncate text-sm text-ink">{company.name}</span>
        <span className="flex items-center gap-1.5">
          <span className="truncate font-mono text-[11px] tracking-tight text-muted">{company.ticker}</span>
          {showSector && company.sector && (
            <span className="inline-flex shrink-0 items-center gap-1 font-data text-[10px] uppercase tracking-widest text-muted">
              <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: sectorColor(company.sector) }} />
              {sectorLabel(company.sector)}
            </span>
          )}
        </span>
      </span>
      <span
        aria-hidden="true"
        className={`ml-auto shrink-0 whitespace-nowrap text-sm font-medium ${bullish ? 'text-bullish' : 'text-bearish'}`}
      >
        {bullish ? '▲' : '▼'} {company.confidence_score}%
      </span>
    </>
  );

  const ringClass = company.in_my_holdings ? 'ring-2 ring-accent-secondary' : '';

  if (!onClick) {
    return <div className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 ${ringClass}`}>{content}</div>;
  }

  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-page ${
        selected ? 'bg-page' : ''
      } ${ringClass}`}
    >
      {content}
    </button>
  );
}
