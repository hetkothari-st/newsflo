import { verdictLabel } from '../../lib/feedV2Format';
import type { FeedV2Alert } from '../../lib/feedV2Api';

interface Level1SummaryV2Props {
  alert: FeedV2Alert;
}

function signedPct(value: number): string {
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(1)}%`;
}

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

export default function Level1SummaryV2({ alert }: Level1SummaryV2Props) {
  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-lg bg-surface p-5">
        <span className="rounded-full bg-elevated px-2 py-0.5 text-[11px] uppercase tracking-widest text-muted">
          {verdictLabel(alert.verdict)}
        </span>
        {alert.summary_long && (
          <p className="mt-3 font-sans text-sm text-ink">{alert.summary_long}</p>
        )}
      </div>

      <div className="rounded-lg bg-surface p-5">
        <div className="flex gap-6">
          <div>
            <div className="font-sans text-xs text-muted">Raw move</div>
            <div
              className={`font-data text-lg font-medium ${
                alert.raw_move_pct >= 0 ? 'text-bullish' : 'text-bearish'
              }`}
            >
              {signedPct(alert.raw_move_pct)}
            </div>
          </div>
          <div>
            <div className="font-sans text-xs text-muted">Sector move</div>
            <div className="font-data text-lg font-medium text-muted">{signedPct(alert.sector_move_pct)}</div>
          </div>
        </div>
        {alert.volume_multiple !== null && (
          <div className="mt-3 font-data text-sm text-ink">
            {alert.volume_multiple.toFixed(1)}× average volume
          </div>
        )}
      </div>

      <div className="rounded-lg bg-surface p-5">
        <div className="font-sans text-xs text-muted">
          {alert.article.source} &middot; {alert.is_fallback_benchmark ? 'vs Nifty 50' : 'vs sector index'}
        </div>
        <time className="mt-1 block font-sans text-xs text-muted" dateTime={alert.created_at}>
          {formatTime(alert.created_at)}
        </time>
      </div>
    </div>
  );
}
