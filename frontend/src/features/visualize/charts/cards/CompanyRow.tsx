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
// `sector` is optional -- pass it when the row's own card grouping doesn't
// already imply a single sector (e.g. a cascade/parent-linked group can mix
// sectors), so the sector is still visible per-company.
export default function CompanyRow({
  company,
  onClick,
  selected = false,
  sector,
}: {
  company: AlertCompany;
  onClick?: () => void;
  selected?: boolean;
  sector?: string;
}) {
  const bullish = company.direction === 'bullish';
  const content = (
    <>
      <CompanyAvatar ticker={company.ticker} />
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="truncate text-sm text-ink">{company.name}</span>
        <span className="flex items-center gap-1.5">
          <span className="truncate font-mono text-[11px] tracking-tight text-muted">{company.ticker}</span>
          {sector && (
            <span className="inline-flex shrink-0 items-center gap-1 font-data text-[10px] uppercase tracking-wide text-muted">
              <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: sectorColor(sector) }} />
              {sectorLabel(sector)}
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

  if (!onClick) {
    return <div className="flex w-full items-center gap-2 rounded-md px-2 py-1.5">{content}</div>;
  }

  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-page ${
        selected ? 'bg-page ring-1 ring-inset ring-hairline' : ''
      }`}
    >
      {content}
    </button>
  );
}
