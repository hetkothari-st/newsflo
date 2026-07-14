import { useState } from 'react';
import type { AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { rankByMagnitude } from '../transforms';

// Bar length comes from rank position within this side only (index 0 =
// nearest the axis = strongest in this alert), never from the raw
// magnitude float -- see rankByMagnitude's docstring.
function widthForRank(index: number, total: number): number {
  if (total <= 1) return 100;
  return 100 - (index / total) * 60;
}

function Bar({ company, side, onSelect }: { company: AlertCompany; side: 'left' | 'right'; onSelect: () => void }) {
  const bullish = company.direction === 'bullish';
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`flex items-center gap-2 text-xs ${side === 'left' ? 'flex-row-reverse' : ''}`}
    >
      <span className={bullish ? 'text-bullish' : 'text-bearish'} aria-hidden="true">
        {bullish ? '▲' : '▼'}
      </span>
      <span className="text-ink">{company.ticker}</span>
    </button>
  );
}

export default function ImpactBar({ companies }: { companies: AlertCompany[] }) {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const bullish = rankByMagnitude(companies.filter((c) => c.direction === 'bullish'));
  const bearish = rankByMagnitude(companies.filter((c) => c.direction === 'bearish'));

  if (bullish.length === 0 && bearish.length === 0) return null;

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col items-end gap-2">
          {bearish.map((company, i) => (
            <div key={company.company_id} className="flex items-center justify-end gap-2" style={{ width: `${widthForRank(i, bearish.length)}%` }}>
              <div className="h-2 flex-1 rounded-l-full bg-bearish" />
              <Bar company={company} side="left" onSelect={() => setSelectedId((id) => (id === company.company_id ? null : company.company_id))} />
            </div>
          ))}
        </div>
        <div className="flex flex-col items-start gap-2">
          {bullish.map((company, i) => (
            <div key={company.company_id} className="flex items-center gap-2" style={{ width: `${widthForRank(i, bullish.length)}%` }}>
              <Bar company={company} side="right" onSelect={() => setSelectedId((id) => (id === company.company_id ? null : company.company_id))} />
              <div className="h-2 flex-1 rounded-r-full bg-bullish" />
            </div>
          ))}
        </div>
      </div>
      {selectedId !== null &&
        (() => {
          const selected = companies.find((c) => c.company_id === selectedId);
          return selected ? <ReasoningPanel company={selected} /> : null;
        })()}
    </div>
  );
}
