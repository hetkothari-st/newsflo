import type { Alert, Watchlist } from './api';

export type Market = 'IN' | 'GLOBAL';

// An alert belongs to a market tab if ANY of its companies is in that market.
// A zero-company alert matches NEITHER tab (correct: neither India nor Global
// claims it, per the feature design — there is no unfiltered "all" tab).
export function alertMatchesMarket(alert: Alert, market: Market): boolean {
  return alert.companies.some((c) => c.market === market);
}

// The Custom tab shows an alert if its category is watchlisted OR any of its
// companies is watchlisted (OR, not AND — two independent filter facets). An
// EMPTY watchlist matches nothing: an unconfigured custom filter must never
// silently show the whole feed.
export function alertMatchesWatchlist(alert: Alert, watchlist: Watchlist): boolean {
  if (watchlist.categories.length === 0 && watchlist.companies.length === 0) {
    return false;
  }
  if (watchlist.categories.includes(alert.category)) {
    return true;
  }
  return alert.companies.some((c) =>
    watchlist.companies.some((w) => w.company_id === c.company_id),
  );
}
