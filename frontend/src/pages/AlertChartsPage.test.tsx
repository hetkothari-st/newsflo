import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import AlertChartsPage from './AlertChartsPage';
import { AuthProvider } from '../lib/auth';
import { LanguageProvider } from '../lib/language';
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
    companies: [
      {
        company_id: 1, ticker: 'RIL', name: 'Reliance Industries', index_tier: 'NIFTY50', sector: 'oil_gas',
        direction: 'bullish', magnitude_low: 2, magnitude_high: 4, rationale: 'Refiner margins widen.',
        key_points: [], confidence_score: 50, time_horizon: 'Short-Term', basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN',
        in_my_holdings: false, past_mentions: [],
      },
    ],
    ...overrides,
  };
}

function renderPage(id = '1') {
  return render(
    <LanguageProvider>
      <AuthProvider>
        <MemoryRouter initialEntries={[`/alerts/${id}/charts`]}>
          <Routes>
            <Route path="/alerts/:id/charts" element={<AlertChartsPage />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </LanguageProvider>,
  );
}

describe('AlertChartsPage', () => {
  it('fetches the alert by route id and shows the article title', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alert());
    renderPage('1');
    // The title also appears inside ImpactTree's news node, so scope to the page heading.
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Crude prices ease on supply news' })).toBeInTheDocument(),
    );
  });

  it('shows an error state when the fetch fails', async () => {
    vi.spyOn(api, 'getAlert').mockRejectedValue(new Error('Alert not found'));
    renderPage('999');
    await waitFor(() => expect(screen.getByText('Alert not found')).toBeInTheDocument());
  });

  it('renders all six grouping charts for an alert with mixed direct/indirect, bullish/bearish, multi-sector companies', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alert({
      event_type: 'crude_oil',
      companies: [
        {
          company_id: 1, ticker: 'RELIANCE.NS', name: 'Reliance Industries', index_tier: 'NIFTY50',
          sector: 'oil_gas', direction: 'bullish', magnitude_low: 2, magnitude_high: 4,
          rationale: 'Refiner margins widen.', key_points: ['Crude eases'], confidence_score: 80,
          time_horizon: 'Short-Term', basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN',
          in_my_holdings: false, past_mentions: [], impact_level: 'direct', parent_company_id: null,
        },
        {
          company_id: 2, ticker: 'INDIGO.NS', name: 'InterGlobe Aviation', index_tier: 'NIFTY50',
          sector: 'railways_transport', direction: 'bearish', magnitude_low: 1, magnitude_high: 3,
          rationale: 'Fuel costs rise.', key_points: ['ATF costs up'], confidence_score: 55,
          time_horizon: 'Medium-Term', basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN',
          in_my_holdings: true, past_mentions: [], impact_level: 'indirect_l1', parent_company_id: 1,
        },
      ],
    }));
    renderPage('1');

    expect(await screen.findByText('Multi-Level Impact Tree')).toBeInTheDocument();
    expect(screen.getByText('Cascade Levels')).toBeInTheDocument();
    expect(screen.getByText('Confidence Tree')).toBeInTheDocument();
    expect(screen.getByText('Positive / Negative Split')).toBeInTheDocument();
    expect(screen.getByText('Timeline Tree')).toBeInTheDocument();
    expect(screen.getByText('Sector Tree')).toBeInTheDocument();
  });
});
