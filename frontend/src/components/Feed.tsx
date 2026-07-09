import { useEffect, useMemo, useState } from 'react';
import { getAlerts, type Alert } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useAlertsSocket } from '../lib/useAlertsSocket';
import AlertCard from './AlertCard';

// Prepend live pushes ahead of the fetched list, deduping by id (a live entry
// for an id already present wins, since it is iterated first).
export function mergeAlerts(live: Alert[], fetched: Alert[]): Alert[] {
  const seen = new Set<number>();
  const merged: Alert[] = [];
  for (const alert of [...live, ...fetched]) {
    if (seen.has(alert.id)) continue;
    seen.add(alert.id);
    merged.push(alert);
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
