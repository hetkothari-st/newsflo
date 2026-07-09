import { useEffect, useMemo, useState } from 'react';
import { getAlerts, type Alert } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useAlertsSocket } from '../lib/useAlertsSocket';
import AlertCard from './AlertCard';

// Prepend live pushes ahead of the fetched list, deduping by id. On an id
// collision the `fetched` copy's data wins: REST-fetched alerts carry the
// accurate per-viewer `in_my_holdings` flag, while live WS-pushed payloads
// always report `in_my_holdings: false` (the pipeline has no per-viewer
// context at broadcast time). Live entries only contribute brand-new ids
// (and their own data) that aren't yet present in `fetched`, so a fresh
// push still appears immediately at the top of the feed.
export function mergeAlerts(live: Alert[], fetched: Alert[]): Alert[] {
  const fetchedById = new Map(fetched.map((alert) => [alert.id, alert]));
  const seen = new Set<number>();
  const merged: Alert[] = [];
  for (const alert of [...live, ...fetched]) {
    if (seen.has(alert.id)) continue;
    seen.add(alert.id);
    merged.push(fetchedById.get(alert.id) ?? alert);
  }
  return merged;
}

export default function Feed() {
  const { token } = useAuth();
  const [fetched, setFetched] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const live = useAlertsSocket();

  useEffect(() => {
    let active = true;
    setLoading(true);
    getAlerts(token)
      .then((data) => {
        if (active) {
          setFetched(data);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : 'Failed to load alerts.');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [token]);

  const alerts = useMemo(() => mergeAlerts(live, fetched), [live, fetched]);

  if (loading) {
    return <p className="text-xs uppercase tracking-widest text-muted">Loading…</p>;
  }
  if (error) {
    return <p className="text-xs uppercase tracking-widest text-bearish">{error}</p>;
  }
  if (alerts.length === 0) {
    return (
      <p className="text-xs uppercase tracking-widest text-muted">
        No alerts yet. New stories will appear here live.
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-5">
      {alerts.map((alert) => (
        <AlertCard key={alert.id} alert={alert} isAuthenticated={token !== null} />
      ))}
    </div>
  );
}
