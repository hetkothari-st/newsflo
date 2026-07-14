import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { getAlerts, getWatchlist, type Alert, type Watchlist } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useLanguage } from '../lib/language';
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

function normalizeTitle(title: string): string {
  return title.trim().toLowerCase().replace(/\s+/g, ' ');
}

// RSS sources frequently republish the identical wire story under a new
// URL. The backend has its own republish-dedup (reuses one analysis instead
// of re-running the LLM) but it doesn't catch every case, so distinct Alert
// rows for the same story can still reach the client. Collapsing them here
// by normalized title is the last line of defense against a feed showing
// the same headline/photo twice -- keep the newest (`alerts` is already
// newest-first).
export function dedupeByTitle(alerts: Alert[]): Alert[] {
  const seen = new Set<string>();
  const result: Alert[] = [];
  for (const alert of alerts) {
    const key = normalizeTitle(alert.article.title);
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(alert);
  }
  return result;
}

const EMPTY_WATCHLIST: Watchlist = { categories: [], companies: [] };

export default function Feed() {
  const { token } = useAuth();
  const { language, t, translating } = useLanguage();
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
  const carouselRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    getAlerts(token, language)
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
  }, [token, language]);

  // The on-demand translation drain finishes some time after the fetch
  // above already ran (it just triggered the drain and moved on) -- without
  // this, newly-translated content only ever shows up after a manual page
  // reload. Refetches silently (no loading spinner, no revealedIds reset)
  // so already-visible cards just update their text in place. Keyed on the
  // true->false transition specifically, via the ref below, so this never
  // fires on mount (translating starts false) or on the switch itself
  // (translating starts true) -- only once the drain actually completes.
  const wasTranslating = useRef(translating);
  useEffect(() => {
    const justFinished = wasTranslating.current && !translating;
    wasTranslating.current = translating;
    if (!justFinished) return;

    let active = true;
    getAlerts(token, language)
      .then((data) => {
        if (active) setFetched(data);
      })
      .catch(() => {
        // Best-effort refresh -- the existing feed content stays as-is if
        // this fails, no need to surface a separate error for it.
      });
    return () => {
      active = false;
    };
  }, [translating, token, language]);

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

  const alerts = useMemo(() => dedupeByTitle(mergeAlerts(live, fetched)), [live, fetched]);

  // "New" and "visible" are both scoped to the ACTIVE tab -- otherwise a live
  // push on a tab the user isn't viewing would light up "N new" with nothing
  // to actually reveal there (whole-branch review finding).
  const tabAlerts = useMemo(() => {
    if (tab === 'india') return alerts.filter((a) => alertMatchesMarket(a, 'IN'));
    if (tab === 'global') return alerts.filter((a) => alertMatchesMarket(a, 'GLOBAL'));
    return alerts.filter((a) => alertMatchesWatchlist(a, watchlist));
  }, [alerts, tab, watchlist]);

  const newCount = useMemo(
    () => tabAlerts.filter((a) => !revealedIds.has(a.id)).length,
    [tabAlerts, revealedIds],
  );
  const visibleAlerts = useMemo(
    () => tabAlerts.filter((a) => revealedIds.has(a.id)),
    [tabAlerts, revealedIds],
  );
  const revealNew = useCallback(() => {
    setRevealedIds((prev) => {
      const next = new Set(prev);
      tabAlerts.forEach((a) => next.add(a.id));
      return next;
    });
    carouselRef.current?.scrollTo({ top: 0 });
    window.scrollTo({ top: 0 });
  }, [tabAlerts]);

  // Switching tabs silently reveals whatever's already queued for the tab
  // being switched to (a push that arrived while on a *different* tab
  // shouldn't require an extra "N new" tap once the user actually navigates
  // there). MobileFeedCarousel is NOT remounted on tab change (same DOM node,
  // new content), so there's no free "fresh scroll position" here -- reset
  // it explicitly, same as revealNew, or a revisit to a tab with residual
  // scroll offset would silently shift content under the user, reproducing
  // the exact bug this queueing exists to prevent. Deliberately keyed on
  // `tab` alone: a live push arriving while the tab stays active must still
  // queue behind "N new" instead of auto-revealing.
  useEffect(() => {
    setRevealedIds((prev) => {
      const next = new Set(prev);
      let changed = false;
      tabAlerts.forEach((a) => {
        if (!next.has(a.id)) {
          next.add(a.id);
          changed = true;
        }
      });
      return changed ? next : prev;
    });
    carouselRef.current?.scrollTo({ top: 0 });
    window.scrollTo({ top: 0 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  const openAlert = alerts.find((a) => a.id === openAlertId) ?? null;
  const customConfigured = watchlist.categories.length > 0 || watchlist.companies.length > 0;

  let body: ReactNode;
  if (loading) {
    body = <p className="p-4 text-xs uppercase tracking-widest text-muted">{t('feed.loading')}</p>;
  } else if (error) {
    body = <p className="p-4 text-xs uppercase tracking-widest text-bearish">{error}</p>;
  } else if (tab === 'custom' && !token) {
    body = (
      <p className="p-4 text-xs uppercase tracking-widest text-muted">
        {t('feed.loginPrompt')}{' '}
        <Link to="/login" className="text-ink underline">
          {t('feed.loginLink')}
        </Link>
      </p>
    );
  } else if (tab === 'custom' && !customConfigured) {
    body = (
      <p className="p-4 text-xs uppercase tracking-widest text-muted">
        {t('feed.customEmpty')}
      </p>
    );
  } else if (visibleAlerts.length === 0) {
    const emptyMessage =
      tab === 'custom'
        ? t('feed.customNoMatch')
        : t(tab === 'india' ? 'feed.emptyIndia' : 'feed.emptyGlobal');
    body = <p className="p-4 text-xs uppercase tracking-widest text-muted">{emptyMessage}</p>;
  } else {
    body = (
      <>
        <MobileFeedCarousel
          ref={carouselRef}
          alerts={visibleAlerts}
          onOpen={setOpenAlertId}
          openAlertId={openAlertId}
          onClose={() => setOpenAlertId(null)}
          isAuthenticated={token !== null}
        />
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
      <div className="px-4 md:mx-auto md:w-full md:max-w-6xl md:px-8 md:pt-8">
        <CategoryTabs
          active={tab}
          onChange={setTab}
          connected={connected}
          newCount={newCount}
          onRevealNew={revealNew}
          onOpenCustomSettings={() => setSettingsOpen(true)}
        />
      </div>
      <div className="min-h-0 flex-1 md:mx-auto md:w-full md:max-w-6xl md:px-8">{body}</div>
      <AlertDetail open={openAlertId !== null} onClose={() => setOpenAlertId(null)} hiddenOnMobile>
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
