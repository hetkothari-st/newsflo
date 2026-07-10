import { describe, expect, it } from 'vitest';
import { alertMatchesMarket, alertMatchesWatchlist } from './feedFilters';
import type { Alert, AlertCompany, Watchlist } from './api';

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1,
    ticker: 'RELIANCE.NS',
    name: 'Reliance',
    index_tier: 'NIFTY50',
    direction: 'bullish',
    magnitude_low: 1,
    magnitude_high: 2,
    rationale: 'x',
    key_points: [],
    basis: 'direct_mention',
    confidence: 'llm_estimate',
    market: 'IN',
    in_my_holdings: false,
    ...overrides,
  };
}

function alert(overrides: Partial<Alert>): Alert {
  return {
    id: 1,
    category: 'oil_energy',
    created_at: '2026-07-10T10:00:00+00:00',
    article: { id: 1, title: 't', url: 'https://example.com/1', image_url: null },
    companies: [],
    ...overrides,
  };
}

describe('alertMatchesMarket', () => {
  it('an alert with only .NS companies matches India, not Global', () => {
    const a = alert({ companies: [company({ market: 'IN' })] });
    expect(alertMatchesMarket(a, 'IN')).toBe(true);
    expect(alertMatchesMarket(a, 'GLOBAL')).toBe(false);
  });

  it('an alert with only non-.NS companies matches Global, not India', () => {
    const a = alert({ companies: [company({ company_id: 2, ticker: 'AAPL', market: 'GLOBAL' })] });
    expect(alertMatchesMarket(a, 'GLOBAL')).toBe(true);
    expect(alertMatchesMarket(a, 'IN')).toBe(false);
  });

  it('an alert with companies from BOTH markets matches both', () => {
    const a = alert({
      companies: [company({ market: 'IN' }), company({ company_id: 2, ticker: 'AAPL', market: 'GLOBAL' })],
    });
    expect(alertMatchesMarket(a, 'IN')).toBe(true);
    expect(alertMatchesMarket(a, 'GLOBAL')).toBe(true);
  });

  it('an alert with ZERO companies matches neither market', () => {
    const a = alert({ companies: [] });
    expect(alertMatchesMarket(a, 'IN')).toBe(false);
    expect(alertMatchesMarket(a, 'GLOBAL')).toBe(false);
  });
});

describe('alertMatchesWatchlist', () => {
  const watchlist: Watchlist = {
    categories: ['oil_energy'],
    companies: [{ company_id: 5, ticker: 'AAPL', name: 'Apple' }],
  };

  it('matches on category alone', () => {
    const a = alert({ category: 'oil_energy', companies: [] });
    expect(alertMatchesWatchlist(a, watchlist)).toBe(true);
  });

  it('matches on company alone', () => {
    const a = alert({ category: 'banking', companies: [company({ company_id: 5 })] });
    expect(alertMatchesWatchlist(a, watchlist)).toBe(true);
  });

  it('matches when BOTH category and company match (still true)', () => {
    const a = alert({ category: 'oil_energy', companies: [company({ company_id: 5 })] });
    expect(alertMatchesWatchlist(a, watchlist)).toBe(true);
  });

  it('does not match when neither category nor company match', () => {
    const a = alert({ category: 'banking', companies: [company({ company_id: 99 })] });
    expect(alertMatchesWatchlist(a, watchlist)).toBe(false);
  });

  it('an empty watchlist matches NOTHING (never show-all)', () => {
    const empty: Watchlist = { categories: [], companies: [] };
    const a = alert({ category: 'oil_energy', companies: [company({ company_id: 5 })] });
    expect(alertMatchesWatchlist(a, empty)).toBe(false);
  });
});
