/* 5-second poll of /directory/live-caps for the Directory ranking.
   Best-effort: a failed poll keeps the previous snapshot (rows fall back
   to whatever ordering data they already have); each successful poll
   REPLACES the map wholesale so a ticker that went stale server-side
   drops back to its stored cap on the next render. */
import { useEffect, useState } from 'react';
import { getDirectoryLiveCaps, type CapSource } from './directoryLiveCaps';

const POLL_INTERVAL_MS = 5000;

export interface LiveCapEntry {
  rank: number;
  marketCap: number;
  source: CapSource;
}

export function useDirectoryLiveCaps(): Map<string, LiveCapEntry> {
  const [caps, setCaps] = useState<Map<string, LiveCapEntry>>(() => new Map());

  useEffect(() => {
    let active = true;
    const poll = () => {
      getDirectoryLiveCaps()
        .then((rows) => {
          if (!active) return;
          const next = new Map<string, LiveCapEntry>();
          for (const row of rows) {
            next.set(row.ticker, {
              rank: row.rank,
              marketCap: row.market_cap,
              source: row.cap_source,
            });
          }
          setCaps(next);
        })
        .catch(() => {
          /* overlay is best-effort; the last snapshot stays */
        });
    };
    poll();
    const id = window.setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      active = false;
      window.clearInterval(id);
    };
  }, []);

  return caps;
}
