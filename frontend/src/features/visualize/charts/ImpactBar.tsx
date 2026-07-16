import type { AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { rankByMagnitude } from '../transforms';
import { useCompanySelection } from './useCompanySelection';

// Bar length comes from rank position within this side only (index 0 =
// nearest the axis = strongest in this alert), never from the raw
// magnitude float -- see rankByMagnitude's docstring.
function widthForRank(index: number, total: number): number {
  if (total <= 1) return 100;
  return 100 - (index / total) * 60;
}

// The bar segment gets a fixed pixel width scaled by rank, independent of
// the row/label width, so a long ticker name can never squeeze it to 0px.
// MIN_BAR_PX keeps even the weakest rank visibly present.
//
// Sizing measured directly in a real 390px-wide mobile viewport (the app's
// primary test width): the grid-cols-2 column is 165.6px wide, gap-2
// between label and bar is 8px, and the longest observed realistic ticker
// label (TATAMOTORS.NS, incl. arrow glyph) is ~109.5px. That leaves only
// ~48px for the bar before the row overflows and the overflow-x-auto
// fallback kicks in with a visible scrollbar. MAX_BAR_PX is kept safely
// under that hard limit; MIN_BAR_PX is scaled down proportionally so the
// weakest rank still reads as clearly shorter, not identical.
const MAX_BAR_PX = 40;
const MIN_BAR_PX = 4;

function barWidthPx(index: number, total: number): number {
  return Math.max(MIN_BAR_PX, (widthForRank(index, total) / 100) * MAX_BAR_PX);
}

function Bar({ company, side, onSelect }: { company: AlertCompany; side: 'left' | 'right'; onSelect: () => void }) {
  const bullish = company.direction === 'bullish';
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`flex shrink-0 items-center gap-2 text-xs ${side === 'left' ? 'flex-row-reverse' : ''}`}
    >
      <span className={bullish ? 'text-bullish' : 'text-bearish'} aria-hidden="true">
        {bullish ? '▲' : '▼'}
      </span>
      <span className="text-ink">{company.ticker}</span>
    </button>
  );
}

export default function ImpactBar({
  companies,
  eventType,
}: {
  companies: AlertCompany[];
  eventType?: string | null;
}) {
  const { toggle, selected } = useCompanySelection(companies);
  const bullish = rankByMagnitude(companies.filter((c) => c.direction === 'bullish'));
  const bearish = rankByMagnitude(companies.filter((c) => c.direction === 'bearish'));

  if (bullish.length === 0 && bearish.length === 0) return null;

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col items-end gap-2">
          {bearish.map((company, i) => (
            <div key={company.company_id} className="flex w-full items-center justify-end gap-2 overflow-x-auto">
              <div
                className="h-2 shrink-0 rounded-l-full bg-bearish"
                style={{ width: `${barWidthPx(i, bearish.length)}px` }}
              />
              <Bar company={company} side="left" onSelect={() => toggle(company.company_id)} />
            </div>
          ))}
        </div>
        <div className="flex flex-col items-start gap-2">
          {bullish.map((company, i) => (
            <div key={company.company_id} className="flex w-full items-center gap-2 overflow-x-auto">
              <Bar company={company} side="right" onSelect={() => toggle(company.company_id)} />
              <div
                className="h-2 shrink-0 rounded-r-full bg-bullish"
                style={{ width: `${barWidthPx(i, bullish.length)}px` }}
              />
            </div>
          ))}
        </div>
      </div>
      {selected && <ReasoningPanel company={selected} eventType={eventType} />}
    </div>
  );
}
