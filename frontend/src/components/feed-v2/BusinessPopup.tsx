import { capTierColorClass } from '../../lib/feedV2Format';
import type { CapTier } from '../../lib/feedV2Api';

interface BusinessPopupProps {
  ticker: string;
  sector: string;
  capTier: CapTier | null;
  businessDesc: string | null;
}

export default function BusinessPopup({ ticker, sector, capTier, businessDesc }: BusinessPopupProps) {
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
      <div className="rounded-lg bg-surface p-5">
        <p className="font-sans text-sm text-ink">
          {businessDesc ?? 'Business description not available.'}
        </p>
      </div>
    </div>
  );
}
