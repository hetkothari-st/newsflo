import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import AlertRipplePage from './AlertRipplePage';
import * as feedV2Api from '../lib/feedV2Api';
import { AuthProvider } from '../lib/auth';
import type { FeedV2Alert } from '../lib/feedV2Api';

function makeAlert(overrides: Partial<FeedV2Alert> = {}): FeedV2Alert {
  return {
    id: 1,
    category: 'oil_gas',
    created_at: '2026-07-22T10:00:00Z',
    summary_short: 'Oil supply shock lifts refiners',
    summary_long: null,
    article: { id: 1, title: 'Oil surges', url: 'https://example.com/a', source: 'test', published_at: null },
    excess_move_pct: -4.2,
    direction: 'bearish',
    raw_move_pct: -4.8,
    sector_move_pct: -0.6,
    volume_multiple: 3.1,
    benchmark_ticker: '^CNXENERGY',
    is_fallback_benchmark: false,
    peak_ticker: 'RELIANCE.NS',
    peak_company_name: 'Reliance Industries',
    verdict: 'COMPANY_SPECIFIC',
    intensity: { score: 82, band: 'High', components: [] },
    breadth_score: 40,
    in_my_holdings: false,
    ripple: [
      {
        ticker: 'BPCL.NS', name: 'Bharat Petroleum', sector: 'oil_gas', cap_tier: 'LARGE',
        business_desc: 'Refines petroleum.', relationship: 'BENEFICIARY', direction: 'bullish',
        excess_move_pct: 3.0, intensity: { score: 70, band: 'Moderate', components: [] },
        is_exposure_only: false, in_my_holdings: false,
      },
    ],
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/feed-v2/alert/1/ripple']}>
      <AuthProvider>
        <Routes>
          <Route path="/feed-v2/alert/:id/ripple" element={<AlertRipplePage />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe('AlertRipplePage', () => {
  it('renders the ripple companies', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alert').mockResolvedValue(makeAlert());
    renderPage();
    await waitFor(() => expect(screen.getByText('BPCL.NS')).toBeInTheDocument());
    expect(screen.getByText('Beneficiary (1)')).toBeInTheDocument();
  });

  it('renders a door back to Level 1 and forward to the timeline', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alert').mockResolvedValue(makeAlert());
    renderPage();
    await waitFor(() => screen.getByText('BPCL.NS'));
    expect(screen.getByRole('link', { name: /Summary/ })).toHaveAttribute('href', '/feed-v2/alert/1');
    expect(screen.getByRole('link', { name: /See timeline/ })).toHaveAttribute(
      'href', '/feed-v2/alert/1/timeline',
    );
  });

  it('shows "Alert not found" when the fetch fails', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alert').mockRejectedValue(new Error('404'));
    renderPage();
    await waitFor(() => expect(screen.getByText('Alert not found.')).toBeInTheDocument());
  });
});
