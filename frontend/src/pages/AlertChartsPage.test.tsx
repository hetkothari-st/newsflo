import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import AlertChartsPage from './AlertChartsPage';
import { AuthProvider } from '../lib/auth';
import { LanguageProvider } from '../lib/language';
import { ThemeProvider } from '../lib/theme';
import * as api from '../lib/api';
import type { Alert } from '../lib/api';

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

function alert(overrides: Partial<Alert> = {}): Alert {
  return {
    id: 1,
    category: 'oil_energy',
    category_label: 'Oil & Energy',
    created_at: '2026-07-14T00:00:00Z',
    article: { id: 1, title: 'Crude prices ease on supply news', url: 'https://example.com', image_url: null },
    companies: [{
      company_id: 1, ticker: 'RIL', name: 'Reliance Industries', index_tier: 'NIFTY50', sector: 'oil_gas',
      direction: 'bullish', magnitude_low: 2, magnitude_high: 4, rationale: 'Refiner margins widen.',
      key_points: [], confidence_score: 50, time_horizon: 'Short-Term', basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN',
      in_my_holdings: false, past_mentions: [],
    }],
    ...overrides,
  };
}

function renderPage(id = '1') {
  return render(
    <ThemeProvider>
      <LanguageProvider>
        <AuthProvider>
          <MemoryRouter initialEntries={[`/alerts/${id}/charts`]}>
            <Routes>
              <Route path="/alerts/:id/charts" element={<AlertChartsPage />} />
              <Route path="/alerts/:id" element={<p>Affected companies destination</p>} />
            </Routes>
          </MemoryRouter>
        </AuthProvider>
      </LanguageProvider>
    </ThemeProvider>,
  );
}

describe('AlertChartsPage', () => {
  it('fetches the alert by route id and shows the article title', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alert());
    renderPage('1');

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Crude prices ease on supply news' })).toBeInTheDocument(),
    );
  });

  it('shows an error state when the fetch fails', async () => {
    vi.spyOn(api, 'getAlert').mockRejectedValue(new Error('Alert not found'));
    renderPage('999');

    await waitFor(() => expect(screen.getByText('Alert not found')).toBeInTheDocument());
  });

  it('shows one chart at a time and advances with the next control', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alert());
    renderPage('1');

    expect(await screen.findByText('Multi-Level Impact Tree')).toBeInTheDocument();
    expect(screen.queryByText('Ripple Effect Graph')).not.toBeInTheDocument();
    expect(screen.getByText('Chart 1 of 10')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Next chart' }));

    expect(screen.getByText('Ripple Effect Graph')).toBeInTheDocument();
    expect(screen.queryByText('Multi-Level Impact Tree')).not.toBeInTheDocument();
    expect(screen.getByText('Chart 2 of 10')).toBeInTheDocument();
  });

  it('moves between charts with horizontal swipe gestures and stops at the boundaries', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alert());
    renderPage('1');

    const carousel = await screen.findByTestId('chart-carousel');
    expect(screen.getByRole('button', { name: 'Previous chart' })).toBeDisabled();

    fireEvent.touchStart(carousel, { touches: [{ clientX: 240, clientY: 100 }] });
    fireEvent.touchMove(carousel, { touches: [{ clientX: 120, clientY: 105 }] });
    fireEvent.touchEnd(carousel, { changedTouches: [{ clientX: 120, clientY: 105 }] });

    expect(screen.getByText('Chart 2 of 10')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Previous chart' }));
    expect(screen.getByText('Chart 1 of 10')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Previous chart' })).toBeDisabled();
  });

  it('takes the user directly back to affected companies', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alert());
    renderPage('1');

    fireEvent.click(await screen.findByRole('button', { name: 'Affected companies' }));

    expect(screen.getByText('Affected companies destination')).toBeInTheDocument();
  });
});
