import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Feed, { mergeAlerts } from './Feed';
import { AuthProvider } from '../lib/auth';
import * as api from '../lib/api';
import type { Alert, AlertCompany } from '../lib/api';

// Isolate Feed from the real socket in these tests.
vi.mock('../lib/useAlertsSocket', () => ({ useAlertsSocket: () => [] }));

function makeAlert(id: number, title: string, companies: AlertCompany[] = []): Alert {
  return {
    id,
    category: 'oil_energy',
    created_at: '2026-07-09T10:00:00+00:00',
    article: { id, title, url: `https://example.com/${id}` },
    companies,
  };
}

function makeCompany(inMyHoldings: boolean): AlertCompany {
  return {
    company_id: 1,
    ticker: 'ACME',
    name: 'Acme Corp',
    index_tier: 'NIFTY50',
    direction: 'bullish',
    magnitude_low: 1,
    magnitude_high: 3,
    rationale: 'test',
    basis: 'direct_mention',
    confidence: 'llm_estimate',
    in_my_holdings: inMyHoldings,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('mergeAlerts', () => {
  it('prepends a brand-new live alert ahead of the fetched list', () => {
    const merged = mergeAlerts([makeAlert(3, 'three-live')], [makeAlert(1, 'one')]);
    expect(merged.map((a) => a.id)).toEqual([3, 1]);
    expect(merged[0].article.title).toBe('three-live');
  });

  it('dedupes by id, keeping the live entry position but the fetched data', () => {
    const merged = mergeAlerts([makeAlert(2, 'two-live')], [makeAlert(1, 'one'), makeAlert(2, 'two')]);
    expect(merged.map((a) => a.id)).toEqual([2, 1]);
    // Fetched data wins on overlap, even though the live copy determined position.
    expect(merged[0].article.title).toBe('two');
  });

  it('prefers the fetched copy of an overlapping alert for accurate in_my_holdings', () => {
    const live = [makeAlert(5, 'five', [makeCompany(false)])];
    const fetched = [makeAlert(5, 'five', [makeCompany(true)])];
    const merged = mergeAlerts(live, fetched);
    expect(merged).toHaveLength(1);
    expect(merged[0].companies[0].in_my_holdings).toBe(true);
  });
});

describe('Feed', () => {
  it('renders alert cards from the initial fetch', async () => {
    vi.spyOn(api, 'getAlerts').mockResolvedValue([makeAlert(1, 'Oil news headline')]);
    render(
      <AuthProvider>
        <Feed />
      </AuthProvider>,
    );
    expect(await screen.findByText('Oil news headline')).toBeInTheDocument();
  });

  it('shows an empty state when there are no alerts', async () => {
    vi.spyOn(api, 'getAlerts').mockResolvedValue([]);
    render(
      <AuthProvider>
        <Feed />
      </AuthProvider>,
    );
    expect(await screen.findByText(/no alerts yet/i)).toBeInTheDocument();
  });
});
