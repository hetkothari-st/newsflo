import { capTierColorClass } from '../../lib/feedV2Format';
import type { CapTier } from '../../lib/feedV2Api';
import type { Fundamentals as FundamentalsData } from '../../lib/api';
import Fundamentals from '../Fundamentals';

interface BusinessPopupProps {
  ticker: string;
  sector: string;
  capTier: CapTier | null;
  // BSE-sourced classification + ratios, replacing the old LLM-invented
  // business_desc paragraph. Shared with InsightCard/RippleSection via the
  // Fundamentals component so the panels cannot drift.
  fundamentals?: FundamentalsData | null;
}

export default function BusinessPopup({ ticker, sector, capTier, fundamentals }: BusinessPopupProps) {
  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-lg bg-surface p-5">
        <div className="flex items-center gap-2">
          <span className="font-data text-sm text-ink">{ticker}</span>
          <span className="font-sans text-xs uppercase tracking-widest text-muted">{sector}</span>
          {capTier && (
            <span
              className={`rounded-full px-2 py-0.5 font-sans text-[11px] uppercase tracking-widest ${capTierColorClass(capTier)}`}
            >
              {capTier}
            </span>
          )}
        </div>
      </div>
      {/* No fallback text: an unclassified company renders no second panel
          at all -- Fundamentals itself returns null when data is null, and
          this card only wraps it when there's something to show. */}
      {fundamentals && (
        <div className="rounded-lg bg-surface p-5">
          <Fundamentals data={fundamentals} />
        </div>
      )}
    </div>
  );
}
