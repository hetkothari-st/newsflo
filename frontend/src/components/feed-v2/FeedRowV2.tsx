import { useState } from 'react';
import { formatExcess, intensityBandColorClass, verdictLabel } from '../../lib/feedV2Format';
import type { FeedV2Alert } from '../../lib/feedV2Api';
import AlertDetail from '../AlertDetail';
import IntensityBreakdownPopup from './IntensityBreakdownPopup';

interface FeedRowV2Props {
  alert: FeedV2Alert;
  onOpen: () => void;
}

export default function FeedRowV2({ alert, onOpen }: FeedRowV2Props) {
  const { text: excessText } = formatExcess(alert.excess_move_pct);
  const isMuted = alert.verdict === 'SECTOR_WIDE';
  const [breakdownOpen, setBreakdownOpen] = useState(false);

  return (
    <>
      <div
        role="button"
        tabIndex={0}
        onClick={onOpen}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') onOpen();
        }}
        className="cursor-pointer border-b border-hairline py-[14px] last:border-b-0"
      >
        <div className="flex items-center gap-3">
          <span
            className={`min-w-[74px] shrink-0 font-data text-[19px] font-medium ${
              alert.direction === 'bullish' ? 'text-bullish' : 'text-bearish'
            }`}
          >
            {excessText}
          </span>
          <span className={`flex-1 truncate font-sans text-sm ${isMuted ? 'text-muted' : 'text-ink'}`}>
            {alert.summary_short}
          </span>
          {alert.in_my_holdings && (
            <span data-testid="owned-dot" className="h-[7px] w-[7px] shrink-0 rounded-full bg-accent" />
          )}
        </div>
        <div className="ml-[84px] flex items-center gap-2">
          <span className="rounded-full bg-elevated px-2 py-0.5 text-[11px] uppercase tracking-widest text-muted">
            {verdictLabel(alert.verdict)}
          </span>
          <span className="font-data text-[11px] text-muted">{alert.peak_ticker}</span>
          <button
            type="button"
            data-testid="intensity-tap-target"
            onClick={(e) => {
              e.stopPropagation();
              setBreakdownOpen(true);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') e.stopPropagation();
            }}
            className="flex items-center gap-2"
            aria-label="View intensity breakdown"
          >
            <span className="h-1 w-full max-w-[130px] rounded-sm bg-elevated">
              <span
                className={`block h-full rounded-sm ${intensityBandColorClass(alert.intensity.band)}`}
                style={{ width: `${alert.intensity.score}%` }}
              />
            </span>
            <span className="font-data text-[11px] text-muted">{alert.intensity.score}</span>
          </button>
        </div>
      </div>
      <AlertDetail open={breakdownOpen} onClose={() => setBreakdownOpen(false)}>
        <IntensityBreakdownPopup intensity={alert.intensity} />
      </AlertDetail>
    </>
  );
}
