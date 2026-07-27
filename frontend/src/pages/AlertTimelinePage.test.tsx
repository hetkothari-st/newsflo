import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import AlertTimelinePage from './AlertTimelinePage';
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
    timeline: [{ horizon: 'TODAY', description: 'Markets react immediately to the supply shock.' }],
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/feed-v2/alert/1/timeline']}>
      <AuthProvider>
        <Routes>
          <Route path="/feed-v2/alert/:id/timeline" element={<AlertTimelinePage />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe('AlertTimelinePage', () => {
  it('renders the timeline entries', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alert').mockResolvedValue(makeAlert());
    renderPage();
    await waitFor(() =>
      expect(screen.getByText('Markets react immediately to the supply shock.')).toBeInTheDocument(),
    );
    expect(screen.getByText('Today')).toBeInTheDocument();
  });

  it('renders a door back to the ripple level', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alert').mockResolvedValue(makeAlert());
    renderPage();
    await waitFor(() => screen.getByText('Today'));
    expect(screen.getByRole('link', { name: /Ripple/ })).toHaveAttribute('href', '/feed-v2/alert/1/ripple');
  });

  it('shows "Alert not found" when the fetch fails', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alert').mockRejectedValue(new Error('404'));
    renderPage();
    await waitFor(() => expect(screen.getByText('Alert not found.')).toBeInTheDocument());
  });
});
