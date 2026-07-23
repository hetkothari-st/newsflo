import { useNavigate } from 'react-router-dom';
import { capTierColorClass, formatExcess, intensityBandColorClass } from '../../lib/feedV2Format';
import type { CapTier, Intensity } from '../../lib/feedV2Api';

interface PeerRowProps {
  ticker: string;
  capTier: CapTier | null;
  direction: 'bullish' | 'bearish';
  excessMovePct: number | null;
  intensity: Intensity | null;
  isExposureOnly: boolean;
  inMyHoldings: boolean;
  alertId?: number;
  onOpenBusinessPopup: () => void;
}

export default function PeerRow({
  ticker,
  capTier,
  direction,
  excessMovePct,
  intensity,
  isExposureOnly,
  inMyHoldings,
  alertId,
  onOpenBusinessPopup,
}: PeerRowProps) {
  const navigate = useNavigate();

  function goToDeepDive() {
    const query = alertId !== undefined ? `?alertId=${alertId}` : '';
    navigate(`/feed-v2/stock/${ticker}${query}`);
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={goToDeepDive}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') goToDeepDive();
      }}
      aria-label={ticker}
      className="flex cursor-pointer items-center gap-3 py-1.5"
    >
      <span className="font-data text-[11px] text-muted">{ticker}</span>
      {capTier && (
        <span
          className={`rounded-full px-2 py-0.5 font-sans text-[10px] uppercase tracking-widest ${capTierColorClass(capTier)}`}
        >
          {capTier}
        </span>
      )}
      {inMyHoldings && (
        <span data-testid="peer-row-owned-dot" className="h-[7px] w-[7px] shrink-0 rounded-full bg-accent" />
      )}
      {isExposureOnly ? (
        <span className="font-sans text-xs text-muted">Exposure</span>
      ) : (
        <>
          <span className={`font-data text-xs ${direction === 'bullish' ? 'text-bullish' : 'text-bearish'}`}>
            {formatExcess(excessMovePct as number).text}
          </span>
          {intensity && (
            <>
              <span className="h-1 w-full max-w-[80px] rounded-sm bg-elevated">
                <span
                  className={`block h-full rounded-sm ${intensityBandColorClass(intensity.band)}`}
                  style={{ width: `${intensity.score}%` }}
                />
              </span>
              <span className="font-data text-[11px] text-muted">{intensity.score}</span>
            </>
          )}
        </>
      )}
      <button
        type="button"
        aria-label="View business details"
        onClick={(e) => {
          e.stopPropagation();
          onOpenBusinessPopup();
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') e.stopPropagation();
        }}
        className="ml-auto flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] text-muted"
      >
        i
      </button>
      <span className="shrink-0 text-muted" aria-hidden="true">
        ›
      </span>
    </div>
  );
}
