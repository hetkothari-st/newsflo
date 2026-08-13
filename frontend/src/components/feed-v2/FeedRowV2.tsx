import { useState } from 'react';
import { formatExcess, intensityBandColorClass, verdictLabel } from '../../lib/feedV2Format';
import type { FeedV2Alert } from '../../lib/feedV2Api';
import AlertCover from '../AlertCover';
import AlertDetail from '../AlertDetail';
import CategorySwatch from '../CategorySwatch';
import IntensityBreakdownPopup from './IntensityBreakdownPopup';

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

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
        className="cursor-pointer overflow-hidden rounded-lg bg-surface p-3 theme-light:shadow-neu"
      >
        <div className="relative h-40 w-full overflow-hidden rounded-md">
          <AlertCover imageUrl={alert.article.image_url} category={alert.category} />
          <div className="absolute inset-x-0 top-0 flex items-center justify-between p-3">
            <span className="inline-flex items-center rounded-full bg-page/85 px-2.5 py-1 backdrop-blur-sm">
              <CategorySwatch category={alert.category} active />
            </span>
            <time className="rounded-full bg-page/85 px-2.5 py-1 text-xs uppercase tracking-widest text-ink backdrop-blur-sm">
              {formatTime(alert.created_at)}
            </time>
          </div>
        </div>

        <h2 className="mt-3 line-clamp-2 font-sans text-lg font-semibold leading-snug text-ink">
          {alert.article.title}
        </h2>

        <div className="mt-2 flex items-center gap-3">
          <span
            className={`shrink-0 font-data text-[17px] font-medium ${
              alert.direction === 'positive'
                ? 'text-bullish'
                : alert.direction === 'negative'
                  ? 'text-bearish'
                  : 'text-muted'
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

        <div className="mt-2 flex items-center gap-2">
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
