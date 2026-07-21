import type { AlertCompany } from '../../../../lib/api';
import { sectorColor } from '../../colors';
import { sectorLabel } from '../../transforms';

// Compact vertical tile: ticker, name, optional sector chip, direction %.
// Shared by ImpactTree (flat sector blocks) and LevelTree (flat per-level
// grid) -- both show companies in a dense grid rather than a row list, so
// this stays visually distinct from CompanyRow (the horizontal list-item
// variant used by the collapsible ImpactCard groups elsewhere).
//
// `onClick` is optional -- when provided, the card becomes a button (e.g.
// LevelTree uses this to toggle a "linked via" detail for cascade
// companies); when omitted it's a plain, non-interactive tile.
export default function CompanyCard({
  company,
  showSector = false,
  onClick,
  selected = false,
}: {
  company: AlertCompany;
  showSector?: boolean;
  onClick?: () => void;
  selected?: boolean;
}) {
  const bearish = company.direction === 'bearish';
  const content = (
    <>
      <span className="font-data text-xs font-semibold text-ink">{company.ticker}</span>
      <span className="truncate font-editorial text-sm text-ink">{company.name}</span>
      {showSector && company.sector && (
        <span className="inline-flex items-center gap-1 font-data text-[10px] uppercase tracking-widest text-muted">
          <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: sectorColor(company.sector) }} />
          {sectorLabel(company.sector)}
        </span>
      )}
      <span className={`font-data text-xs ${bearish ? 'text-bearish' : 'text-bullish'}`}>
        <span aria-hidden="true">{bearish ? '▼' : '▲'}</span> {company.confidence_score}%
      </span>
    </>
  );

  const className = `flex flex-col gap-0.5 rounded-lg border p-2.5 text-left theme-light:shadow-neu-sm ${
    selected ? 'border-ink theme-light:border-ink' : 'border-hairline theme-light:border-transparent'
  }`;

  if (!onClick) {
    return <div className={className}>{content}</div>;
  }

  return (
    <button type="button" onClick={onClick} aria-pressed={selected} className={className}>
      {content}
    </button>
  );
}
