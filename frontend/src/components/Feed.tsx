import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { getAlerts, getWatchlist, type Alert, type Watchlist } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useAlertsSocket } from '../lib/useAlertsSocket';
import { alertMatchesMarket, alertMatchesWatchlist } from '../lib/feedFilters';
import AlertCard from './AlertCard';
import WatchlistSettings from './WatchlistSettings';
import type { FeedTab } from './FeedTabs';

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

const EMPTY_WATCHLIST: Watchlist = { categories: [], companies: [] };

export default function Feed({ activeTab }: { activeTab: FeedTab }) {
  const { token } = useAuth();
  const [fetched, setFetched] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [watchlist, setWatchlist] = useState<Watchlist>(EMPTY_WATCHLIST);
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

  // Only fetch the watchlist for the Custom tab, and only when authenticated.
  const refreshWatchlist = useCallback(() => {
    if (!token) return;
    getWatchlist(token)
      .then(setWatchlist)
      .catch(() => setWatchlist(EMPTY_WATCHLIST));
  }, [token]);

  useEffect(() => {
    if (activeTab === 'custom' && token) {
      refreshWatchlist();
    }
  }, [activeTab, token, refreshWatchlist]);

  const alerts = useMemo(() => mergeAlerts(live, fetched), [live, fetched]);

  const visibleAlerts = useMemo(() => {
    if (activeTab === 'india') return alerts.filter((a) => alertMatchesMarket(a, 'IN'));
    if (activeTab === 'global') return alerts.filter((a) => alertMatchesMarket(a, 'GLOBAL'));
    return alerts.filter((a) => alertMatchesWatchlist(a, watchlist));
  }, [alerts, activeTab, watchlist]);

  if (loading) {
    return <p className="text-xs uppercase tracking-widest text-muted">Loading…</p>;
  }
  if (error) {
    return <p className="text-xs uppercase tracking-widest text-bearish">{error}</p>;
  }

  const cardList = (
    <div className="flex flex-col gap-5">
      {visibleAlerts.map((alert) => (
        <AlertCard key={alert.id} alert={alert} isAuthenticated={token !== null} />
      ))}
    </div>
  );

  if (activeTab === 'custom') {
    if (!token) {
      return (
        <p className="text-xs uppercase tracking-widest text-muted">
          Log in to build your custom feed.{' '}
          <Link to="/login" className="text-ink underline">
            Log in
          </Link>
        </p>
      );
    }
    const configured = watchlist.categories.length > 0 || watchlist.companies.length > 0;
    return (
      <div className="flex flex-col gap-6">
        <WatchlistSettings onSaved={refreshWatchlist} />
        {!configured ? (
          <p className="text-xs uppercase tracking-widest text-muted">
            Choose categories or companies above to build your custom feed.
          </p>
        ) : visibleAlerts.length === 0 ? (
          <p className="text-xs uppercase tracking-widest text-muted">
            No alerts match your custom filters yet.
          </p>
        ) : (
          cardList
        )}
      </div>
    );
  }

  if (visibleAlerts.length === 0) {
    return (
      <p className="text-xs uppercase tracking-widest text-muted">
        No {activeTab === 'india' ? 'India' : 'Global'} alerts yet. New stories will appear here live.
      </p>
    );
  }
  return cardList;
}
