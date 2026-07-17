import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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

const directCompany = {
  company_id: 1, ticker: 'RIL', name: 'Reliance Industries', index_tier: 'NIFTY50', sector: 'oil_gas',
  direction: 'bullish' as const, magnitude_low: 2, magnitude_high: 4, rationale: 'Refiner margins widen.',
  key_points: [], confidence_score: 50, time_horizon: 'Short-Term', basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN' as const,
  in_my_holdings: false, past_mentions: [],
};

const inferredCompany = {
  company_id: 2, ticker: 'ONGC', name: 'Oil and Natural Gas Corporation', index_tier: 'NIFTY50', sector: 'oil_gas',
  direction: 'bearish' as const, magnitude_low: 1, magnitude_high: 2, rationale: 'Sector-wide pressure on crude producers.',
  key_points: [], confidence_score: 30, time_horizon: 'Short-Term', basis: 'sector_inference', confidence: 'llm_estimate', market: 'IN' as const,
  in_my_holdings: false, past_mentions: [],
};

const indirectCompany = {
  company_id: 3, ticker: 'TSM', name: 'TSMC', index_tier: 'NIFTY50', sector: 'it',
  direction: 'bearish' as const, magnitude_low: 1, magnitude_high: 2, rationale: 'Fabs Reliance-adjacent chips.',
  key_points: [], confidence_score: 20, time_horizon: 'Medium-Term', basis: 'direct_mention', confidence: 'llm_estimate', market: 'IN' as const,
  in_my_holdings: false, past_mentions: [], impact_level: 'indirect_l1', parent_company_id: 1,
};

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
    await waitFor(() => expect(screen.getByText('Crude prices ease on supply news')).toBeInTheDocument());
  });

  it('shows the pager labels for all six chart types', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alert());
    renderPage('1');
    await waitFor(() => expect(screen.getByText('Sector')).toBeInTheDocument());
    expect(screen.getByText('Tier')).toBeInTheDocument();
    expect(screen.getByText('Impact')).toBeInTheDocument();
    expect(screen.getByText('Split')).toBeInTheDocument();
    expect(screen.getByText('Confidence')).toBeInTheDocument();
    expect(screen.getByText('Timeline')).toBeInTheDocument();
  });

  it('advances to the next chart type when the pager control is clicked', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alert());
    renderPage('1');
    await waitFor(() => expect(screen.getByText('RIL')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Tier'));
    // Tier view renders the same company under a tier-row label instead of a sector tile.
    await waitFor(() => expect(screen.getByText('Nifty 50')).toBeInTheDocument());
  });

  it('shows an error state when the fetch fails', async () => {
    vi.spyOn(api, 'getAlert').mockRejectedValue(new Error('Alert not found'));
    renderPage('999');
    await waitFor(() => expect(screen.getByText('Alert not found')).toBeInTheDocument());
  });

  it('Normal view shows direct and sector-inferred companies (both impact_level=direct); Drilldown adds indirect ones too', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alert({ companies: [directCompany, inferredCompany, indirectCompany] }));
    renderPage('1');
    // Normal: both direct_mention (RIL) and sector_inference (ONGC) count as
    // impact_level="direct" -- only genuinely indirect companies are hidden.
    await waitFor(() => expect(screen.getByText('RIL')).toBeInTheDocument());
    expect(screen.getByText('ONGC')).toBeInTheDocument();
    expect(screen.queryByText('TSM')).not.toBeInTheDocument();

    fireEvent.click(screen.getByText('Drilldown'));
    await waitFor(() => expect(screen.getByText('TSM')).toBeInTheDocument());
    expect(screen.getByText('RIL')).toBeInTheDocument();
    expect(screen.getByText('ONGC')).toBeInTheDocument();
  });

  it('shows the no-direct-companies message in Normal view when every company is indirect', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alert({ companies: [indirectCompany] }));
    renderPage('1');
    await waitFor(() =>
      expect(
        screen.getByText('No directly-confirmed companies for this alert — try Drilldown for the wider sector picture.'),
      ).toBeInTheDocument(),
    );
  });

  it('shows the Levels tab and groups an indirect company under its parent', async () => {
    vi.spyOn(api, 'getAlert').mockResolvedValue(alert({ companies: [directCompany, indirectCompany] }));
    renderPage('1');
    await waitFor(() => expect(screen.getByText('Levels')).toBeInTheDocument());
    fireEvent.click(screen.getByText('Drilldown'));
    fireEvent.click(screen.getByText('Levels'));
    await waitFor(() => expect(screen.getByText('Direct Impact')).toBeInTheDocument());
    expect(screen.getByText('Indirect Impact — Level 1')).toBeInTheDocument();
    expect(screen.getByText(/via Reliance Industries/i)).toBeInTheDocument();
  });
});
