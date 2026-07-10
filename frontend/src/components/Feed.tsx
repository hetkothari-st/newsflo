import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { getAlerts, getWatchlist, type Alert, type Watchlist } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useAlertsSocket } from '../lib/useAlertsSocket';
import { alertMatchesMarket, alertMatchesWatchlist } from '../lib/feedFilters';
import AlertCompanies from './AlertCompanies';
import AlertDetail from './AlertDetail';
import CategoryTabs, { type FeedTab } from './CategoryTabs';
import DesktopFeedGrid from './DesktopFeedGrid';
import MobileFeedCarousel from './MobileFeedCarousel';
import WatchlistSettings from './WatchlistSettings';

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

export default function Feed() {
  const { token } = useAuth();
  const [tab, setTab] = useState<FeedTab>('india');
  const [fetched, setFetched] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [watchlist, setWatchlist] = useState<Watchlist>(EMPTY_WATCHLIST);
  const [openAlertId, setOpenAlertId] = useState<number | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  // Ids the user has already been shown. Live pushes not yet in this set are
  // "new" and held back from the rendered list (see design spec: a card
  // arriving mid-scroll must never shift the user's scroll-snap position).
  const [revealedIds, setRevealedIds] = useState<Set<number>>(new Set());
  const { alerts: live, connected } = useAlertsSocket();

  useEffect(() => {
    let active = true;
    setLoading(true);
    getAlerts(token)
      .then((data) => {
        if (active) {
          setFetched(data);
          setRevealedIds(new Set(data.map((a) => a.id)));
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

  const refreshWatchlist = useCallback(() => {
    if (!token) return;
    getWatchlist(token)
      .then(setWatchlist)
      .catch(() => setWatchlist(EMPTY_WATCHLIST));
  }, [token]);

  useEffect(() => {
    if (tab === 'custom' && token) {
      refreshWatchlist();
    }
  }, [tab, token, refreshWatchlist]);

  const alerts = useMemo(() => mergeAlerts(live, fetched), [live, fetched]);

  const newCount = useMemo(
    () => alerts.filter((a) => !revealedIds.has(a.id)).length,
    [alerts, revealedIds],
  );
  const shownAlerts = useMemo(
    () => alerts.filter((a) => revealedIds.has(a.id)),
    [alerts, revealedIds],
  );
  const revealNew = useCallback(() => {
    setRevealedIds(new Set(alerts.map((a) => a.id)));
  }, [alerts]);

  const visibleAlerts = useMemo(() => {
    if (tab === 'india') return shownAlerts.filter((a) => alertMatchesMarket(a, 'IN'));
    if (tab === 'global') return shownAlerts.filter((a) => alertMatchesMarket(a, 'GLOBAL'));
    return shownAlerts.filter((a) => alertMatchesWatchlist(a, watchlist));
  }, [shownAlerts, tab, watchlist]);

  const openAlert = alerts.find((a) => a.id === openAlertId) ?? null;
  const customConfigured = watchlist.categories.length > 0 || watchlist.companies.length > 0;

  let body: ReactNode;
  if (loading) {
    body = <p className="p-4 text-xs uppercase tracking-widest text-muted">Loading…</p>;
  } else if (error) {
    body = <p className="p-4 text-xs uppercase tracking-widest text-bearish">{error}</p>;
  } else if (tab === 'custom' && !token) {
    body = (
      <p className="p-4 text-xs uppercase tracking-widest text-muted">
        Log in to build your custom feed.{' '}
        <Link to="/login" className="text-ink underline">
          Log in
        </Link>
      </p>
    );
  } else if (tab === 'custom' && !customConfigured) {
    body = (
      <p className="p-4 text-xs uppercase tracking-widest text-muted">
        Choose categories or companies to build your custom feed.
      </p>
    );
  } else if (visibleAlerts.length === 0) {
    const emptyMessage =
      tab === 'custom'
        ? 'No alerts match your custom filters yet.'
        : `No ${tab === 'india' ? 'India' : 'Global'} alerts yet. New stories will appear here live.`;
    body = <p className="p-4 text-xs uppercase tracking-widest text-muted">{emptyMessage}</p>;
  } else {
    body = (
      <>
        <MobileFeedCarousel alerts={visibleAlerts} onOpen={setOpenAlertId} />
        <DesktopFeedGrid alerts={visibleAlerts} onOpen={setOpenAlertId} />
      </>
    );
  }

  return (
    // Mobile: a fixed-height column (100dvh minus the 3.5rem slim NavBar and
    // 3.5rem BottomNav, both h-14 -- see NavBar.tsx/BottomNav.tsx) so the
    // carousel's flex-1 child can fill exactly the remaining space. Desktop
    // drops the fixed height entirely and scrolls normally with the page.
    <div className="flex h-[calc(100dvh-7rem)] flex-col overflow-hidden md:h-auto md:overflow-visible">
      <div className="px-4 pt-4 md:mx-auto md:w-full md:max-w-feed md:px-4 md:pt-8">
        <CategoryTabs
          active={tab}
          onChange={setTab}
          connected={connected}
          lastAlertAt={shownAlerts[0]?.created_at ?? null}
          newCount={newCount}
          onRevealNew={revealNew}
          onOpenCustomSettings={() => setSettingsOpen(true)}
        />
      </div>
      <div className="min-h-0 flex-1 md:mx-auto md:w-full md:max-w-feed md:px-4">{body}</div>
      <AlertDetail open={openAlertId !== null} onClose={() => setOpenAlertId(null)}>
        {openAlert && <AlertCompanies alert={openAlert} isAuthenticated={token !== null} />}
      </AlertDetail>
      <AlertDetail open={settingsOpen} onClose={() => setSettingsOpen(false)}>
        <WatchlistSettings
          onSaved={() => {
            refreshWatchlist();
            setSettingsOpen(false);
          }}
        />
      </AlertDetail>
    </div>
  );
}
