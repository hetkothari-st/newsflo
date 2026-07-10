import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import FeedPage from './FeedPage';
import { AuthProvider } from '../lib/auth';
import * as api from '../lib/api';
import type { Alert, AlertCompany } from '../lib/api';

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

function makeAlert(id: number, title: string, companies: AlertCompany[]): Alert {
  return {
    id,
    category: 'oil_energy',
    created_at: '2026-07-10T10:00:00+00:00',
    article: { id, title, url: `https://example.com/${id}`, image_url: null },
    companies,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('FeedPage', () => {
  it('defaults to the India tab and switches to Global on click', async () => {
    const indiaAlert = makeAlert(1, 'India oil headline', [company({ market: 'IN' })]);
    const globalAlert = makeAlert(2, 'Global tech headline', [
      company({ company_id: 2, ticker: 'AAPL', name: 'Apple', market: 'GLOBAL' }),
    ]);
    vi.spyOn(api, 'getAlerts').mockResolvedValue([indiaAlert, globalAlert]);

    render(
      <MemoryRouter>
        <AuthProvider>
          <FeedPage />
        </AuthProvider>
      </MemoryRouter>,
    );

    // India tab is active by default.
    expect(await screen.findByText('India oil headline')).toBeInTheDocument();
    expect(screen.queryByText('Global tech headline')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('tab', { name: /global/i }));
    expect(await screen.findByText('Global tech headline')).toBeInTheDocument();
    expect(screen.queryByText('India oil headline')).not.toBeInTheDocument();
  });
});
