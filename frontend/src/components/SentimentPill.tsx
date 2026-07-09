import type { AlertCompany } from '../lib/api';

export type Sentiment = 'bullish' | 'bearish' | 'mixed';

// Majority (>50%) of the visible companies decides the pill. An exact tie —
// including the empty (zero-company) case — is Mixed.
export function netSentiment(companies: Pick<AlertCompany, 'direction'>[]): Sentiment {
  const total = companies.length;
  const bullish = companies.filter((c) => c.direction === 'bullish').length;
  const bearish = companies.filter((c) => c.direction === 'bearish').length;
  if (bullish > total / 2) return 'bullish';
  if (bearish > total / 2) return 'bearish';
  return 'mixed';
}

const PILL: Record<Sentiment, { label: string; className: string }> = {
  bullish: { label: 'Net Bullish', className: 'border-bullish text-bullish' },
  bearish: { label: 'Net Bearish', className: 'border-bearish text-bearish' },
  mixed: { label: 'Mixed', className: 'border-muted text-muted' },
};

export default function SentimentPill({
  companies,
}: {
  companies: Pick<AlertCompany, 'direction'>[];
}) {
  const { label, className } = PILL[netSentiment(companies)];
  return (
    <span
      className={`inline-flex items-center rounded-full border-[1.5px] bg-transparent px-3 py-1 text-xs uppercase tracking-widest ${className}`}
    >
      {label}
    </span>
  );
}
