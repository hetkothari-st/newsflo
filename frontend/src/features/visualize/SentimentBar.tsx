import type { AlertCompany } from '../../lib/api';

export default function SentimentBar({ companies }: { companies: AlertCompany[] }) {
  const bullish = companies.filter((c) => c.direction === 'bullish').length;
  const bearish = companies.filter((c) => c.direction === 'bearish').length;
  const total = bullish + bearish;

  if (total === 0) return null;

  const bullishPct = (bullish / total) * 100;
  const bearishPct = (bearish / total) * 100;

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex h-2 overflow-hidden rounded-full bg-hairline">
        {bullish > 0 && (
          <div
            className={`bg-bullish ${bearish > 0 ? 'border-r-2 border-page' : ''}`}
            style={{ width: `${bullishPct}%` }}
          />
        )}
        {bearish > 0 && <div className="bg-bearish" style={{ width: `${bearishPct}%` }} />}
      </div>
      <p className="text-xs">
        <span className="text-bullish">{bullish} Bullish</span>
        <span className="text-muted"> · </span>
        <span className="text-bearish">{bearish} Bearish</span>
      </p>
    </div>
  );
}
