import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import AlertLevel1Page from './AlertLevel1Page';
import * as feedV2Api from '../lib/feedV2Api';
import { AuthProvider } from '../lib/auth';
import type { FeedV2Alert } from '../lib/feedV2Api';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

function makeAlert(overrides: Partial<FeedV2Alert> = {}): FeedV2Alert {
  return {
    id: 1,
    category: 'oil_gas',
    created_at: '2026-07-22T10:00:00Z',
    summary_short: 'Oil supply shock lifts refiners',
    summary_long: 'Crude prices jumped on a supply disruption. Refiners face wider margin pressure.',
    article: { id: 1, title: 'Oil surges', url: 'https://example.com/a', source: 'Economic Times', published_at: null },
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
    impact_companies: [
      { ticker: 'RELIANCE.NS', name: 'Reliance Industries', direction: 'bearish', excess_move_pct: -4.2, why: 'Refining margins compress as crude input costs rise.' },
      { ticker: 'ONGC.NS', name: 'ONGC', direction: 'bullish', excess_move_pct: 2.1, why: null },
    ],
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/feed-v2/alert/1']}>
      <AuthProvider>
        <Routes>
          <Route path="/feed-v2/alert/:id" element={<AlertLevel1Page />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe('AlertLevel1Page', () => {
  it('renders the summary, raw/sector move, and volume', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alert').mockResolvedValue(makeAlert());
    renderPage();
    await waitFor(() => expect(screen.getByText(/Crude prices jumped/)).toBeInTheDocument());
    expect(screen.getByText('-4.8%')).toBeInTheDocument();
    expect(screen.getByText('-0.6%')).toBeInTheDocument();
    expect(screen.getByText('3.1× average volume')).toBeInTheDocument();
  });

  it('renders one impact-core row per directly-affected company, with why when present', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alert').mockResolvedValue(makeAlert());
    renderPage();
    await waitFor(() => expect(screen.getByText('RELIANCE.NS')).toBeInTheDocument());
    expect(screen.getByText('ONGC.NS')).toBeInTheDocument();
    expect(screen.getByText('Refining margins compress as crude input costs rise.')).toBeInTheDocument();
  });

  it('navigates to the stock deep-dive when an impact-core row is clicked', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alert').mockResolvedValue(makeAlert());
    renderPage();
    await waitFor(() => screen.getByText('RELIANCE.NS'));
    fireEvent.click(screen.getByRole('button', { name: /RELIANCE\.NS/ }));
    expect(mockNavigate).toHaveBeenCalledWith('/feed-v2/stock/RELIANCE.NS?alertId=1');
  });

  it('renders a door to the ripple level', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alert').mockResolvedValue(makeAlert());
    renderPage();
    await waitFor(() => screen.getByText(/Crude prices jumped/));
    expect(screen.getByRole('link', { name: /See ripple/ })).toHaveAttribute('href', '/feed-v2/alert/1/ripple');
  });

  it('shows "Alert not found" when the fetch fails', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alert').mockRejectedValue(new Error('404'));
    renderPage();
    await waitFor(() => expect(screen.getByText('Alert not found.')).toBeInTheDocument());
  });
});
