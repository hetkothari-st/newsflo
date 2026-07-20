import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import AlertCascadePage from './AlertCascadePage';
import { AuthProvider } from '../lib/auth';
import { LanguageProvider } from '../lib/language';
import * as api from '../lib/api';
import type { Alert } from '../lib/api';

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

const directCompany = {
  company_id: 1, ticker: 'RIL', name: 'Reliance Industries', index_tier: 'NIFTY50', sector: 'oil_gas',
  direction: 'bullish' as const, magnitude_low: 2, magnitude_high: 4, rationale: 'Refiner margins widen.',
  key_points: [], confidence_score: 50, time_horizon: 'Short-Term', basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN' as const,
  in_my_holdings: false, past_mentions: [], impact_level: 'direct' as const, parent_company_id: null,
};

const indirectCompany = {
  company_id: 2, ticker: 'TSM', name: 'TSMC', index_tier: 'NIFTY50', sector: 'it',
  direction: 'bearish' as const, magnitude_low: 1, magnitude_high: 2, rationale: 'Fabs Reliance-adjacent chips.',
  key_points: [], confidence_score: 20, time_horizon: 'Medium-Term', basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN' as const,
  in_my_holdings: false, past_mentions: [], impact_level: 'indirect_l1' as const, parent_company_id: 1,
};

function alert(overrides: Partial<Alert> = {}): Alert {
  return {
    id: 1,
    category: 'oil_energy',
    category_label: 'Oil & Energy',
    created_at: '2026-07-14T00:00:00Z',
    article: { id: 1, title: 'Crude prices ease on supply news', url: 'https://example.com', image_url: null },
    companies: [directCompany],
    ...overrides,
  };
}

function renderPage(id = '1') {
  return render(
    <LanguageProvider>
      <AuthProvider>
        <MemoryRouter initialEntries={[`/alerts/${id}/charts/cascade`]}>
          <Routes>
            <Route path="/alerts/:id/charts/cascade" element={<AlertCascadePage />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </LanguageProvider>,
  );
}

describe('AlertCascadePage', () => {
  it('fetches the alert by route id and shows the article title', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alert());
    renderPage('1');
    await waitFor(() => expect(screen.getByText('Crude prices ease on supply news')).toBeInTheDocument());
  });

  it('shows an error state when the fetch fails', async () => {
    vi.spyOn(api, 'getAlert').mockRejectedValue(new Error('Alert not found'));
    renderPage('999');
    await waitFor(() => expect(screen.getByText('Alert not found')).toBeInTheDocument());
  });

  it('defaults to Drilldown, showing the full cascade including indirect companies', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alert({ companies: [directCompany, indirectCompany] }));
    renderPage('1');

    await waitFor(() => expect(screen.getByText('RIL')).toBeInTheDocument());
    expect(screen.getByText('TSM')).toBeInTheDocument();
  });

  it('Normal breadth hides indirect companies; Drilldown brings them back', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alert({ companies: [directCompany, indirectCompany] }));
    renderPage('1');

    await waitFor(() => expect(screen.getByText('TSM')).toBeInTheDocument());

    fireEvent.click(screen.getByText('Normal'));
    await waitFor(() => expect(screen.queryByText('TSM')).not.toBeInTheDocument());
    expect(screen.getByText('RIL')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Drilldown'));
    await waitFor(() => expect(screen.getByText('TSM')).toBeInTheDocument());
  });
});
