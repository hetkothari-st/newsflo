import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
import Feed, { mergeAlerts } from './Feed';
import { AuthProvider } from '../lib/auth';
import * as api from '../lib/api';
import type { Alert, AlertCompany } from '../lib/api';

// Isolate Feed from the real socket in these tests.
vi.mock('../lib/useAlertsSocket', () => ({ useAlertsSocket: () => ({ alerts: [], connected: true }) }));

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

function makeAlert(id: number, title: string, companies: AlertCompany[], category = 'oil_energy'): Alert {
  return {
    id,
    category,
    created_at: '2026-07-10T10:00:00+00:00',
    article: { id, title, url: `https://example.com/${id}`, image_url: null },
    companies,
  };
}

function renderFeed(ui: ReactElement) {
  return render(
    <MemoryRouter>
      <AuthProvider>{ui}</AuthProvider>
    </MemoryRouter>,
  );
}

function setToken() {
  localStorage.setItem('newsflo.token', 'tok');
  localStorage.setItem('newsflo.email', 'a@example.com');
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('mergeAlerts', () => {
  it('prepends live alerts and dedupes by id (fetched data wins on collision)', () => {
    const merged = mergeAlerts([makeAlert(2, 'two-live', [])], [makeAlert(1, 'one', []), makeAlert(2, 'two', [])]);
    expect(merged.map((a) => a.id)).toEqual([2, 1]);
    expect(merged[0].article.title).toBe('two');
  });
});

describe('Feed tabs', () => {
  const indiaAlert = makeAlert(1, 'India oil headline', [company({ market: 'IN' })]);
  const globalAlert = makeAlert(2, 'Global tech headline', [
    company({ company_id: 2, ticker: 'AAPL', name: 'Apple', market: 'GLOBAL' }),
  ], 'it');

  it('India tab shows only IN-market alerts', async () => {
    vi.spyOn(api, 'getAlerts').mockResolvedValue([indiaAlert, globalAlert]);
    renderFeed(<Feed activeTab="india" />);
    expect(await screen.findByText('India oil headline')).toBeInTheDocument();
    expect(screen.queryByText('Global tech headline')).not.toBeInTheDocument();
  });

  it('Global tab shows only GLOBAL-market alerts', async () => {
    vi.spyOn(api, 'getAlerts').mockResolvedValue([indiaAlert, globalAlert]);
    renderFeed(<Feed activeTab="global" />);
    expect(await screen.findByText('Global tech headline')).toBeInTheDocument();
    expect(screen.queryByText('India oil headline')).not.toBeInTheDocument();
  });

  it('Custom tab shows a login prompt when logged out', async () => {
    vi.spyOn(api, 'getAlerts').mockResolvedValue([indiaAlert]);
    renderFeed(<Feed activeTab="custom" />);
    expect(await screen.findByText(/log in to build your custom feed/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /log in/i })).toBeInTheDocument();
  });

  it('Custom tab shows a configure prompt when logged in with an empty watchlist', async () => {
    setToken();
    vi.spyOn(api, 'getAlerts').mockResolvedValue([indiaAlert]);
    vi.spyOn(api, 'getWatchlist').mockResolvedValue({ categories: [], companies: [] });
    vi.spyOn(api, 'getCategories').mockResolvedValue([]);
    vi.spyOn(api, 'getCompanies').mockResolvedValue([]);
    renderFeed(<Feed activeTab="custom" />);
    expect(await screen.findByText(/choose categories or companies/i)).toBeInTheDocument();
    // The inline editor is present on the Custom tab.
    expect(screen.getByRole('button', { name: /save/i })).toBeInTheDocument();
  });

  it('Custom tab shows watchlist-matched alerts when configured', async () => {
    setToken();
    vi.spyOn(api, 'getAlerts').mockResolvedValue([indiaAlert, globalAlert]);
    vi.spyOn(api, 'getWatchlist').mockResolvedValue({ categories: ['oil_energy'], companies: [] });
    vi.spyOn(api, 'getCategories').mockResolvedValue(['oil_energy']);
    vi.spyOn(api, 'getCompanies').mockResolvedValue([]);
    renderFeed(<Feed activeTab="custom" />);
    await waitFor(() => expect(screen.getByText('India oil headline')).toBeInTheDocument());
    expect(screen.queryByText('Global tech headline')).not.toBeInTheDocument();
  });
});
