import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import StockDeepDivePage from './StockDeepDivePage';
import * as feedV2Api from '../lib/feedV2Api';
import type { StockDeepDive } from '../lib/feedV2Api';
import { AuthProvider } from '../lib/auth';

function makeDeepDive(overrides: Partial<StockDeepDive> = {}): StockDeepDive {
  return {
    ticker: 'RELIANCE.NS',
    name: 'Reliance Industries',
    sector: 'oil_gas',
    cap_tier: 'LARGE',
    business_desc: 'Refines crude oil and runs retail fuel outlets.',
    market_cap: 1500000.0,
    pe: 24.7,
    in_my_holdings: false,
    excess_move_pct: -4.2,
    raw_move_pct: -4.8,
    sector_move_pct: -0.6,
    volume_multiple: 3.1,
    intensity: { score: 82, band: 'High', components: [{ label: 'excess', raw: -4.2, weight: 0.55, contribution: 45.1 }] },
    is_exposure_only: false,
    peers: [],
    ...overrides,
  };
}

function renderPage(ticker = 'RELIANCE.NS', search = '?alertId=42') {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={[`/feed-v2/stock/${ticker}${search}`]}>
        <Routes>
          <Route path="/feed-v2/stock/:ticker" element={<StockDeepDivePage />} />
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  );
}

describe('StockDeepDivePage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders header, metric tiles, and breakdown when alert context is present', async () => {
    vi.spyOn(feedV2Api, 'getStockDeepDive').mockResolvedValue(makeDeepDive());
    renderPage();

    await waitFor(() => expect(screen.getByText('Reliance Industries')).toBeInTheDocument());
    expect(screen.getByText('LARGE')).toBeInTheDocument();
    // '82' and 'High' render twice by design -- once in the header tile,
    // once in the inline IntensityBreakdownPopup (rendered inline, not in a
    // popup, per this task's brief) -- so assert on presence, not uniqueness.
    expect(screen.getAllByText('82').length).toBeGreaterThan(0);
    expect(screen.getAllByText('High').length).toBeGreaterThan(0);
    expect(screen.getByText(/4\.2%/)).toBeInTheDocument();
    expect(screen.getByText(/3\.1/)).toBeInTheDocument();
  });

  it('renders business description and market facts', async () => {
    vi.spyOn(feedV2Api, 'getStockDeepDive').mockResolvedValue(makeDeepDive());
    renderPage();

    await waitFor(() =>
      expect(screen.getByText('Refines crude oil and runs retail fuel outlets.')).toBeInTheDocument(),
    );
    expect(screen.getByText(/24\.7/)).toBeInTheDocument();
  });

  it('omits intensity/metric-tile section when no alert context is present', async () => {
    vi.spyOn(feedV2Api, 'getStockDeepDive').mockResolvedValue(
      makeDeepDive({ excess_move_pct: null, intensity: null, is_exposure_only: null }),
    );
    renderPage('RELIANCE.NS', '');

    await waitFor(() => expect(screen.getByText('Reliance Industries')).toBeInTheDocument());
    expect(screen.queryByText('High')).not.toBeInTheDocument();
  });

  it('renders sector peers sorted as returned, via PeerRow', async () => {
    vi.spyOn(feedV2Api, 'getStockDeepDive').mockResolvedValue(
      makeDeepDive({
        peers: [
          {
            ticker: 'ONGC.NS', name: 'ONGC', sector: 'oil_gas', cap_tier: 'LARGE',
            business_desc: null, direction: 'bearish', excess_move_pct: -0.3,
            intensity: { score: 20, band: 'Low', components: [] }, is_exposure_only: false,
            in_my_holdings: false,
          },
        ],
      }),
    );
    renderPage();

    await waitFor(() => expect(screen.getByText('ONGC.NS')).toBeInTheDocument());
  });

  it('renders a not-found message when the ticker does not exist', async () => {
    vi.spyOn(feedV2Api, 'getStockDeepDive').mockRejectedValue(new Error('Stock not found'));
    renderPage('NOPE.NS');

    await waitFor(() => expect(screen.getByText(/not found/i)).toBeInTheDocument());
  });
});
