import { useEffect, useState } from 'react';

export function formatAgo(iso: string, nowMs: number): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return '';
  const diffSec = Math.max(0, Math.floor((nowMs - t) / 1000));
  if (diffSec < 5) return 'just now';
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}d ago`;
}

export default function LiveStatus({
  connected,
  lastAlertAt,
}: {
  connected: boolean;
  lastAlertAt: string | null;
}) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="mb-4 flex items-center gap-2 text-xs uppercase tracking-widest">
      <span className="relative flex h-2 w-2">
        {connected && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-bullish opacity-75 motion-reduce:hidden" />
        )}
        <span className={`relative inline-flex h-2 w-2 rounded-full ${connected ? 'bg-bullish' : 'bg-muted'}`} />
      </span>
      <span className={connected ? 'text-ink' : 'text-muted'}>{connected ? 'Live' : 'Reconnecting'}</span>
      {lastAlertAt && (
        <>
          <span className="text-muted" aria-hidden="true">
            ·
          </span>
          <span className="text-muted">{formatAgo(lastAlertAt, now)}</span>
        </>
      )}
    </div>
  );
}
