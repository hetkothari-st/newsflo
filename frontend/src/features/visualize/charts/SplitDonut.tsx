import { useState } from 'react';
import type { AlertCompany } from '../../../lib/api';
import ReasoningPanel from '../../../components/ReasoningPanel';
import { rankByMagnitude } from '../transforms';

const RADIUS = 40;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

export default function SplitDonut({ companies }: { companies: AlertCompany[] }) {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const bullish = companies.filter((c) => c.direction === 'bullish');
  const bearish = companies.filter((c) => c.direction === 'bearish');
  const total = bullish.length + bearish.length;

  if (total === 0) return null;

  const bullishFraction = bullish.length / total;
  const bullishDash = bullishFraction * CIRCUMFERENCE;
  const ranked = [...rankByMagnitude(bullish), ...rankByMagnitude(bearish)];

  return (
    <div className="flex flex-col items-center gap-4 p-4">
      <svg viewBox="0 0 100 100" className="h-40 w-40 -rotate-90">
        <circle cx="50" cy="50" r={RADIUS} fill="none" strokeWidth="10" className="stroke-bearish" />
        {bullish.length > 0 && (
          <circle
            cx="50"
            cy="50"
            r={RADIUS}
            fill="none"
            strokeWidth="10"
            strokeLinecap="round"
            className="stroke-bullish"
            strokeDasharray={`${bullishDash} ${CIRCUMFERENCE - bullishDash}`}
          />
        )}
      </svg>
      <p className="text-xs">
        <span className="text-bullish">{bullish.length} Bullish</span>
        <span className="text-muted"> · </span>
        <span className="text-bearish">{bearish.length} Bearish</span>
      </p>
      <div className="flex w-full flex-col gap-1.5">
        {ranked.map((company) => {
          const isBullish = company.direction === 'bullish';
          return (
            <button
              key={company.company_id}
              type="button"
              onClick={() => setSelectedId((id) => (id === company.company_id ? null : company.company_id))}
              className="flex items-center gap-2 rounded-md border border-hairline bg-page px-2 py-1.5 text-left text-xs text-ink"
            >
              <span className={isBullish ? 'text-bullish' : 'text-bearish'} aria-hidden="true">
                {isBullish ? '▲' : '▼'}
              </span>
              {company.ticker}
            </button>
          );
        })}
      </div>
      {selectedId !== null &&
        (() => {
          const selected = companies.find((c) => c.company_id === selectedId);
          return selected ? <ReasoningPanel company={selected} /> : null;
        })()}
    </div>
  );
}
